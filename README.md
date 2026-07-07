# AI-Powered Codebase Analyzer

Backend service for indexing codebases, storing embeddings, and answering natural-language questions over repository context using retrieval-augmented generation.

## What It Does

- Ingests GitHub repositories and branches
- Downloads source files and builds an indexable code tree
- Chunks code, generates embeddings, and stores vectors in Qdrant
- Answers questions with semantic retrieval plus LLM generation
- Tracks chat sessions and history server-side
- Handles authentication through email/password, Google OAuth, and GitHub OAuth
- Exposes Swagger/OpenAPI documentation for all APIs

## Stack

| Layer | Technology |
|---|---|
| Framework | Django 6.0 / Django REST Framework 3.17 |
| Auth | JWT via `djangorestframework-simplejwt`, Google OAuth, GitHub OAuth |
| Database | PostgreSQL |
| Cache | Redis |
| Background Jobs | Celery |
| Vector Search | Qdrant |
| Embeddings | Voyage AI |
| LLM Orchestration | LangChain |
| LLM Providers | Anthropic, Google Gemini, OpenAI |
| API Docs | drf-spectacular + Swagger UI |
| Server | Gunicorn |

## Architecture

```
Client
  -> Django REST API
      -> Auth: register, login, OAuth, JWT
      -> GitHub: install, callback, repo browsing, webhook, scan reports
      -> Embed: repository indexing -> embeddings -> Qdrant
      -> Chat: retrieval from vector store + LLM response + chat history
```

## Repository Layout

```
codebase-analyzer-back-end/
├── auth/                    # Authentication, OAuth, user profile, password reset
├── github/                  # GitHub App, repo listing, webhook, download, scan report
├── embeddings/              # Repo indexing entry points
├── core/                    # Chat/query flows, sessions, history
├── common/                  # Shared responses, pagination, swagger helpers, constants
├── codebase_analyzer_back_end/
│   ├── settings/            # Environment-driven Django settings
│   ├── urls.py              # Root URL routing
│   ├── celery.py            # Celery application
│   └── views.py             # Health check
├── docs/                    # Supporting API and implementation docs
├── postman/                 # Postman resources
├── manage.py
├── requirements.txt
├── runtime.txt
└── Procfile
```

## Main API Routes

| Prefix | Purpose |
|---|---|
| `auth/` | Registration, login, token refresh, logout, profile, password reset, Google OAuth, GitHub OAuth |
| `api/github/` | GitHub install URL, callback, repo listing/search, branches, scan reports, download, disconnect, webhook |
| `embed/` | Repository indexing trigger |
| `api/chat/` | New session, session details, query, history |
| `health/` | Health check |
| `api/schema/` | OpenAPI schema |
| `api/docs/` | Swagger UI |
| `admin/` | Django admin |

Examples of notable endpoints:

- `POST /auth/register/`
- `POST /auth/login/`
- `POST /auth/token/refresh/`
- `GET /api/github/repos/`
- `POST /embed/repo/index/`
- `POST /api/chat/query/`
- `GET /api/docs/`

## Key Capabilities

### Authentication

- Email/password signup and login
- JWT access and refresh tokens
- Google OAuth callback flow
- GitHub OAuth callback flow
- Password reset flow

### GitHub Integration

- GitHub App installation URL generation
- OAuth / callback handling
- Repository browsing and search
- Branch listing
- Repository download support
- Scan reports
- Webhook processing

### Indexing Pipeline

- Accepts repository indexing requests
- Fetches repository content
- Chunks code into semantic units
- Generates embeddings
- Stores vectors for later retrieval

### Chat and Retrieval

- Creates and manages chat sessions
- Retrieves relevant repository context
- Generates answers through the configured LLM provider
- Keeps chat history available through the API

## Environment Setup

The application loads `.env` from the project root at startup.

Required infrastructure:

- PostgreSQL
- Redis
- Qdrant
- At least one LLM provider key
- Voyage AI API key for embeddings
- GitHub App credentials for repository access

Important environment variables:

| Variable | Description |
|---|---|
| `SECRET_KEY` | Django secret key |
| `ENVIRONMENT` | `development`, `staging`, or `production` |
| `DB_ENGINE`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | PostgreSQL settings |
| `REDIS_URL` | Redis connection string |
| `QDRANT_URL`, `QDRANT_API_KEY` | Qdrant configuration |
| `VOYAGE_API_KEY` | Embedding provider key |
| `ANTHROPIC_API_KEY` | Claude provider key |
| `GOOGLE_API_KEY` | Gemini provider key |
| `OPENAI_API_KEY` | OpenAI provider key |
| `GITHUB_APP_ID`, `GITHUB_APP_SLUG`, `GITHUB_PRIVATE_KEY`, `GITHUB_WEBHOOK_SECRET` | GitHub App settings |
| `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` | GitHub OAuth settings |
| `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET` | Google OAuth settings |
| `FRONTEND_URL` | Frontend origin |
| `PASSWORD_RESET_FRONTEND_URL` | Password reset redirect URL |
| `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` or `BREVO_SMTP_USERNAME`, `BREVO_SMTP_PASSWORD` | SMTP credentials |

## Local Development

```bash
git clone <repo-url>
cd codebase-analyzer-back-end

python -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env

python manage.py migrate
python manage.py runserver
```

## Background Workers

Celery is used for asynchronous processing:

```bash
celery -A codebase_analyzer_back_end worker -l info
```

Redis must be available and `REDIS_URL` must point to it.

## API Documentation

- Swagger UI: `/api/docs/`
- OpenAPI schema: `/api/schema/`

## Notes

- The backend is Django-based, not Express-based.
- Most endpoints require `Authorization: Bearer <access_token>`.
- Development settings default to the console email backend if SMTP credentials are not configured.
- Production deployments should set `DJANGO_SETTINGS_MODULE=codebase_analyzer_back_end.settings.production`.