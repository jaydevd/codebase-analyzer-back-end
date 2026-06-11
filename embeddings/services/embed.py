from celery import shared_task
from github.services.github_app import GitHubAppService
import re
import voyageai
import time

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct, Filter,
    FieldCondition, MatchValue
)
import hashlib
import uuid
from common.constants import VOYAGE_API_KEY, QDRANT_URL, QDRANT_API_KEY

qdrant = QdrantClient(
    url=QDRANT_URL,        # e.g. "http://localhost:6333" or your Qdrant Cloud URL
    api_key=QDRANT_API_KEY # only needed for Qdrant Cloud
)

COLLECTION_NAME = 'codebase_chunks'
VECTOR_SIZE = 1024  # voyage-code-3 outputs 1024-dim vectors

voyage_client = voyageai.Client(api_key=VOYAGE_API_KEY)

EMBED_BATCH_SIZE = 128 
github_service = GitHubAppService()

EXCLUDED_DIRS = [
    'node_modules/', 'vendor/', '.git/', 'dist/', 'build/', 'out/',
    '__pycache__/', '.venv/', 'venv/', 'env/', 'coverage/', 'target/',
    '.next/', '.nuxt/', 'bin/', 'obj/',
]

EXCLUDED_EXTENSIONS = {
    '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.webp',
    '.mp4', '.mp3', '.wav', '.pdf', '.zip', '.tar', '.gz',
    '.min.js', '.min.css', '.map', '.pyc', '.pyo', '.class',
    '.dll', '.so', '.exe', '.dylib',
}

EXCLUDED_FILENAMES = {
    'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml',
    'Gemfile.lock', 'poetry.lock', 'Cargo.lock',
}

MAX_FILE_BYTES = 100_000

