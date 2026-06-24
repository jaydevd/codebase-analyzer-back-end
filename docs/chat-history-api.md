# Chat History API — Frontend Integration Guide

Base URL: `/api/chat/`
Auth: `Authorization: Bearer <access_token>` (JWT)

---

## Endpoints

### 1. Create Chat Session

Starts a new chat. Called when the user opens a new chat or starts fresh.

```
POST session/new
```

**Request:**
```json
{
  "title": "Optional title (default: 'Untitled Chat')",
  "repository": "repo-name or null",
  "branch": "main or null"
}
```

**Response (201):**
```json
{
  "status": 201,
  "data": {
    "id": "uuid",
    "title": "Untitled Chat",
    "repository": "repo-name",
    "branch": "main",
    "created_at": 1747000000,
    "updated_at": 1747000000,
    "is_deleted": false,
    "is_archived": false
  },
  "message": "Chat session created",
  "errors": null
}
```

**When to call:** On "New Chat" / "New Session" button click. Save the returned `id` — it's the `session_id` you'll use when saving queries.

---

### 2. List Chat History

Fetches all non-deleted sessions for the logged-in user.

```
GET history/
```

**Response (200):**
```json
{
  "status": 200,
  "data": [
    {
      "id": "uuid",
      "title": "Untitled Chat",
      "repository": "repo-name",
      "branch": "main",
      "created_at": 1747000000,
      "updated_at": 1747000000,
      "is_deleted": false,
      "is_archived": false
    }
  ],
  "message": "Chat history fetched successfully"
}
```

**When to call:**
- On the history/sidebar page load to populate the session list.
- After creating a new session, to refresh the list.

---

### 3. Get Chat Detail (Session + Messages)

Fetches a single session with all its messages.

```
GET session/<uuid:pk>/
```

**Response (200):**
```json
{
  "status": 200,
  "data": {
    "id": "uuid",
    "title": "Untitled Chat",
    "repository": "repo-name",
    "branch": "main",
    "created_at": 1747000000,
    "updated_at": 1747000000,
    "is_deleted": false,
    "is_archived": false,
    "messages": [
      {
        "id": "uuid",
        "chat_id": "uuid",
        "prompt": "What does this function do?",
        "content": "The function...",
        "created_at": 1747000000,
        "updated_at": 1747000000
      }
    ]
  },
  "message": "Chat session fetched successfully"
}
```

**When to call:** When the user clicks on a session in the history list to open/revisit that conversation.

---

### 4. Update Chat Session

Rename title, archive, or soft-delete a session.

```
PATCH session/<uuid:pk>/
```

**Request** (partial — send only fields to update):
```json
{
  "title": "New Title",
  "is_archived": true,
  "is_deleted": true
}
```

**Response (200):**
```json
{
  "status": 200,
  "data": {
    "id": "uuid",
    "title": "New Title",
    "is_deleted": true,
    "is_archived": true,
    ...
  },
  "message": "Chat session updated successfully"
}
```

**When to call:**
- **Rename:** After user edits the session title inline.
- **Archive:** When user clicks archive (hides from main list but not deleted).
- **Delete:** When user clicks delete (soft-delete — recoverable by admin; filtered out from history).

---

### 5. Send Query (auto-saves to ChatMessage)

Sends a prompt to the LLM. Prompt and response are automatically persisted to `ChatMessage` under the given `chat_id`.

```
POST query/
```

**Request:**
```json
{
  "chat_id": "uuid (required)",
  "prompt": "What does this function do?",
  "repo": "repo-name",
  "branch": "main",
  "stream": true,
  "attached_files": [],
  "history": []
}
```

**Response (non-streaming, 200):**
```json
{
  "status": 200,
  "data": {
    "answer": "The function..."
  },
  "message": "Query processed successfully."
}
```

**Response (streaming):** `text/plain` chunked stream of tokens.

**Behavior:**
- `ChatMessage(prompt=..., content="")` is created **before** the LLM call.
- On **non-streaming**: `content` is set to the full LLM response after completion.
- On **streaming**: `content` is accumulated and persisted when the stream ends (via `_save_on_complete` wrapper).
- If the LLM call fails, the message remains with `content=""` — the prompt is never lost.

**When to call:** Every user message in a chat — pass the same `chat_id` obtained from session creation.

---

## Typical User Flow

```
1. User clicks "New Chat"
   → POST /api/chat/session/new  →  get chat_id (field "id")

2. Page loads (or user clicks a session in sidebar)
   → GET /api/chat/history/  →  populate sidebar
   → GET /api/chat/session/<chat_id>/  →  load messages

3. User sends a message
   → POST /api/chat/query/  with the same chat_id
     → prompt + response auto-saved as ChatMessage

4. User sends follow-up
   → POST /api/chat/query/  with same chat_id again
     → message is appended to the session

5. User renames / archives / deletes
   → PATCH /api/chat/session/<chat_id>/
```

---

## Notes

- All timestamps are Unix epoch integers (seconds).
- `is_deleted=true` sessions are excluded from `GET history/` by default (soft delete).
- `is_archived=true` sessions still appear in history — archive is a client-side hint.
- The `user_id` is set automatically from the JWT token; never send it in the request body.
- `repository` and `branch` are optional on session creation — they can be set later or left null for free-form chats.
- **`chat_id` is required** in the query endpoint. Frontend must always pass it to ensure messages are stored under the correct session.
