# API Reference — Frontend Integration Guide

---

## Authentication

All endpoints except `/auth/*` and webhooks require a JWT `access_token` header:

```
Authorization: Bearer <access_token>
```

---

## 1. Scan Report (NEW)

Fetch scan status for all branches of a repo, including previous scan history.

### `GET /api/github/repos/<repo_id>/scan-report/`

**Response 200:**
```json
{
  "status": 200,
  "data": [
    {
      "branch": "main",
      "status": "scanned",
      "last_indexed_at": 1719000000,
      "previous_scans": [
        {
          "commit_url": "https://github.com/org/repo/commit/abc123",
          "commit_sha": "abc123",
          "indexed_at": 1719000000
        },
        {
          "commit_url": "https://github.com/org/repo/commit/def456",
          "commit_sha": "def456",
          "indexed_at": 1718900000
        }
      ]
    },
    {
      "branch": "develop",
      "status": "failed",
      "last_indexed_at": null,
      "previous_scans": [
        {
          "commit_url": "https://github.com/org/repo/commit/789ghi",
          "commit_sha": "789ghi",
          "indexed_at": 1718800000
        }
      ]
    }
  ],
  "message": "Scan report fetched successfully org/repo"
}
```

**Status values:** `not_scanned`, `scanning`, `scanned`, `failed`

---

## 2. Index / Scan a Branch (MODIFIED)

Previously just a Celery trigger. Now also creates a `BranchScan` record to track the scan attempt.

### `POST /embed/repo/index/`

**Request:**
```json
{
  "repo_id": 123456,
  "branch": "main",
  "commit_sha": "abc123def456"
}
```

**Response 200:**
```json
{
  "status": 200,
  "data": null,
  "message": "Indexing main in background."
}
```

**Flow:**
1. Sets `RepoBranch.status = "scanning"`
2. Creates a `BranchScan` record (`status = "scanning"`)
3. Dispatches Celery task `index_branch_task`
4. On **success**: `BranchScan.status = "scanned"`, `completed_at` set, `RepoBranch` updated
5. On **failure**: `BranchScan.status = "failed"`, `completed_at` set, `ScanError` created with error details, `RepoBranch.status = "failed"`, `last_error_message` stored

---

## 3. Chat / Query (MODIFIED)

The `history` field is **now optional**. Chat history is automatically managed server-side via LangChain's `RunnableWithMessageHistory` with `thread_id = chat_id`. The LLM remembers previous messages in the same session without the frontend sending history.

### `POST /api/chat/query/`

**Request:**
```json
{
  "prompt": "How does auth work?",
  "repo": "my-repo",
  "branch": "main",
  "chat_id": "uuid-of-chat-session",
  "attached_files": [
    { "filename": "notes.py", "content": "print('hello')" }
  ],
  "stream": true
}
```

**Changes from previous version:**
- `history` field is **optional** (kept for backward compatibility but ignored)
- No need to send previous messages — the server loads them from `ChatMessage` records for the given `chat_id`
- `_save_on_complete` streaming wrapper is no longer needed — LangChain persists messages automatically via `DjangoChatMessageHistory`

**Response (non-streaming, `stream: false`):**
```json
{
  "status": 200,
  "data": {
    "answer": "The auth system uses JWT tokens..."
  },
  "message": "Query processed successfully."
}
```

**Response (streaming, `stream: true`):**
- Returns `text/plain` SSE-like stream of chunks
- Messages are persisted automatically after the stream completes

### `POST /api/chat/session/new`

Unchanged. Creates a new `ChatSession` and returns the `id` to use as `chat_id`.

### `GET /api/chat/history/`

Unchanged. Lists all chat sessions for the user.

### `GET /api/chat/session/<uuid:pk>/`

Unchanged. Returns session details + all messages.

### `PATCH /api/chat/session/<uuid:pk>/`

Unchanged. Update title, archive/delete.

---

## 4. GitHub Repos & Branches

### `GET /api/github/repos/`

Unchanged. Lists repos. Returns `repo_id` (GitHub integer ID) needed for scan-report.

### `GET /api/github/repos/search/?query=<term>`

Unchanged. Search repos by name.

### `GET /api/github/repos/<repo>/branches/`

Unchanged. Lists branches from GitHub API directly.

---

## 5. Webhook (UNCHANGED)

`POST /api/github/webhook/` — now also stores `commit_url` when syncing branches.

---

## Summary of Changes from Previous Version

| Change | Impact on Frontend |
|---|---|
| New endpoint `GET /api/github/repos/<repo_id>/scan-report/` | New feature — add button/link to show scan report per repo |
| `POST /embed/repo/index/` now tracks scan attempts via `BranchScan` | No frontend change needed — same request/response |
| `POST /api/chat/query/` no longer requires `history` field | **Simplify frontend** — remove history management logic |
| `POST /api/chat/query/` `chat_id` is now the `thread_id` for LangChain memory | Pass the same `chat_id` for follow-up questions in the same session |
| Commit URL now stored in `RepoBranch` and `BranchScan` | Use `previous_scans[].commit_url` in scan report to link to GitHub commits |
| `ScanError` table tracks all scan failures | No frontend changes needed — backend/internal use |
