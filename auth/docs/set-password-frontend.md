# Set Password (OAuth Users) — Frontend Integration

## Overview

Users who signed up via Google or GitHub OAuth do not have a password. This endpoint lets them set one so they can also log in with email + password.

---

## Endpoint

```
POST /auth/set-password/
Authorization: Bearer <access_token>
Content-Type: application/json

{
    "new_password": "StrongPass123!"
}
```

## Determining when to show the UI

The user profile endpoint (`GET /auth/user/`) now returns `has_password`:

```json
{
    "data": {
        "id": "...",
        "email": "user@example.com",
        "google_id": "12345",
        "github_oauth_id": null,
        "has_password": false,
        ...
    }
}
```

Use this field to decide what to show:

| Condition | Show |
|---|---|
| `google_id` or `github_oauth_id` present **and** `has_password === false` | **"Set Password"** button/link |
| `google_id` or `github_oauth_id` present **and** `has_password === true` | **"Change Password"** (existing endpoint) |
| Neither ID present | **"Change Password"** (standard email/password user) |

---

## Response handling

| Status | Meaning | Action |
|---|---|---|
| **200** | Password set successfully | Show success toast/message. User can now log in with email + password. |
| **400** | Validation error | Show the error message. Two possible cases: |
| | `"This account was not created via Google or GitHub..."` | User is not an OAuth user — direct them to Change Password. |
| | `"This account already has a password set."` | User already has a password — direct them to Change Password. |
| | Password strength rules | Show inline validation as usual. |
| **401** | Token missing/expired | Redirect to login. |

### Response format

Success:
```json
{
    "status": 200,
    "data": null,
    "message": "Password set successfully."
}
```

Error:
```json
{
    "status": 400,
    "data": null,
    "message": "Validation error.",
    "errors": {
        "new_password": ["This account already has a password set."]
    }
}
```

---

## Flow (settings page example)

```
[Settings] → [Security] → "Set Password"

1. User sees "Set Password" button (only if OAuth user without password)
2. Clicks → modal/page with a single password field + confirm
3. POST /auth/set-password/ { "new_password": "..." }
4. On success → toast "Password set successfully"
5. Optionally offer to log out so they can verify login with email+password
```

## Testing

| Test case | Expected behavior |
|---|---|
| Google-only user sets password | 200, can later log in with email + password |
| GitHub-only user sets password | 200 |
| Email/password user hits endpoint | 400 "not created via Google or GitHub" |
| OAuth user who already set password hits endpoint | 400 "already has a password" |
| Unauthenticated request | 401 |
| Weak password | 400 with password validation errors |
