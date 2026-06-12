import os
from dotenv import load_dotenv

load_dotenv()

GITHUB_BASE_URL="https://api.github.com"
VOYAGE_API_KEY=os.getenv("VOYAGE_API_KEY", "")
QDRANT_URL=os.getenv("QDRANT_URL", "")
QDRANT_API_KEY=os.getenv("QDRANT_API_KEY", "")
QDRANT_COLLECTION=os.getenv("QDRANT_COLLECTION", "codebase_chunks")