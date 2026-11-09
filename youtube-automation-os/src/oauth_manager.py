"""Google OAuth 2.0 for installed (desktop) applications.

* Client config comes from ``GOOGLE_CLIENT_ID`` + ``GOOGLE_CLIENT_SECRET`` (+ optional
  ``GOOGLE_REDIRECT_URI``) or from ``GOOGLE_CLIENT_SECRETS_FILE`` (the JSON downloaded
  from Google Cloud Console). Never from YAML, never hardcoded.
* The authorized-user token is stored at ``GOOGLE_TOKEN_PATH`` (default ``token.json``
  in the toolkit root) with file mode 0600, written atomically. It contains a refresh
  token: treat it like a password. It is gitignored.
* Nothing in this module prints or logs token values; ``status()`` reports only
  booleans, expiry and scope names.

The loopback flow (``run_local_server``) is Google's supported flow for desktop apps;
the old out-of-band (copy/paste code) flow was shut down by Google in 2022/2023.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .config import load_scopes, project_root, resolve_path
from .exceptions import AuthError, ConfigError, ScopeError
from .logger import get_logger

AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"
DEFAULT_REDIRECT = "http://localhost:8080/"


def token_path() -> Path:
    return resolve_path(os.getenv("GOOGLE_TOKEN_PATH") or "token.json")


def client_config() -> dict:
    """Build the installed-app client config from the environment. Raises ConfigError if absent."""
    secrets_file = os.getenv("GOOGLE_CLIENT_SECRETS_FILE")
    if secrets_file:
        p = resolve_path(secrets_file)
        if not p.exists():
            raise ConfigError(f"GOOGLE_CLIENT_SECRETS_FILE points to a missing file: {p}")
        data = json.loads(p.read_text(encoding="utf-8"))
        if "installed" not in data:
            raise ConfigError(
                "The client secrets file is not a 'Desktop app' OAuth client (no 'installed' key). "
                "Create an OAuth client of type 'Desktop app' in Google Cloud Console."
            )
        return data
    client_id = (os.getenv("GOOGLE_CLIENT_ID") or "").strip()
    client_secret = (os.getenv("GOOGLE_CLIENT_SECRET") or "").strip()
    missing = [n for n, v in (("GOOGLE_CLIENT_ID", client_id), ("GOOGLE_CLIENT_SECRET", client_secret)) if not v]
    if missing:
        raise ConfigError(
            "Missing OAuth client configuration: " + ", ".join(missing)
            + ". Set them in .env (see .env.example) or set GOOGLE_CLIENT_SECRETS_FILE."
        )
    redirect = os.getenv("GOOGLE_REDIRECT_URI") or DEFAULT_REDIRECT
    return {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": AUTH_URI,
            "token_uri": TOKEN_URI,
            "redirect_uris": [redirect],
        }
    }


def redirect_host_port() -> tuple[str, int]:
    uri = urlparse(os.getenv("GOOGLE_REDIRECT_URI") or DEFAULT_REDIRECT)
    if uri.scheme != "http" or uri.hostname not in {"localhost", "127.0.0.1"}:
        raise ConfigError("GOOGLE_REDIRECT_URI must be a loopback URL such as http://localhost:8080/ for a desktop OAuth client")
    return uri.hostname, uri.port or 8080


# ------------------------------------------------------------------ scopes ------
def scope_profiles(cfg: dict | None = None) -> dict[str, list[str]]:
    cfg = cfg or load_scopes()
    return {k: list(v) for k, v in cfg.get("profiles", {}).items()}


def resolve_scopes(names: list[str] | str, cfg: dict | None = None) -> list[str]:
    """Turn profile names (``upload,analytics``) and/or full scope URLs into a sorted scope list."""
    if isinstance(names, str):
        names = [n.strip() for n in names.split(",") if n.strip()]
    profiles = scope_profiles(cfg)
    out: set[str] = set()
    for n in names:
        if n.startswith("https://"):
            out.add(n)
        elif n in profiles:
            out.update(profiles[n])
        else:
            raise ConfigError(f"Unknown scope profile '{n}'. Known: {', '.join(sorted(profiles))}")
    return sorted(out)


def missing_scopes_for(operations: list[str], granted: list[str] | set[str], cfg: dict | None = None) -> list[str]:
    """For each operation, at least one of its accepted scopes must be granted.

    Returns a list of human-readable requirements that are not met.
    """
    cfg = cfg or load_scopes()
    accepted = cfg.get("operations", {})
    granted = set(granted or [])
    missing = []
    for op in operations:
        options = accepted.get(op)
        if not options:
            continue
        if not granted.intersection(options):
            missing.append(f"{op} (needs one of: {', '.join(options)})")
    return missing


# --------------------------------------------------------------- token I/O ------
def _write_token(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".token.", suffix=".tmp")
    try:
        os.chmod(tmp, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
        os.replace(tmp, path)
        os.chmod(path, 0o600)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def save_credentials(creds: Any, path: Path | None = None) -> Path:
    path = path or token_path()
    _write_token(path, creds.to_json())
    return path


def _read_token_info(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise AuthError(f"Token file {path} is not valid JSON; delete it and re-run authenticate.py") from exc


def load_credentials(
    operations: list[str] | None = None,
    *,
    path: Path | None = None,
    refresh: bool = True,
    request_factory: Callable[[], Any] | None = None,
    scopes_cfg: dict | None = None,
):
    """Load stored credentials, check scopes for ``operations``, refresh if expired.

    Raises AuthError/ScopeError with a next-step message; never includes token values.
    """
    from google.oauth2.credentials import Credentials

    path = path or token_path()
    if not path.exists():
        raise AuthError(
            f"No OAuth token at {path}. Run: python skills/youtube-auth/scripts/authenticate.py --scopes upload,manage"
        )
    info = _read_token_info(path)
    if not info.get("refresh_token"):
        raise AuthError("Stored token has no refresh token; re-run authenticate.py (it requests offline access).")
    creds = Credentials.from_authorized_user_info(info)
    granted = set(creds.scopes or info.get("scopes") or [])
    if operations:
        missing = missing_scopes_for(operations, granted, scopes_cfg)
        if missing:
            raise ScopeError(missing)
    if refresh and (not creds.valid):
        refresh_credentials(creds, path=path, request_factory=request_factory)
    return creds


def refresh_credentials(creds: Any, *, path: Path | None = None, request_factory: Callable[[], Any] | None = None) -> Any:
    from google.auth.exceptions import RefreshError

    if not creds.refresh_token:
        raise AuthError("Cannot refresh: no refresh token. Re-run authenticate.py.")
    if request_factory is None:
        from google.auth.transport.requests import Request

        request_factory = Request
    log = get_logger()
    try:
        creds.refresh(request_factory())
    except RefreshError as exc:
        # str(exc) from google-auth contains the error code (e.g. invalid_grant), not token values.
        log.error("auth.refresh", "refresh failed", error_class="auth", result="failed", reason=type(exc).__name__)
        raise AuthError(
            "Token refresh failed (the refresh token was revoked or expired). Re-run authenticate.py. "
            "Note: OAuth apps left in 'Testing' publishing status get refresh tokens that expire after 7 days. "
            f"Google said: {str(exc)[:200]}"
        ) from exc
    save_credentials(creds, path)
    log.info("auth.refresh", "access token refreshed", result="success", expiry=_iso(creds.expiry))
    return creds


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:  # google-auth stores naive UTC
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat(timespec="seconds")


def status(path: Path | None = None, scopes_cfg: dict | None = None) -> dict:
    """Local, offline status. Contains no secret values."""
    path = path or token_path()
    out: dict[str, Any] = {
        "token_path": str(path),
        "token_file_exists": path.exists(),
        "client_config_present": _client_config_present(),
    }
    if not path.exists():
        out["state"] = "NOT_AUTHENTICATED"
        return out
    info = _read_token_info(path)
    mode = oct(path.stat().st_mode & 0o777)
    out["token_file_mode"] = mode
    out["token_file_private"] = mode == "0o600"
    out["has_refresh_token"] = bool(info.get("refresh_token"))
    out["has_access_token"] = bool(info.get("token"))
    expiry = info.get("expiry")
    out["access_token_expiry"] = expiry
    expired = None
    if expiry:
        try:
            exp = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            expired = exp <= datetime.now(timezone.utc)
        except ValueError:
            expired = None
    out["access_token_expired"] = expired
    granted = sorted(info.get("scopes") or [])
    out["granted_scopes"] = granted
    cfg = scopes_cfg or load_scopes()
    profiles = scope_profiles(cfg)
    out["profiles_satisfied"] = sorted(n for n, sc in profiles.items() if set(sc) <= set(granted))
    if not out["has_refresh_token"]:
        out["state"] = "INVALID_NO_REFRESH_TOKEN"
    elif expired is False:
        out["state"] = "AUTHENTICATED"
    else:
        out["state"] = "AUTHENTICATED_NEEDS_REFRESH"
    return out


def _client_config_present() -> bool:
    try:
        client_config()
        return True
    except ConfigError:
        return False


def authenticate(
    scopes: list[str],
    *,
    open_browser: bool = True,
    path: Path | None = None,
    flow_factory: Callable[..., Any] | None = None,
) -> dict:
    """Run the installed-app loopback flow and save the token. Returns ``status()``."""
    if flow_factory is None:
        from google_auth_oauthlib.flow import InstalledAppFlow

        flow_factory = InstalledAppFlow.from_client_config
    host, port = redirect_host_port()
    flow = flow_factory(client_config(), scopes=scopes)
    creds = flow.run_local_server(
        host=host,
        port=port,
        open_browser=open_browser,
        access_type="offline",
        prompt="consent",
        authorization_prompt_message="Open this URL in a browser on THIS device to authorize YouTube access:\n{url}\n",
        success_message="YouTube Automation OS is authorized. You can close this tab.",
    )
    saved = save_credentials(creds, path)
    get_logger().info("auth.authenticate", "token saved", result="success", token_path=str(saved), scopes=scopes)
    return status(saved)


def project_token_hint() -> str:
    return str(project_root() / "token.json")
