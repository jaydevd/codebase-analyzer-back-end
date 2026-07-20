# Admin Panel — Backend API Specification

This document specifies every API endpoint the admin panel front-end consumes. The front-end is built and expects these exact request/response shapes. The backend can be written from scratch against this spec.

---

## Base URL

All endpoints are prefixed with the configured API base URL (e.g. `https://api.example.com`).

All admin endpoints are nested under `/admin/`.

Authentication: **Bearer JWT token** in `Authorization` header. Only users with `role = "admin"` may access these endpoints.

---

## Data Models

### AdminUser

```json
{
  "id": "uuid",
  "email": "user@example.com",
  "first_name": "John",
  "last_name": "Doe",
  "github_username": "johndoe",
  "role": "user",
  "is_active": true,
  "is_suspended": false,
  "is_github_installation_active": true,
  "repo_count": 5,
  "chat_count": 12,
  "last_login": "2026-06-30T14:30:00Z",
  "created_at": "2026-01-15T10:00:00Z"
}
```

### ScanJob

```json
{
  "id": "uuid",
  "repository_id": "uuid",
  "repository_name": "my-repo",
  "repository_full_name": "owner/my-repo",
  "user_id": "uuid",
  "user_email": "user@example.com",
  "branch": "main",
  "commit_sha": "abc123def456",
  "status": "completed",
  "progress": 100,
  "error_message": null,
  "error_log": null,
  "started_at": "2026-06-30T12:00:00Z",
  "completed_at": "2026-06-30T12:05:00Z",
  "duration_seconds": 300,
  "created_at": "2026-06-30T11:59:00Z"
}
```

**Status enum:** `pending | running | completed | failed`

### AdminRepo

```json
{
  "id": "uuid",
  "name": "my-repo",
  "full_name": "owner/my-repo",
  "owner_id": "uuid",
  "owner_email": "user@example.com",
  "private": false,
  "language": "TypeScript",
  "status": "scanned",
  "branch_count": 3,
  "file_count": 120,
  "chunk_count": 450,
  "last_scanned": "2026-06-30T12:05:00Z",
  "created_at": "2026-06-01T10:00:00Z"
}
```

**Status enum:** `not_scanned | scanning | scanned | failed`

### ErrorLog

```json
{
  "id": "uuid",
  "level": "error",
  "source": "codebase-analyzer.worker",
  "message": "Failed to clone repository",
  "repository_name": "owner/my-repo",
  "user_email": "user@example.com",
  "stack_trace": "Traceback (most recent call last):\n  File ...",
  "created_at": "2026-06-30T12:00:00Z"
}
```

**Level enum:** `error | warning | info`

### PaginatedResponse

Every list endpoint returns this wrapper:

```json
{
  "count": 150,
  "next": "https://api.example.com/admin/users/?page=3",
  "previous": "https://api.example.com/admin/users/?page=1",
  "results": [ ... ]
}
```

| Field | Type | Description |
|---|---|---|
| `count` | integer | Total number of results across all pages |
| `next` | string or null | URL for the next page, or null if on last page |
| `previous` | string or null | URL for the previous page, or null if on first page |
| `results` | array | Array of items for the current page |

---

## Endpoints

### 1. Dashboard Stats

#### `GET /admin/stats/`

Returns aggregate metrics for the dashboard overview cards.

**Response 200:**

```json
{
  "total_users": 240,
  "active_users": 180,
  "total_repos": 85,
  "scanned_repos": 60,
  "total_chats": 1200,
  "scans_today": 15,
  "failed_scans": 8,
  "avg_scan_duration_seconds": 245
}
```

| Field | Type | Description |
|---|---|---|
| `total_users` | integer | Total registered users |
| `active_users` | integer | Users who have logged in within the last 30 days |
| `total_repos` | integer | Total repositories across all users |
| `scanned_repos` | integer | Repos with at least one completed scan |
| `total_chats` | integer | Total chat sessions across all users |
| `scans_today` | integer | Scans started today |
| `failed_scans` | integer | Total scans with status "failed" |
| `avg_scan_duration_seconds` | integer or null | Average duration of completed scans in seconds |

#### `GET /admin/stats/scans-over-time/`

Returns daily scan counts for the line chart and bar chart.

**Response 200:**

```json
[
  {
    "date": "2026-06-24",
    "completed": 12,
    "failed": 2,
    "total": 14
  },
  {
    "date": "2026-06-25",
    "completed": 8,
    "failed": 1,
    "total": 9
  }
]
```

Return last 30 days by default. Front-end uses the last 7 entries for the bar chart.

---

### 2. User Management

#### `GET /admin/users/`

Returns a paginated list of all users.

**Query params:**

