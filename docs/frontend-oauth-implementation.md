# Frontend OAuth Implementation Guide

## Overview

Users can sign in using three methods: **Email/password**, **Google**, or **GitHub**. All methods authenticate against the same user account (linked by email). After login, the backend returns a JWT pair (`access` + `refresh`) identical to the email login flow.

---

## 1. Email/Password Login (existing)

```
POST /auth/login/
Body:  { "email": "...", "password": "..." }
Response: { "access": "...", "refresh": "...", "user": { ... } }
```

---

## 2. Google Login

### Flow

```
[User clicks "Sign in with Google"]
    │
    ▼
[Frontend requests authorize URL]
    │  GET /auth/google/authorize/
    │  Response: { "url": "https://accounts.google.com/o/oauth2/v2/auth?..." }
    ▼
[Frontend redirects user to Google consent screen]
    │  User approves
    ▼
[Google redirects to backend callback]
    │  GET /auth/google/callback/?code=xxx&state=yyy
    ▼
[Backend exchanges code for tokens, verifies ID token,
 creates/links user, issues JWT]
    │  302 Redirect → {FRONTEND_URL}/auth/callback?access=xxx&refresh=xxx
    ▼
[Frontend receives tokens from URL,
 stores them, navigates to app]
```

### Frontend Implementation

#### a) Fetch the authorize URL and redirect

```javascript
async function signInWithGoogle() {
  const res = await fetch('/auth/google/authorize/');
  const data = await res.json();

  if (!data.success) {
    // handle error
    return;
  }

  // Redirect browser to Google
  window.location.href = data.data.url;
}
```

#### b) Handle the callback page (`/auth/callback`)

Same as GitHub — create a route at `/auth/callback` that reads the URL parameters:

```javascript
// On the /auth/callback page
const params = new URLSearchParams(window.location.search);

if (params.has('error')) {
  // show error message
  console.error('OAuth error:', params.get('error'));
} else {
  const accessToken = params.get('access');
  const refreshToken = params.get('refresh');

  if (accessToken && refreshToken) {
    localStorage.setItem('access_token', accessToken);
    localStorage.setItem('refresh_token', refreshToken);
    // redirect to main app
    window.location.href = '/dashboard';
  }
}
```

### API Reference

**`GET /auth/google/authorize/`**

Returns the Google OAuth URL to redirect the user to.

**Response (200):**
```json
{
  "success": true,
  "message": "Google authorization URL generated.",
  "data": {
    "url": "https://accounts.google.com/o/oauth2/v2/auth?client_id=..."
  }
}
```

**`GET /auth/google/callback/?code=xxx&state=yyy`**

This is a public redirect endpoint. On success, the browser redirects to:
```
{FRONTEND_URL}/auth/callback?access=xxx&refresh=xxx
```

On error:
```
{FRONTEND_URL}/auth/callback?error=<error_code>
```

---

## 3. GitHub Login

### Flow

```
[User clicks "Sign in with GitHub"]
    │
    ▼
[Frontend requests authorize URL]
    │  GET /auth/github/authorize/
    │  Response: { "url": "https://github.com/login/oauth/authorize?..." }
    ▼
[Frontend opens URL in a popup/new tab]
    │  User approves on GitHub
    ▼
[GitHub redirects to backend callback]
    │  GET /auth/github/callback/?code=xxx&state=yyy
    ▼
[Backend exchanges code, creates/links user, issues JWT]
    │  302 Redirect → {FRONTEND_URL}/auth/callback?access=xxx&refresh=xxx
    ▼
[Frontend popup receives the redirect with tokens in URL]
    │
    ▼
[Frontend reads tokens from URL, stores them, closes popup,
 notifies main window, navigates to app]
```

### Frontend Implementation

#### a) Fetch the authorize URL

```javascript
async function signInWithGitHub() {
  const res = await fetch('/auth/github/authorize/');
  const data = await res.json();

  if (!data.success) {
    // handle error
    return;
  }

  // Open popup
  const popup = window.open(
    data.data.url,
    'github-oauth',
    'width=600,height=700'
  );

  // Listen for the callback message
  window.addEventListener('message', (event) => {
    if (event.origin !== window.location.origin) return;
    if (event.data.type === 'github-oauth-callback') {
      if (event.data.access) {
        localStorage.setItem('access_token', event.data.access);
        localStorage.setItem('refresh_token', event.data.refresh);
        // redirect to app or close popup
      } else {
        // show error from event.data.error
      }
    }
  });
}
```

