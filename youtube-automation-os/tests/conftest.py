"""Shared fixtures. No test touches the network: Google services are built from the
discovery documents bundled with google-api-python-client and wired to scripted HTTP."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import httplib2
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import cli, logger  # noqa: E402
from src.config import load_settings  # noqa: E402
from src.quota_manager import from_settings  # noqa: E402
from src.retry import RetryPolicy  # noqa: E402
from src.state import StateStore  # noqa: E402
from src.youtube_client import YouTubeClient, build_services  # noqa: E402

SAMPLE_VIDEO = ROOT / "data" / "videos" / "sample.mp4"
SAMPLE_THUMB = ROOT / "data" / "thumbnails" / "sample.jpg"
SAMPLE_SRT = ROOT / "data" / "transcripts" / "sample.srt"


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Every test gets its own log/state/token paths and no Google credentials."""
    for var in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_CLIENT_SECRETS_FILE", "GOOGLE_REDIRECT_URI",
                "YOUTUBE_DAILY_QUOTA", "YOUTUBE_DEFAULT_PRIVACY", "YOUTUBE_DEFAULT_CATEGORY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("YOUTUBE_DRY_RUN", "false")
    monkeypatch.setenv("GOOGLE_TOKEN_PATH", str(tmp_path / "token.json"))
    monkeypatch.setenv("YTAOS_LOG_PATH", str(tmp_path / "logs" / "ytaos.jsonl"))
    monkeypatch.setenv("YTAOS_STATE_DIR", str(tmp_path / "state"))
    logger.set_logger(None)
    yield
    logger.set_logger(None)


@pytest.fixture
def log_path(tmp_path) -> Path:
    return tmp_path / "logs" / "ytaos.jsonl"


def read_log(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.fixture
def settings(tmp_path) -> dict:
    s = copy.deepcopy(load_settings())
    s["paths"]["state_dir"] = str(tmp_path / "state")
    return s


class NoSleep:
    def __init__(self):
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


@pytest.fixture
def rt(settings):
    r = cli.runtime(settings)
    r.policy = RetryPolicy(max_attempts=3, base_delay=1.0, max_delay=8.0, sleep=NoSleep())
    return r


def load_script(skill: str, name: str):
    path = ROOT / "skills" / skill / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"ytaos_{skill.replace('-', '_')}_{name}", path)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    spec.loader.exec_module(module)
    return module


# ------------------------------------------------------------- scripted HTTP ------
class ScriptedHttp:
    """httplib2-compatible fake. Each script item is (headers_dict, body) or an Exception to raise.

    Records every request so tests can assert exactly what would have been sent to Google.
    """

    def __init__(self, script: list):
        self.script = list(script)
        self.requests: list[dict] = []

    def request(self, uri, method="GET", body=None, headers=None, redirections=5, connection_type=None):
        if hasattr(body, "read"):
            body = body.read()
        self.requests.append({"uri": uri, "method": method, "headers": dict(headers or {}), "body": body})
        if not self.script:
            raise AssertionError(f"Unexpected HTTP request: {method} {uri}")
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        resp_headers, content = item
        if isinstance(content, (dict, list)):
            content = json.dumps(content)
        if isinstance(content, str):
            content = content.encode("utf-8")
        resp_headers = {k.lower(): str(v) for k, v in resp_headers.items()}
        resp_headers.setdefault("status", "200")
        return httplib2.Response(resp_headers), content


def ok(body) -> tuple:
    return ({"status": "200", "content-type": "application/json"}, body)


def err(status: int, reason: str, message: str = "error", extra_headers: dict | None = None) -> tuple:
    body = {"error": {"code": status, "message": message, "errors": [{"reason": reason, "message": message, "domain": "youtube"}]}}
    headers = {"status": str(status), "content-type": "application/json"}
    headers.update(extra_headers or {})
    return (headers, body)


def make_client(rt, script: list, analytics_script: list | None = None) -> tuple[YouTubeClient, ScriptedHttp]:
    http = ScriptedHttp(script)
    youtube, _ = build_services(http=http)
    analytics = None
    if analytics_script is not None:
        _, analytics = build_services(http=ScriptedHttp(analytics_script))
    return YouTubeClient(youtube, analytics, quota=rt.quota, policy=rt.policy), http


@pytest.fixture
def store(rt) -> StateStore:
    return rt.store


@pytest.fixture
def quota(settings, tmp_path):
    return from_settings(settings, tmp_path / "state")


def run_script(rel: str, *args: str, env: dict | None = None, tmp: Path | None = None) -> subprocess.CompletedProcess:
    e = {k: v for k, v in os.environ.items()}
    e.update(env or {})
    return subprocess.run([sys.executable, str(ROOT / rel), *args], capture_output=True, text=True, env=e, cwd=str(ROOT), timeout=120)
