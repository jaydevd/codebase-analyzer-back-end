import logging
import traceback
from celery import shared_task, chord
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
from github.models import GithubRepos, RepoBranch, RepoIndexStatus, BranchScan, ScanError
from common.models import get_unix_timestamp
from embeddings.services.rate_limiter import VoyageRateLimiter

logger = logging.getLogger(__name__)
rate_limiter = VoyageRateLimiter()

EMBED_BATCH_MAX_RETRIES = 15


class EmbeddingService:

  def ensure_collection(self):
    existing = [c.name for c in qdrant.get_collections().collections]
    if QDRANT_COLLECTION not in existing:
        qdrant.create_collection(
            collection_name=QDRANT_COLLECTION,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )
        logger.info("Created collection: %s", QDRANT_COLLECTION)


  def stable_id(self, repo: str, file_path: str, chunk_index: int) -> str:
      key = f"{repo}:{file_path}:{chunk_index}"
      return str(uuid.UUID(hashlib.md5(key.encode()).hexdigest()))


  def store_chunks(
      self,
      chunks: list[dict],
      owner: str,
      repo: str,
      branch: str,
      commit_sha: str,
      blob_sha_map: dict[str, str],
  ):
    self.ensure_collection()

    points = []
    for chunk in chunks:
        if 'embedding' not in chunk:
            logger.warning("Skipping chunk %s for %s — embedding missing", chunk.get('chunk_index'), chunk.get('file_path'))
            continue

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
                'text':         chunk['text'],
            }
        ))

    for i in range(0, len(points), 100):
        batch_points = points[i: i + 100]
        qdrant.upsert(
            collection_name=QDRANT_COLLECTION,
            points=batch_points,
        )
        logger.info("Stored %s/%s points in Qdrant", min(i + 100, len(points)), len(points))

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
    texts = [c['text'] for c in batch]
    result = voyage_client.embed(
        texts,
        model=VOYAGE_EMBEDDING_MODEL,
        input_type='document',
    )
    for chunk, embedding in zip(batch, result.embeddings):
        chunk['embedding'] = embedding
    return batch

  def chunk_file(self, path: str, content: str, max_chars: int = 1500) -> list[dict]:
    lines = content.splitlines()
    chunks = []
    current_chunk_lines = []
    current_chars = 0
    start_line = 0

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
    all_chunks = []
    for path, content in file_contents.items():
        file_chunks = self.chunk_file(path, content)
        all_chunks.extend(file_chunks)
    logger.info("Total chunks: %s", len(all_chunks))
    return all_chunks

  def group_batches(self, all_chunks: list[dict]) -> list[list[dict]]:
    batches = []
    current_batch = []
    current_tokens = 0

    for chunk in all_chunks:
        chunk_tokens = rate_limiter.estimate_tokens([chunk['text']])
        if current_tokens + chunk_tokens > 2500 and current_batch:
            batches.append(current_batch)
            current_batch = []
            current_tokens = 0

        current_batch.append(chunk)
        current_tokens += chunk_tokens

    if current_batch:
        batches.append(current_batch)

    logger.info("Created %s embedding batches", len(batches))
    return batches

  def index_branch(
    self,
    owner: str,
    repo: str,
    branch: str,
    commit_sha: str,
    tree_response: dict,
    installation_id: int
  ):
      logger.info("Step 1: Filtering tree...")
      filtered_files = self.filter_tree(tree_response)

      logger.info("Step 2: Fetching file contents...")
      file_contents = github_service.fetch_all_blobs(installation_id, owner, repo, filtered_files)

      blob_sha_map = {e['path']: e['sha'] for e in filtered_files}

      logger.info("Step 3: Chunking files...")
      all_chunks = self.chunk_all_files(file_contents)

      logger.info("Step 4: Grouping into batches...")
      batches = self.group_batches(all_chunks)

      logger.info("Step 5: Dispatching %s embedding batch tasks via chord...", len(batches))

      if not batches:
          logger.warning("No chunks to index — branch has no indexable files")
          return None

      return {
          'batches': batches,
          'blob_sha_map': blob_sha_map,
          'filtered_files': filtered_files,
          'all_chunks': all_chunks,
      }


embedding_service = EmbeddingService()


def _mark_index_success(repo_id, branch, commit_sha, scan_id):
    now = get_unix_timestamp()
    RepoBranch.objects.filter(repo__repo_id=repo_id, name=branch).update(
        status=RepoIndexStatus.SCANNED,
        commit_sha=commit_sha,
        last_indexed_at=now,
    )
    if scan_id:
        BranchScan.objects.filter(id=scan_id).update(
            status=RepoIndexStatus.SCANNED,
            completed_at=now,
        )
    logger.info("Indexing complete for repo=%s branch=%s", repo_id, branch)