#### b) Handle the callback page (`/auth/callback`)

Create a route at `/auth/callback` that handles the redirect from GitHub. This page reads the URL parameters and sends them to the main window.

```javascript
// On the /auth/callback page (runs in the popup/redirect window)

const params = new URLSearchParams(window.location.search);

if (params.has('error')) {
  // Send error to opener
  window.opener.postMessage(
    { type: 'github-oauth-callback', error: params.get('error') },
    window.location.origin
  );
  window.close();
} else {
  // Send tokens to opener
  window.opener.postMessage(
    {
      type: 'github-oauth-callback',
      access: params.get('access'),
      refresh: params.get('refresh'),
    },
    window.location.origin
  );
  window.close();
}
```

### API Reference

**`GET /auth/github/authorize/`**

Returns the GitHub OAuth URL to redirect the user to.

**Response (200):**
```json
{
  "success": true,
  "message": "GitHub authorization URL generated.",
  "data": {
    "url": "https://github.com/login/oauth/authorize?client_id=..."
  }
}
```

**`GET /auth/github/callback/?code=xxx&state=yyy`**

This is a public redirect endpoint. On success, the browser redirects to:
```
{FRONTEND_URL}/auth/callback?access=xxx&refresh=xxx
```

On error:
```
{FRONTEND_URL}/auth/callback?error=<error_code>
```

---

## 4. Token Management

All login methods return the same token format. Use the standard pattern:

```javascript
// Store tokens after login
localStorage.setItem('access_token', data.data.access);
localStorage.setItem('refresh_token', data.data.refresh);

// Attach to API requests
fetch('/api/endpoint', {
  headers: {
    'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
  },
});

// Refresh when expired
async function refreshToken() {
  const res = await fetch('/auth/token/refresh/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh: localStorage.getItem('refresh_token') }),
  });
  const data = await res.json();
  if (data.success) {
    localStorage.setItem('access_token', data.data.access);
  }
}
```

---

## 5. User Profile

After login, the user profile includes OAuth-related fields:

```json
{
  "id": "uuid",
  "email": "user@example.com",
  "first_name": "John",
  "last_name": "Doe",
  "avatar_url": "https://avatars.githubusercontent.com/...",
  "google_id": "12345...",
  "github_oauth_id": 12345,
  "github_username": "johndoe",
  "is_github_installation_active": false
}
```

---

## 6. GitHub Repo Access

After logging in with GitHub, the user's repos are immediately accessible via the existing endpoints. The backend uses the OAuth token stored during login.

| Endpoint | Method | Description |
|---|---|---|
| `/api/github/repos/` | GET | List user's GitHub repos |
| `/api/github/repos/<repo>/branches/` | GET | List branches for a repo |
| `/api/github/repo/download/` | POST | Download a repo as zipball |

No additional GitHub installation is required for personal repos. The existing GitHub App installation flow (`/api/github/install-url/`) remains available for org repos.

---

## 7. Determining Login Method

To show the correct login UI on the frontend:

- If `google_id` is present → user has Google linked
- If `github_oauth_id` is present → user has GitHub linked
- If user has `password` (check via a `has_password` endpoint or infer) → email login works

---

## 8. Environment Variables (Frontend)

| Variable | Description |
|---|---|
| `VITE_GOOGLE_CLIENT_ID` | Google OAuth Client ID from Google Cloud Console |
| `VITE_API_BASE_URL` | Backend base URL (e.g., `http://localhost:8000`) |

---

## 9. Error Codes

| Error Code | Meaning |
|---|---|
| `invalid_state` | CSRF state mismatch — restart the OAuth flow |
| `no_code` | No authorization code received from GitHub |
| `token_exchange_failed` | Failed to exchange GitHub code for access token |
| `no_email` | Could not retrieve email from GitHub (email must be public/verified) |