| Param | Type | Description |
|---|---|---|
| `page` | integer | Page number (default: 1) |
| `search` | string | Search by name or email |
| `role` | string | Filter by role (`admin` or `user`) |
| `is_active` | boolean | Filter by active status |
| `is_suspended` | boolean | Filter by suspended status |

**Response 200:** `PaginatedResponse<AdminUser>` — see data model above.

#### `GET /admin/users/{id}/`

Returns a single user by ID.

**Response 200:** `AdminUser` object — see data model above.

#### `PATCH /admin/users/{id}/`

Update user fields. All fields optional.

**Request body:**

```json
{
  "first_name": "Jane",
  "last_name": "Smith",
  "email": "jane@example.com",
  "role": "admin"
}
```

**Response 200:** Updated `AdminUser` object.

#### `DELETE /admin/users/{id}/`

Permanently delete a user and all associated data.

**Response 204:** No content.

#### `POST /admin/users/{id}/suspend/`

Suspend a user account. Suspended users cannot log in.

**Response 200:**

```json
{
  "detail": "User suspended"
}
```

#### `POST /admin/users/{id}/activate/`

Re-activate a suspended user.

**Response 200:**

```json
{
  "detail": "User activated"
}
```

---

### 3. Scan Management

#### `GET /admin/scans/`

Returns a paginated list of all scan jobs.

**Query params:**

| Param | Type | Description |
|---|---|---|
| `page` | integer | Page number |
| `status` | string | Filter by status: `pending`, `running`, `completed`, `failed` |
| `search` | string | Search by repository name or user email |

**Response 200:** `PaginatedResponse<ScanJob>` — see data model above.

#### `GET /admin/scans/{id}/`

Returns a single scan job by ID.

**Response 200:** `ScanJob` object — see data model above.

#### `POST /admin/scans/{id}/retry/`

Trigger a retry of a failed scan. Creates a new scan job for the same repository + branch.

**Response 200:**

```json
{
  "detail": "Scan retry triggered"
}
```

---

### 4. Repository Management

#### `GET /admin/repos/`

Returns a paginated list of all repositories.

**Query params:**

| Param | Type | Description |
|---|---|---|
| `page` | integer | Page number |
| `search` | string | Search by repo name or owner email |
| `status` | string | Filter by status: `not_scanned`, `scanning`, `scanned`, `failed` |
| `owner_id` | string (uuid) | Filter by owner user ID |

**Response 200:** `PaginatedResponse<AdminRepo>` — see data model above.

#### `DELETE /admin/repos/{id}/`

Delete a repository and all associated data (scans, chunks, chat messages).

**Response 204:** No content.

#### `POST /admin/repos/{id}/rescan/`

Trigger a new scan for this repository (default branch).

**Response 200:**

```json
{
  "detail": "Re-scan triggered"
}
```

---

### 5. Error Logs

#### `GET /admin/logs/`

Returns a paginated list of system error logs.

**Query params:**

| Param | Type | Description |
|---|---|---|
| `page` | integer | Page number |
| `level` | string | Filter by level: `error`, `warning`, `info` |
| `source` | string | Filter by source name |
| `search` | string | Search by message, repo name, or user email |

**Response 200:** `PaginatedResponse<ErrorLog>` — see data model above.

---

## Implementation Notes

### Pagination

All list endpoints use page-number-based pagination. Use Django REST Framework's `PageNumberPagination` or equivalent. Default page size should be 25 (front-end does not override `?page_size=` — it reads `next`/`previous` URLs for navigation).

### Error Response Format

All errors should follow DRF convention:

**Validation error:**
```json
{
  "field_name": ["Error message 1", "Error message 2"]
}
```

**Non-field error:**
```json
{
  "non_field_errors": ["General error message"]
}
```

### Admin Access Control

Check that the requesting user has `role = "admin"` on every admin endpoint. Return `403 Forbidden` if not.

### User Deletion Cascade

Deleting a user (`DELETE /admin/users/{id}/`) should cascade-delete:
- Their repositories
- Their scan jobs
- Their chat sessions and messages
- Their GitHub installation data (if any)

### Scan Retry vs Rescan

- `POST /admin/scans/{id}/retry/` — Creates a new scan job for the same repo + branch. Does not modify the original failed scan.
- `POST /admin/repos/{id}/rescan/` — Creates a new scan job for the repo's default branch. Used from the repositories page.

### Stats Accuracy

- `active_users` = users who have logged in within the last 30 days
- `scanned_repos` = repos with at least one scan job with `status = "completed"`
- `failed_scans` = total scan jobs with `status = "failed"` (not unique repos)
- `avg_scan_duration_seconds` = average of `duration_seconds` across all `completed` scans
