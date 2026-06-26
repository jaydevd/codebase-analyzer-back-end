import os
from dotenv import load_dotenv

import voyageai
from qdrant_client import QdrantClient

load_dotenv()

# Github variables
GITHUB_BASE_URL="https://api.github.com"

# Voyage variables
VOYAGE_API_KEY=os.getenv("VOYAGE_API_KEY", "")
VOYAGE_EMBEDDING_MODEL=os.getenv("VOYAGE_EMBEDDING_MODEL", "voyage-code-3")
voyage_client = voyageai.Client(api_key=VOYAGE_API_KEY)

# LLM variables
LLM_PROVIDER=os.getenv("LLM_PROVIDER", "anthropic").strip().lower()
ANTHROPIC_API_KEY=os.getenv("ANTHROPIC_API_KEY", "")
GOOGLE_API_KEY=os.getenv("GOOGLE_API_KEY", "")
OPENAI_API_KEY=os.getenv("OPENAI_API_KEY", "")
LLM_MODEL=os.getenv("LLM_MODEL", "claude-3-5-sonnet-latest")
LLM_TEMPERATURE=float(os.getenv("LLM_TEMPERATURE", "0"))
LLM_MAX_TOKENS=int(os.getenv("LLM_MAX_TOKENS", "4096"))

# Qdrant variables
QDRANT_URL=os.getenv("QDRANT_URL", "")
QDRANT_API_KEY=os.getenv("QDRANT_API_KEY", "")
QDRANT_COLLECTION=os.getenv("QDRANT_COLLECTION", "codebase_chunks")

qdrant = QdrantClient(
    url=QDRANT_URL,        # e.g. "http://localhost:6333" or your Qdrant Cloud URL
    api_key=QDRANT_API_KEY # only needed for Qdrant Cloud
)

# Embeddings variables
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

EMBED_BATCH_SIZE = 128
VECTOR_SIZE = 1024  # voyage-code-3 outputs 1024-dim vectors
MAX_FILE_BYTES = 100_000

# Token and memory budget
CHUNK_TARGET_TOKENS = 600       # target per chunk for retrieval granularity
CHUNK_MAX_TOKENS = 2000         # hard max per chunk (small files embedded whole)
BATCH_MAX_CHUNKS = 128          # chunks per API call (voyage-code-3 sweet spot)
REPO_MAX_TOKENS = 20_000_000    # hard cap per repo ingestion budget
QUERY_MAX_CONTEXT_TOKENS = 40_000  # LLM context token budget
CHAT_HISTORY_MAX_MESSAGES = 20     # recent exchanges to include in context
MAX_ATTACHED_FILE_BYTES = 1_000_000  # 1MB limit on attached file content
