---
name: youtube-auth
description: Authorize, check, or refresh Google OAuth access to a YouTube channel for YouTube Automation OS. Use when the user says "authenticate my YouTube account", "connect my channel", when another YouTube skill fails with an auth or scope error (exit code 4), or before the first upload.
---

# youtube-auth

## 1. Skill name
`youtube-auth`, part of YouTube Automation OS (`youtube-automation-os/`).

## 2. Description
Google OAuth 2.0 for an installed (desktop) application: get consent once, store a refresh token safely, refresh access tokens, and check which scopes are granted.

## 3. Purpose
Every other YouTube skill needs a valid token with the right scopes. This skill is the only place tokens are created. The token file is written with mode 0600 and is never printed.

## 4. When to use
- First-time setup, or "Authenticate my YouTube account".
- A script exits with code 4 (`AuthError` / `ScopeError`).
- You need captions or analytics and the token only has upload scopes.
- Before a long pipeline run: `validate_auth.py --require upload,manage`.

## 5. Required inputs
- `GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET` in `.env` (OAuth client of type **Desktop app**), or `GOOGLE_CLIENT_SECRETS_FILE`.
- A browser on the **same device** for the one-time consent screen.

## 6. Optional inputs
- `GOOGLE_REDIRECT_URI` (default `http://127.0.0.1:8091/`; must be a loopback URL. Not 8080: the phone website uses it).
- `GOOGLE_TOKEN_PATH` (default `token.json` in the toolkit root).
- `--scopes` profiles from `config/scopes.yaml`: `upload`, `manage`, `captions`, `readonly`, `analytics`.

## 7. Expected outputs
A status object with no secret values: `state` (`AUTHENTICATED`, `AUTHENTICATED_NEEDS_REFRESH`, `NOT_AUTHENTICATED`, `INVALID_NO_REFRESH_TOKEN`), `granted_scopes`, `profiles_satisfied`, `access_token_expiry`, `token_file_private`.

## 8. Dependencies
`google-auth`, `google-auth-oauthlib`, `python-dotenv` (in `requirements.txt`).

## 9. Exact execution commands
Run from `youtube-automation-os/` with the venv active:
```bash
python skills/youtube-auth/scripts/authenticate.py --scopes upload,manage
python skills/youtube-auth/scripts/authenticate.py --scopes upload,manage,captions,analytics --no-browser
python skills/youtube-auth/scripts/validate_auth.py --require upload,manage
python skills/youtube-auth/scripts/validate_auth.py --live          # 1 quota unit: channels.list(mine=true)
python skills/youtube-auth/scripts/refresh_token.py
```

## 10. CLI arguments
| Script | Arguments |
|---|---|
| `authenticate.py` | `--scopes LIST` (default `upload,manage`), `--no-browser`, `--force`, `--list-profiles`, `--json` |
| `validate_auth.py` | `--require LIST`, `--live`, `--json` (exit 0 ok, 4 problems) |
| `refresh_token.py` | `--json` |

## 11. Configuration
- Scope profiles and per-operation scope requirements: `config/scopes.yaml`.
- Recommended for the full pipeline: `upload,manage,captions`; add `analytics` for reports.

## 12. Error handling
| Problem | What you see | Fix |
|---|---|---|
| Client ID/secret missing | `ConfigError` naming the missing variables (exit 3) | Fill `.env` |
| Web-type client JSON | "not a 'Desktop app' OAuth client" | Create a Desktop app client |
| No token | `AuthError` with the authenticate command (exit 4) | Run `authenticate.py` |
| Missing scopes | `ScopeError` listing operations and accepted scopes (exit 4) | Re-run with more `--scopes` and `--force` |
| Refresh token revoked or expired | `AuthError` "Token refresh failed" | Re-run `authenticate.py --force` |

## 13. Failure recovery
Re-running `authenticate.py --force` is always safe: it replaces `token.json` atomically. Apps in the Google Cloud **Testing** publishing state get refresh tokens that expire after 7 days. Publish the consent screen (or re-authenticate weekly) to avoid this.

## 14. Security considerations
- The token file holds a refresh token, so treat it like a password. It is gitignored, mode 0600, and written atomically.
- No script prints `token`, `refresh_token` or `client_secret`. Logs are redacted (`src/logger.py`).
- Request the fewest scopes needed. `upload` alone cannot read or verify videos.
- Revoke access at https://myaccount.google.com/permissions.

## 15. Integration with other skills
`youtube-upload`, `youtube-thumbnail`, `youtube-transcript`, `youtube-analytics` and `youtube-pipeline` all call `src.oauth_manager.load_credentials(operations)`. It checks scopes per operation and refreshes automatically.

## 16. Working examples
```bash
$ python skills/youtube-auth/scripts/validate_auth.py
OK: False  state: NOT_AUTHENTICATED
token: /…/youtube-automation-os/token.json exists=False
PROBLEM: OAuth client config missing (GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET or GOOGLE_CLIENT_SECRETS_FILE)
PROBLEM: Auth state NOT_AUTHENTICATED: run skills/youtube-auth/scripts/authenticate.py
```
After consent, `validate_auth.py --live` adds `live check: {'ok': True, 'channel_id': 'UC…', 'channel_title': '…'}`.