def _mark_index_failed(repo_id, branch, scan_id, error_message, error_type="IndexError", stack_trace=None):
    now = get_unix_timestamp()
    RepoBranch.objects.filter(repo__repo_id=repo_id, name=branch).update(
        status=RepoIndexStatus.FAILED,
        last_error_message=error_message,
    )
    if scan_id:
        BranchScan.objects.filter(id=scan_id).update(
            status=RepoIndexStatus.FAILED,
            completed_at=now,
        )
        ScanError.objects.create(
            branch_scan_id=scan_id,
            error_message=error_message,
            error_type=error_type,
            stack_trace=stack_trace or "",
        )
    logger.error("Indexing failed for repo=%s branch=%s: %s", repo_id, branch, error_message)


@shared_task(bind=True)
def index_branch_task(self, owner, repo, branch, commit_sha, tree_response, installation_id, repo_id, scan_id=None):
    try:
        service = EmbeddingService()

        logger.info("index_branch_task: preparing data for %s/%s (%s)", owner, repo, branch)

        filtered_files = service.filter_tree(tree_response)
        file_contents = github_service.fetch_all_blobs(installation_id, owner, repo, filtered_files)
        blob_sha_map = {e['path']: e['sha'] for e in filtered_files}
        all_chunks = service.chunk_all_files(file_contents)
        batches = service.group_batches(all_chunks)

        if not batches:
            logger.warning("No indexable files for %s/%s (%s)", owner, repo, branch)
            _mark_index_success(repo_id, branch, commit_sha, scan_id)
            return

        logger.info("Dispatching %s batch(es) via chord for %s/%s", len(batches), owner, repo)

        callback = (
            finalize_index.s(
                repo_id=repo_id,
                branch=branch,
                commit_sha=commit_sha,
                scan_id=scan_id,
            )
            .on_error(
                handle_chord_error.s(
                    repo_id=repo_id,
                    branch=branch,
                    scan_id=scan_id,
                )
            )
        )
        
        header = [
            embed_batch_task.s(
                batch=batch,
                owner=owner,
                repo=repo,
                branch=branch,
                commit_sha=commit_sha,
                blob_sha_map=blob_sha_map,
            )
            for batch in batches
        ]
        
        chord(header)(callback)

        header = [
            embed_batch_task.s(
                batch=batch,
                owner=owner,
                repo=repo,
                branch=branch,
                commit_sha=commit_sha,
                blob_sha_map=blob_sha_map,
            )
            for batch in batches
        ]

        chord_result = chord(header)(callback)

        logger.info("Chord dispatched for %s/%s — %s batch(es)", owner, repo, len(batches))

    except Exception as e:
        logger.exception("index_branch_task failed during preparation")
        _mark_index_failed(
            repo_id, branch, scan_id,
            error_message=str(e),
            error_type=type(e).__name__,
            stack_trace=traceback.format_exc(),
        )


@shared_task
def finalize_index(results, repo_id, branch, commit_sha, scan_id):
    failed_count = sum(1 for r in results if not r)
    total = len(results)

    if failed_count == 0:
        _mark_index_success(repo_id, branch, commit_sha, scan_id)
    else:
        _mark_index_failed(
            repo_id, branch, scan_id,
            error_message=f"{failed_count}/{total} embedding batch(es) failed",
            error_type="EmbeddingBatchError",
        )


@shared_task
def handle_chord_error(request, exc, traceback, repo_id, branch, scan_id):
    _mark_index_failed(
        repo_id, branch, scan_id,
        error_message=f"Chord error: {exc}",
        error_type=type(exc).__name__,
        stack_trace=traceback,
    )


@shared_task(bind=True, max_retries=EMBED_BATCH_MAX_RETRIES, default_retry_delay=60)
def embed_batch_task(self, batch, owner, repo, branch, commit_sha, blob_sha_map):
    try:
        texts = [c['text'] for c in batch]
        tokens = rate_limiter.estimate_tokens(texts)

        wait_time = rate_limiter.calculate_wait_time(tokens)
        if wait_time > 0:
            logger.info("Rate limit: delaying batch by %.1fs (tokens=%s)", wait_time, tokens)
            raise self.retry(countdown=wait_time)

        rate_limiter.consume(tokens)

        service = EmbeddingService()
        embedded_batch = service.embed_chunks_batch(batch)
        service.store_chunks(embedded_batch, owner, repo, branch, commit_sha, blob_sha_map)

        logger.debug("Batch embedded and stored successfully (%s chunks)", len(batch))
        return True

    except Exception as e:
        if isinstance(e, self.retry):
            raise

        if "429" in str(e) or "Too Many Requests" in str(e):
            retries = self.request.retries
            backoff = 20 * (2 ** retries)
            logger.warning("429 rate limit — retry %s/%s in %.0fs", retries + 1, EMBED_BATCH_MAX_RETRIES, backoff)
            raise self.retry(exc=e, countdown=backoff)

        logger.error("embed_batch_task failed: %s", e)
        raise self.retry(exc=e)
