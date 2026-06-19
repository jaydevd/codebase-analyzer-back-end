from celery import shared_task
import re
import time

from qdrant_client.models import (
    Distance, VectorParams, PointStruct, Filter,
    FieldCondition, MatchValue
)
import hashlib
import uuid
from common.constants import (
  QDRANT_COLLECTION,
  qdrant,
  voyage_client,
  VOYAGE_EMBEDDING_MODEL,
  EXCLUDED_DIRS,
  EXCLUDED_EXTENSIONS,
  EXCLUDED_FILENAMES,
  EMBED_BATCH_SIZE,
  VECTOR_SIZE,
  MAX_FILE_BYTES
)
from github.services.github_app import github_service
from embeddings.services.rate_limiter import VoyageRateLimiter

rate_limiter = VoyageRateLimiter()

class EmbeddingService:

  def ensure_collection(self):
    """Create the Qdrant collection if it doesn't exist yet."""
    existing = [c.name for c in qdrant.get_collections().collections]
    if QDRANT_COLLECTION not in existing:
        qdrant.create_collection(
            collection_name=QDRANT_COLLECTION,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )
        print(f"Created collection: {QDRANT_COLLECTION}")


  def stable_id(self, repo: str, file_path: str, chunk_index: int) -> str:
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
    print(f"[DEBUG] Preparing to store {len(chunks)} chunks in Qdrant")
    for chunk in chunks:
        if 'embedding' not in chunk:
            print(f"[DEBUG] Skipping chunk {chunk.get('chunk_index')} for {chunk.get('file_path')} as embedding is missing")
            continue  # skip failed embeddings

        point_id = self.stable_id(f"{owner}/{repo}", chunk['file_path'], chunk['chunk_index'])
        print(f"[DEBUG] Created Point ID: {point_id} for {owner}/{repo}:{chunk['file_path']}:{chunk['chunk_index']}")

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

    print(f"[DEBUG] Total points prepared for upsert: {len(points)}")
    # upsert in batches of 100
    for i in range(0, len(points), 100):
        batch_points = points[i: i + 100]
        print(f"[DEBUG] Upserting batch of {len(batch_points)} points to collection {QDRANT_COLLECTION}")
        qdrant.upsert(
            collection_name=QDRANT_COLLECTION,
            points=batch_points,
        )
        print(f"Stored {min(i + 100, len(points))}/{len(points)} points")

  def should_index(self, entry: dict) -> bool:
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
  
  def embed_chunks_batch(self, batch: list[dict]) -> list[dict]:
    """
    Adds an 'embedding' field to each chunk in a given batch.
    Designed to be called by a Celery task that has already checked rate limits.
    """
    texts = [c['text'] for c in batch]
    print(f"[DEBUG] Generating embeddings for batch of {len(batch)} chunks")

    result = voyage_client.embed(
        texts,
        model=VOYAGE_EMBEDDING_MODEL,
        input_type='document',   # 'document' for indexing, 'query' for queries
    )
    for chunk, embedding in zip(batch, result.embeddings):
        chunk['embedding'] = embedding
    print(f"[DEBUG] Successfully generated embeddings for batch of {len(batch)} chunks")

    return batch
  
  def chunk_file(self, path: str, content: str, max_chars: int = 1500) -> list[dict]:
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
  
  def index_branch(
    self,
    owner: str,
    repo: str,
    branch: str,
    commit_sha: str,
    tree_response: dict,
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

      print("Step 4: Dispatching embedding tasks...")
      
      # Group chunks into batches that are around 2000-3000 tokens
      batches = []
      current_batch = []
      current_tokens = 0
      
      for chunk in all_chunks:
          chunk_tokens = rate_limiter.estimate_tokens([chunk['text']])
          # If a single chunk is larger than target, just send it (should be rare)
          if current_tokens + chunk_tokens > 2500 and current_batch:
              batches.append(current_batch)
              current_batch = []
              current_tokens = 0
              
          current_batch.append(chunk)
          current_tokens += chunk_tokens
          
      if current_batch:
          batches.append(current_batch)
          
      print(f"[DEBUG] Created {len(batches)} batches for embedding")

      # Dispatch each batch as a separate Celery task
      for batch in batches:
          embed_batch_task.delay(batch, owner, repo, branch, commit_sha, blob_sha_map)

      print(f"✓ Queued {len(filtered_files)} files → {len(batches)} batches for embedding")
      return {
          'file_count': len(filtered_files),
          'chunk_count': len(all_chunks),
          'batch_count': len(batches),
          'commit_sha': commit_sha,
      }


embedding_service = EmbeddingService()


@shared_task(bind=True)
def index_branch_task(self, owner, repo, branch, commit_sha, tree_response, installation_id):
    try:
        print("[DEBUG] index_branch_task: imposing the embedding service")
        service = EmbeddingService()
        print("[DEBUG] index_branch_task: embedding service impose.")
        service.index_branch(owner, repo, branch, commit_sha, tree_response, installation_id)
        print("[DEBUG] index_branch_Task: calling index_branch method.")
    except Exception as e:
        print(f"[ERROR] index_branch_task failed: {e}")

@shared_task(bind=True, max_retries=None)
def embed_batch_task(self, batch, owner, repo, branch, commit_sha, blob_sha_map):
    try:
        texts = [c['text'] for c in batch]
        tokens = rate_limiter.estimate_tokens(texts)
        
        # Check rate limits
        wait_time = rate_limiter.calculate_wait_time(tokens)
        if wait_time > 0:
            print(f"[RATE LIMIT] Delaying execution by {wait_time:.1f}s (Tokens: {tokens})")
            raise self.retry(countdown=wait_time)
            
        # We have capacity, consume it
        rate_limiter.consume(tokens)
        
        service = EmbeddingService()
        embedded_batch = service.embed_chunks_batch(batch)
        service.store_chunks(embedded_batch, owner, repo, branch, commit_sha, blob_sha_map)
        
    except Exception as e:
        # Handle 429 specifically for exponential backoff if Voyage rate limited us
        if "429" in str(e) or "Too Many Requests" in str(e):
            # Calculate exponential backoff (e.g. 20s, 40s, 80s...)
            retries = self.request.retries
            backoff = 20 * (2 ** retries)
            print(f"[BACKOFF] Encountered 429. Retrying in {backoff}s. Attempt {retries + 1}")
            raise self.retry(exc=e, countdown=backoff)
            
        # If it's a Retry exception, let it propagate (for rate limiting logic)
        if "Retry" in str(e.__class__.__name__):
            raise
            
        print(f"[ERROR] embed_batch_task failed: {e}")
        # Could also add generic retry for other errors here
        raise self.retry(exc=e, countdown=60)