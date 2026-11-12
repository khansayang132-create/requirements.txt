import os
import shutil
from pathlib import Path

import pytest

from dhfactory.config import Settings

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def ws(tmp_path, monkeypatch):
    """A clean workspace with the repo's configuration and no provider credentials."""
    for env in ("HEYGEN_API_KEY", "ELEVENLABS_API_KEY", "RUNWAYML_API_SECRET", "DID_API_KEY", "SYNTHESIA_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    shutil.copytree(ROOT / "configuration", tmp_path / "configuration")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DHF_WORKSPACE", str(tmp_path))
    return tmp_path


@pytest.fixture
def settings(ws):
    return Settings(_env_file=None, dhf_workspace=ws)


needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
os.environ.setdefault("PYTHONHASHSEED", "0")
