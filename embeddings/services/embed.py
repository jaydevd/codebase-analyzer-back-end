import logging
import traceback
from celery import shared_task, chord
from celery.exceptions import Retry as CeleryRetry
import re
import time
import tiktoken

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
  MAX_FILE_BYTES,
  CHUNK_TARGET_TOKENS,
  CHUNK_MAX_TOKENS,
  BATCH_MAX_CHUNKS,
  BATCH_MAX_TOKENS,
  REPO_MAX_TOKENS,
)
from github.services.github_app import github_service, clear_blob_cache
from github.models import GithubRepos, RepoBranch, RepoIndexStatus, BranchScan, BranchScanStatus, ScanError
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

  FILE_PRIORITY = {ext: priority for priority, exts in enumerate([
      {'.py', '.js', '.ts', '.jsx', '.tsx', '.go', '.rs', '.java', '.rb', '.php', '.c', '.cpp', '.h', '.hpp', '.cs', '.swift', '.kt'},
      {'.json', '.yaml', '.yml', '.toml', '.xml', '.ini', '.cfg'},
      {'.md', '.rst', '.txt', '.html', '.css', '.scss', '.less'},
  ]) for ext in exts}

  def priority(self, path: str) -> int:
    ext = '.' + path.split('.')[-1] if '.' in path else ''
    return self.FILE_PRIORITY.get(ext, 99)

  def filter_tree(self, tree_response: dict) -> list[dict]:
    all_blobs = [e for e in tree_response['tree'] if e['type'] == 'blob']
    return [e for e in all_blobs if self.should_index(e)]

  def get_indexed_blob_shas(self, owner: str, repo: str, branch: str, commit_sha: str) -> set[str]:
    existing_shas = set()
    next_offset = None
    while True:
      results, next_offset = qdrant.scroll(
          collection_name=QDRANT_COLLECTION,
          scroll_filter=Filter(
              must=[
                  FieldCondition(key="repo", match=MatchValue(value=f"{owner}/{repo}")),
                  FieldCondition(key="branch", match=MatchValue(value=branch)),
                  FieldCondition(key="commit_sha", match=MatchValue(value=commit_sha)),
              ]
          ),
          limit=10000,
          offset=next_offset,
      )
      for point in results:
          existing_shas.add(point.payload.get("blob_sha", ""))
      if not next_offset:
          break
    return existing_shas

  def embed_chunks_batch(self, batch: list[dict]) -> list[dict]:
    batch = [c for c in batch if c.get('text', '').strip()]
    if not batch:
        logger.warning("embed_chunks_batch received empty batch after filtering")
        return batch
    texts = [c['text'] for c in batch]
    result = voyage_client.embed(
        texts,
        model=VOYAGE_EMBEDDING_MODEL,
        input_type='document',
    )
    for chunk, embedding in zip(batch, result.embeddings):
        chunk['embedding'] = embedding
    return batch

  def chunk_file(self, path: str, content: str, target_tokens: int = CHUNK_TARGET_TOKENS, max_tokens: int = CHUNK_MAX_TOKENS) -> list[dict]:
    enc = tiktoken.get_encoding("cl100k_base")
    lines = content.splitlines()
    chunks = []
    current_chunk_lines = []
    current_tokens = 0
    start_line = 0

    boundary_pattern = re.compile(
        r'^\s*(def |async def |class |function |const |export |public |private |protected |fn )'
    )

    for i, line in enumerate(lines):
        line_tokens = len(enc.encode(line))
        is_boundary = boundary_pattern.match(line) and current_tokens > 0
        would_overflow = current_tokens + line_tokens > max_tokens
        past_target = current_tokens >= target_tokens

        if (would_overflow or (is_boundary and past_target)) and current_chunk_lines:
            text = '\n'.join(current_chunk_lines)
            if text.strip():
                chunks.append({
                    'text': text,
                    'chunk_index': len(chunks),
                    'start_line': start_line,
                    'end_line': i - 1,
                    'file_path': path,
                })
            current_chunk_lines = []
            current_tokens = 0
            start_line = i

        current_chunk_lines.append(line)
        current_tokens += line_tokens

    if current_chunk_lines:
        text = '\n'.join(current_chunk_lines)
        if text.strip():
            chunks.append({
                'text': text,
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
    for i in range(0, len(all_chunks), BATCH_MAX_CHUNKS):
        batches.append(all_chunks[i:i + BATCH_MAX_CHUNKS])
    logger.info("Created %s embedding batches (%s chunks/batch)", len(batches), BATCH_MAX_CHUNKS)
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


def _mark_index_partial(repo_id, branch, commit_sha, scan_id):
    now = get_unix_timestamp()
    RepoBranch.objects.filter(repo__repo_id=repo_id, name=branch).update(
        status=RepoIndexStatus.PARTIALLY_SCANNED,
        commit_sha=commit_sha,
        last_indexed_at=now,
    )
    if scan_id:
        BranchScan.objects.filter(id=scan_id).update(
            status=BranchScanStatus.PARTIALLY_SCANNED,
            completed_at=now,
        )
    logger.info("Indexing partial for repo=%s branch=%s (20M token cap reached)", repo_id, branch)


@shared_task(bind=True)
def index_branch_task(self, owner, repo, branch, commit_sha, tree_response, installation_id, repo_id, scan_id=None):
    try:
        service = EmbeddingService()

        logger.info("index_branch_task: preparing data for %s/%s (%s)", owner, repo, branch)

        filtered_files = service.filter_tree(tree_response)

        estimated_total = sum(e.get('size', 0) for e in filtered_files) // 4
        over_budget = estimated_total > REPO_MAX_TOKENS
        if over_budget:
            logger.warning(
                "Repo %s/%s exceeds 20M token budget (~%s estimated). Will index partially.",
                owner, repo, estimated_total,
            )

        # Item 5: Sort files by priority so important content gets indexed first
        filtered_files.sort(key=lambda e: service.priority(e['path']))

        clear_blob_cache()

        # Item 4: Check which blob SHAs are already indexed for this commit
        already_indexed = service.get_indexed_blob_shas(owner, repo, branch, commit_sha)
        if already_indexed:
            logger.info("Found %s already-indexed blobs for %s/%s @ %s", len(already_indexed), owner, repo, commit_sha)

        blob_sha_map = {}
        batches = []
        current_batch = []
        current_batch_tokens = 0
        total_embedded_tokens = 0
        hit_token_cap = False
        enc = tiktoken.get_encoding("cl100k_base")

        # Item 1: Token-aware batch size
        batch_max_tokens = max(BATCH_MAX_TOKENS, 1)

        for entry in filtered_files:
            if hit_token_cap:
                break

            # Item 4: Skip already-indexed blobs
            if entry['sha'] in already_indexed:
                blob_sha_map[entry['path']] = entry['sha']
                continue

            try:
                content = github_service.fetch_blob(installation_id, owner, repo, entry['sha'])
            except Exception as e:
                logger.warning("Skipping %s: %s", entry['path'], e)
                continue

            blob_sha_map[entry['path']] = entry['sha']
            file_chunks = service.chunk_file(entry['path'], content)

            for chunk in file_chunks:
                chunk_tokens = len(enc.encode(chunk['text']))
                if total_embedded_tokens + chunk_tokens > REPO_MAX_TOKENS:
                    hit_token_cap = True
                    break
                total_embedded_tokens += chunk_tokens
                # Item 1: Flush batch by token budget, not by chunk count
                if current_batch_tokens + chunk_tokens > batch_max_tokens and current_batch:
                    batches.append(current_batch)
                    current_batch = []
                    current_batch_tokens = 0
                current_batch.append(chunk)
                current_batch_tokens += chunk_tokens

        if current_batch:
            batches.append(current_batch)

        clear_blob_cache()

        if not batches:
            logger.warning("No indexable files for %s/%s (%s)", owner, repo, branch)
            _mark_index_success(repo_id, branch, commit_sha, scan_id)
            return

        # Item 6: Set status to INDEXING before dispatching batches
        RepoBranch.objects.filter(repo__repo_id=repo_id, name=branch).update(
            status=RepoIndexStatus.INDEXING,
        )
        if scan_id:
            BranchScan.objects.filter(id=scan_id).update(
                status=RepoIndexStatus.INDEXING,
            )

        logger.info(
            "Dispatching %s batch(es) via chord for %s/%s (partial=%s, tokens=%s, batch_max_tokens=%s)",
            len(batches), owner, repo, hit_token_cap, total_embedded_tokens, batch_max_tokens,
        )

        callback = (
            finalize_index.s(
                repo_id=repo_id,
                branch=branch,
                commit_sha=commit_sha,
                scan_id=scan_id,
                partially_scanned=hit_token_cap,
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
def finalize_index(results, repo_id, branch, commit_sha, scan_id, partially_scanned=False):
    failed_count = sum(1 for r in results if not r)
    total = len(results)

    if failed_count == 0:
        if partially_scanned:
            _mark_index_partial(repo_id, branch, commit_sha, scan_id)
        else:
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
        batch = [c for c in batch if c.get('text', '').strip()]
        if not batch:
            logger.warning("Batch had no non-empty chunks, skipping")
            return True
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
        if isinstance(e, CeleryRetry):
            raise

        if "429" in str(e) or "Too Many Requests" in str(e):
            retries = self.request.retries
            backoff = 20 * (2 ** retries)
            logger.warning("429 rate limit — retry %s/%s in %.0fs", retries + 1, EMBED_BATCH_MAX_RETRIES, backoff)
            raise self.retry(exc=e, countdown=backoff)

        logger.error("embed_batch_task failed: %s", e)
        raise self.retry(exc=e)