class EmbeddingService:

  def ensure_collection():
    """Create the Qdrant collection if it doesn't exist yet."""
    existing = [c.name for c in qdrant.get_collections().collections]
    if COLLECTION_NAME not in existing:
        qdrant.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )
        print(f"Created collection: {COLLECTION_NAME}")


  def stable_id(repo: str, file_path: str, chunk_index: int) -> str:
      """Deterministic UUID based on content identity — safe to upsert repeatedly."""
      key = f"{repo}:{file_path}:{chunk_index}"
      return str(uuid.UUID(hashlib.md5(key.encode()).hexdigest()))


  def store_chunks(
      self,
      chunks: list[dict],
      owner: str,
      repo: str,
      branch: str,
      commit_sha: str,
      blob_sha_map: dict[str, str],  # { file_path: blob_sha }
  ):
    self.ensure_collection()

    points = []
    for chunk in chunks:
        if 'embedding' not in chunk:
            continue  # skip failed embeddings

        point_id = self.stable_id(f"{owner}/{repo}", chunk['file_path'], chunk['chunk_index'])

        points.append(PointStruct(
            id=point_id,
            vector=chunk['embedding'],
            payload={
                'repo':         f"{owner}/{repo}",
                'branch':       branch,
                'commit_sha':   commit_sha,
                'file_path':    chunk['file_path'],
                'blob_sha':     blob_sha_map.get(chunk['file_path'], ''),
                'chunk_index':  chunk['chunk_index'],
                'start_line':   chunk['start_line'],
                'end_line':     chunk['end_line'],
                'text':         chunk['text'],   # store text so you don't re-fetch later
            }
        ))

    # upsert in batches of 100
    for i in range(0, len(points), 100):
        qdrant.upsert(
            collection_name=COLLECTION_NAME,
            points=points[i: i + 100],
        )
        print(f"Stored {min(i + 100, len(points))}/{len(points)} points")

  def should_index(entry: dict) -> bool:
    path = entry.get('path', '')
    size = entry.get('size', 0)
    filename = path.split('/')[-1]
    ext = '.' + filename.split('.')[-1] if '.' in filename else ''

    if any(path.startswith(d) for d in EXCLUDED_DIRS):
      return False
    if filename in EXCLUDED_FILENAMES:
      return False
    if ext in EXCLUDED_EXTENSIONS:
      return False
    if size and size > MAX_FILE_BYTES:
      return False
    return True
  
  def filter_tree(self, tree_response: dict) -> list[dict]:
    all_blobs = [e for e in tree_response['tree'] if e['type'] == 'blob']
    return [e for e in all_blobs if self.should_index(e)]
  
  def embed_chunks(chunks: list[dict]) -> list[dict]:
    """
    Adds an 'embedding' field to each chunk.
    Processes in batches to respect API limits.
    """
    for i in range(0, len(chunks), EMBED_BATCH_SIZE):
        batch = chunks[i: i + EMBED_BATCH_SIZE]
        texts = [c['text'] for c in batch]

        try:
            result = voyage_client.embed(
                texts,
                model='voyage-code-3',   # best model for code retrieval
                input_type='document',   # 'document' for indexing, 'query' for queries
            )
            for chunk, embedding in zip(batch, result.embeddings):
                chunk['embedding'] = embedding

        except Exception as e:
            print(f"Embedding batch {i} failed: {e}")
            time.sleep(2)  # back off and retry
            continue

        time.sleep(0.1)  # gentle rate limiting between batches
        print(f"Embedded {min(i + EMBED_BATCH_SIZE, len(chunks))}/{len(chunks)} chunks")

    return chunks
  
  def chunk_file(path: str, content: str, max_chars: int = 1500) -> list[dict]:
    """
    Splits file content into chunks at logical boundaries.
    Returns list of { text, chunk_index, start_line, end_line }
    """
    lines = content.splitlines()
    chunks = []
    current_chunk_lines = []
    current_chars = 0
    start_line = 0

    # Patterns that signal a logical boundary (works for Python, JS, TS, Go, etc.)
    boundary_pattern = re.compile(
        r'^\s*(def |async def |class |function |const |export |public |private |protected |fn )'
    )

    for i, line in enumerate(lines):
        is_boundary = boundary_pattern.match(line) and current_chars > 0
        would_overflow = (current_chars + len(line)) > max_chars

        if (is_boundary or would_overflow) and current_chunk_lines:
            chunks.append({
                'text': '\n'.join(current_chunk_lines),
                'chunk_index': len(chunks),
                'start_line': start_line,
                'end_line': i - 1,
                'file_path': path,
            })
            current_chunk_lines = []
            current_chars = 0
            start_line = i

        current_chunk_lines.append(line)
        current_chars += len(line)

    # flush the last chunk
    if current_chunk_lines:
        chunks.append({
            'text': '\n'.join(current_chunk_lines),
            'chunk_index': len(chunks),
            'start_line': start_line,
            'end_line': len(lines) - 1,
            'file_path': path,
        })

    return chunks


  def chunk_all_files(self, file_contents: dict[str, str]) -> list[dict]:
    """Chunk every file and return a flat list of all chunks with metadata."""
    all_chunks = []
    for path, content in file_contents.items():
        file_chunks = self.chunk_file(path, content)
        all_chunks.extend(file_chunks)
    print(f"Total chunks: {len(all_chunks)}")
    return all_chunks
  
  @shared_task
  def index_branch(
    self,
    owner: str,
    repo: str,
    branch: str,
    commit_sha: str,
    tree_response: dict,   # ← your existing res variable goes here
    installation_id: int
  ):
      print("Step 1: Filtering tree...")
      filtered_files = self.filter_tree(tree_response)

      print("Step 2: Fetching file contents...")
      file_contents = github_service.fetch_all_blobs(installation_id, owner, repo, filtered_files)

      # build a path → blob_sha map for storage metadata
      blob_sha_map = {e['path']: e['sha'] for e in filtered_files}

      print("Step 3: Chunking files...")
      all_chunks = self.chunk_all_files(file_contents)

      print("Step 4: Generating embeddings...")
      embedded_chunks = self.embed_chunks(all_chunks)

      print("Step 5: Storing in Qdrant...")
      self.store_chunks(embedded_chunks, owner, repo, branch, commit_sha, blob_sha_map)

      print(f"✓ Indexed {len(filtered_files)} files → {len(embedded_chunks)} chunks")
      return {
          'file_count': len(filtered_files),
          'chunk_count': len(embedded_chunks),
          'commit_sha': commit_sha,
      }
