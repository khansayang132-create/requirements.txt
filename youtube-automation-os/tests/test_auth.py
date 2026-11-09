"""OAuth: client config from env, scope profiles, token storage (0600, no secrets printed),
refresh through google-auth with a fake transport, and environment configuration."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

import pytest
from conftest import ROOT, run_script
from google.oauth2.credentials import Credentials

from src import oauth_manager
from src.exceptions import AuthError, ConfigError, ScopeError

UPLOAD = "https://www.googleapis.com/auth/youtube.upload"
YT = "https://www.googleapis.com/auth/youtube"
FORCE_SSL = "https://www.googleapis.com/auth/youtube.force-ssl"
ANALYTICS = "https://www.googleapis.com/auth/yt-analytics.readonly"

FAKE_ACCESS = "ya29" + ".FAKE-access-token-for-tests-only"  # built at runtime: no secret-shaped literal in source
FAKE_REFRESH = "1/" + "/0FAKE-refresh-token-for-tests-only"
FAKE_SECRET = "GOCSPX" + "-FAKEsecretForTestsOnly"
NEW_ACCESS = "ya29" + ".NEW-access-token"


def write_token(path, *, scopes, expired=False, refresh=True):
    expiry = datetime.now(timezone.utc).replace(tzinfo=None) + (timedelta(hours=-1) if expired else timedelta(hours=1))
    info = {
        "token": FAKE_ACCESS,
        "refresh_token": FAKE_REFRESH if refresh else None,
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "test-client.apps.googleusercontent.com",
        "client_secret": FAKE_SECRET,
        "scopes": scopes,
        "expiry": expiry.isoformat() + "Z",
    }
    path.write_text(json.dumps(info))
    path.chmod(0o600)
    return info


class FakeTokenResponse:
    def __init__(self, status, payload):
        self.status = status
        self.headers = {"content-type": "application/json"}
        self.data = json.dumps(payload).encode()


class FakeTokenTransport:
    """google.auth.transport.Request stand-in that answers the token endpoint."""

    def __init__(self, status=200, payload=None):
        self.calls = []
        self.status = status
        self.payload = payload or {"access_token": NEW_ACCESS, "expires_in": 3600, "token_type": "Bearer"}

    def __call__(self, url, method="GET", body=None, headers=None, timeout=None, **kw):
        self.calls.append({"url": url, "method": method})
        return FakeTokenResponse(self.status, self.payload)


# ---------------------------------------------------------------- client config --
def test_client_config_from_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "abc.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", FAKE_SECRET)
    cfg = oauth_manager.client_config()
    assert cfg["installed"]["client_id"] == "abc.apps.googleusercontent.com"
    assert cfg["installed"]["token_uri"] == "https://oauth2.googleapis.com/token"
    assert cfg["installed"]["redirect_uris"] == ["http://localhost:8080/"]


def test_client_config_missing_names_the_variables():
    with pytest.raises(ConfigError) as exc:
        oauth_manager.client_config()
    assert "GOOGLE_CLIENT_ID" in str(exc.value) and "GOOGLE_CLIENT_SECRET" in str(exc.value)


def test_client_secrets_file_must_be_desktop_client(tmp_path, monkeypatch):
    f = tmp_path / "web_client.json"
    f.write_text(json.dumps({"web": {"client_id": "x"}}))
    monkeypatch.setenv("GOOGLE_CLIENT_SECRETS_FILE", str(f))
    with pytest.raises(ConfigError, match="Desktop app"):
        oauth_manager.client_config()


def test_redirect_must_be_loopback(monkeypatch):
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://127.0.0.1:9090/")
    assert oauth_manager.redirect_host_port() == ("127.0.0.1", 9090)
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "https://example.com/callback")
    with pytest.raises(ConfigError):
        oauth_manager.redirect_host_port()


# ----------------------------------------------------------------------- scopes --
def test_resolve_scope_profiles():
    assert oauth_manager.resolve_scopes("upload,manage") == sorted([UPLOAD, YT])
    assert FORCE_SSL in oauth_manager.resolve_scopes(["captions"])
    with pytest.raises(ConfigError, match="Unknown scope profile"):
        oauth_manager.resolve_scopes("everything")


def test_missing_scopes_for_operations():
    # upload-only tokens can insert but cannot verify (videos.list) or caption
    missing = oauth_manager.missing_scopes_for(["videos.insert", "videos.list", "captions.insert"], [UPLOAD])
    assert len(missing) == 2
    assert any(m.startswith("videos.list") for m in missing)
    assert oauth_manager.missing_scopes_for(["videos.insert", "videos.list"], [UPLOAD, YT]) == []


# ------------------------------------------------------------------- token I/O --
def test_load_without_token_explains_next_step():
    with pytest.raises(AuthError, match="authenticate.py"):
        oauth_manager.load_credentials(["videos.insert"])


def test_token_without_refresh_token_is_rejected(tmp_path):
    write_token(tmp_path / "token.json", scopes=[UPLOAD], refresh=False)
    with pytest.raises(AuthError, match="no refresh token"):
        oauth_manager.load_credentials(["videos.insert"])


def test_scope_check_rejects_insufficient_token(tmp_path):
    write_token(tmp_path / "token.json", scopes=[UPLOAD])
    with pytest.raises(ScopeError) as exc:
        oauth_manager.load_credentials(["videos.insert", "videos.update"])
    assert "videos.update" in str(exc.value)


def test_valid_token_loads_without_network(tmp_path):
    write_token(tmp_path / "token.json", scopes=[UPLOAD, YT])
    transport = FakeTokenTransport()
    creds = oauth_manager.load_credentials(["videos.insert", "videos.list"], request_factory=lambda: transport)
    assert creds.valid and transport.calls == []


def test_expired_token_is_refreshed_and_saved_privately(tmp_path):
    path = tmp_path / "token.json"
    write_token(path, scopes=[UPLOAD, YT], expired=True)
    transport = FakeTokenTransport()
    creds = oauth_manager.load_credentials(["videos.insert"], request_factory=lambda: transport)
    assert transport.calls and transport.calls[0]["url"] == "https://oauth2.googleapis.com/token"
    assert creds.token == NEW_ACCESS
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert json.loads(path.read_text())["token"] == NEW_ACCESS


def test_revoked_refresh_token_gives_auth_error_without_leaking(tmp_path, log_path):
    write_token(tmp_path / "token.json", scopes=[UPLOAD], expired=True)
    transport = FakeTokenTransport(status=400, payload={"error": "invalid_grant", "error_description": "Token has been expired or revoked."})
    with pytest.raises(AuthError) as exc:
        oauth_manager.load_credentials(["videos.insert"], request_factory=lambda: transport)
    text = str(exc.value)
    assert "Re-run authenticate.py" in text
    assert FAKE_REFRESH not in text and FAKE_SECRET not in text
    assert FAKE_REFRESH not in log_path.read_text()


def test_status_reports_state_but_never_secret_values(tmp_path):
    write_token(tmp_path / "token.json", scopes=[UPLOAD, YT])
    s = oauth_manager.status()
    assert s["state"] == "AUTHENTICATED"
    assert s["token_file_private"] is True
    assert "upload" in s["profiles_satisfied"] and "manage" in s["profiles_satisfied"]
    dumped = json.dumps(s)
    for secret in (FAKE_ACCESS, FAKE_REFRESH, FAKE_SECRET):
        assert secret not in dumped


def test_status_flags_world_readable_token(tmp_path):
    p = tmp_path / "token.json"
    write_token(p, scopes=[UPLOAD])
    p.chmod(0o644)
    assert oauth_manager.status()["token_file_private"] is False


def test_authenticate_runs_flow_and_saves_token(tmp_path, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "abc.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", FAKE_SECRET)
    seen = {}

    class FakeFlow:
        def run_local_server(self, **kw):
            seen.update(kw)
            return Credentials(token=FAKE_ACCESS, refresh_token=FAKE_REFRESH, token_uri="https://oauth2.googleapis.com/token",
                               client_id="abc", client_secret=FAKE_SECRET, scopes=[UPLOAD, YT],
                               expiry=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1))

    def factory(config, scopes):
        seen["scopes"] = scopes
        seen["config_client_id"] = config["installed"]["client_id"]
        return FakeFlow()

    result = oauth_manager.authenticate([UPLOAD, YT], open_browser=False, flow_factory=factory)
    assert seen["access_type"] == "offline" and seen["prompt"] == "consent"
    assert seen["host"] == "localhost" and seen["port"] == 8080 and seen["open_browser"] is False
    assert result["state"] == "AUTHENTICATED" and result["has_refresh_token"]
    assert oct((tmp_path / "token.json").stat().st_mode & 0o777) == "0o600"


# ---------------------------------------------------------------- CLI + env ------
def test_validate_auth_cli_exit_code_when_not_authenticated():
    r = run_script("skills/youtube-auth/scripts/validate_auth.py", "--json")
    assert r.returncode == 4
    data = json.loads(r.stdout)
    assert data["ok"] is False and data["state"] == "NOT_AUTHENTICATED"


def test_validate_auth_cli_ok_with_token(tmp_path):
    write_token(tmp_path / "token.json", scopes=[UPLOAD, YT])
    r = run_script("skills/youtube-auth/scripts/validate_auth.py", "--require", "upload,manage", "--json",
                   env={"GOOGLE_CLIENT_ID": "x.apps.googleusercontent.com", "GOOGLE_CLIENT_SECRET": "placeholder"})
    assert r.returncode == 0, r.stderr
    assert FAKE_REFRESH not in r.stdout and FAKE_ACCESS not in r.stdout


def test_env_example_lists_required_variables_without_values():
    text = (ROOT / ".env.example").read_text()
    for var in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REDIRECT_URI", "GOOGLE_TOKEN_PATH", "OPENAI_API_KEY",
                "YOUTUBE_DEFAULT_PRIVACY", "YOUTUBE_DEFAULT_CATEGORY", "YOUTUBE_DRY_RUN", "LOG_LEVEL"):
        assert re.search(rf"^{var}=", text, re.M), var
    for secret in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "OPENAI_API_KEY"):
        assert re.search(rf"^{secret}=\s*$", text, re.M), f"{secret} must be empty in .env.example"
    assert re.search(r"^YOUTUBE_DRY_RUN=true$", text, re.M)


def test_gitignore_protects_secrets():
    text = (ROOT / ".gitignore").read_text().splitlines()
    for entry in (".env", "*.token", "token.json", "credentials.json", "__pycache__/", ".pytest_cache/", "logs/*", "state/*.json"):
        assert entry in text, entry
