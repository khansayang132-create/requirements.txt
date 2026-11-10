"""upload.py / update_video.py / schedule.py safety rules and request shapes."""

from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from conftest import SAMPLE_VIDEO, load_script, run_script

from src.exceptions import ConfirmationRequired
from src.safety import DRY_RUN, EXECUTE, decide_mode
from src.uploader import UploadSpec, merge_for_update, spec_from_mapping

UPLOAD = "skills/youtube-upload/scripts/upload.py"


# ------------------------------------------------------------------ gate ---------
def test_confirmation_rules(monkeypatch):
    assert decide_mode(dry_run=True, confirm=False, action="x") == DRY_RUN
    assert decide_mode(dry_run=True, confirm=True, action="x") == DRY_RUN  # dry-run takes precedence
    assert decide_mode(dry_run=False, confirm=True, action="x") == EXECUTE
    with pytest.raises(ConfirmationRequired, match="--confirm"):
        decide_mode(dry_run=False, confirm=False, action="x")
    monkeypatch.setenv("YOUTUBE_DRY_RUN", "true")
    with pytest.raises(ConfirmationRequired, match="YOUTUBE_DRY_RUN"):
        decide_mode(dry_run=False, confirm=True, action="x")
    assert decide_mode(dry_run=True, confirm=True, action="x") == DRY_RUN


# ------------------------------------------------------------- upload.py ---------
def test_upload_cli_refuses_without_flags():
    r = run_script(UPLOAD, "--file", str(SAMPLE_VIDEO), "--title", "t", "--not-made-for-kids")
    assert r.returncode == 2 and "--confirm" in r.stderr


def test_upload_cli_dry_run_shows_exact_request():
    r = run_script(UPLOAD, "--file", str(SAMPLE_VIDEO), "--title", "Judul", "--tags", "a,b", "--privacy", "unlisted",
                   "--publish-at", "2030-01-01T19:00:00+07:00", "--dry-run")
    assert r.returncode == 5  # publishAt with unlisted is invalid → nothing sent
    assert "publishAt requires privacyStatus 'private'" in r.stderr
    r = run_script(UPLOAD, "--file", str(SAMPLE_VIDEO), "--title", "Judul", "--tags", "a,b", "--privacy", "private",
                   "--publish-at", "2030-01-01T19:00:00+07:00", "--dry-run")
    assert r.returncode == 0, r.stderr
    d = json.loads(r.stdout)
    assert d["mode"] == "dry_run" and d["would_call"] == ["videos.insert", "videos.list"]
    assert d["request_body"]["status"] == {"privacyStatus": "private", "selfDeclaredMadeForKids": False, "publishAt": "2030-01-01T12:00:00Z"}
    assert d["request_body"]["snippet"]["tags"] == ["a", "b"]
    assert d["quota_estimate"] == {"videos_insert": 1, "data_api": 1}


def test_upload_cli_reads_metadata_file():
    r = run_script(UPLOAD, "--file", str(SAMPLE_VIDEO), "--metadata", "examples/sample_video.yaml", "--dry-run")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["request_body"]["snippet"]["defaultLanguage"] == "id"


def test_upload_cli_rejects_bad_input_before_anything():
    r = run_script(UPLOAD, "--file", "nope.mp4", "--title", "x" * 101, "--dry-run")
    assert r.returncode == 5
    assert "file not found" in r.stderr and "101 characters" in r.stderr


def test_upload_cli_confirm_without_token_fails_cleanly():
    r = run_script(UPLOAD, "--file", str(SAMPLE_VIDEO), "--title", "t", "--confirm")
    assert r.returncode == 4 and "authenticate.py" in r.stderr


def test_env_defaults_apply(monkeypatch):
    from src.config import upload_defaults

    monkeypatch.setenv("YOUTUBE_DEFAULT_PRIVACY", "unlisted")
    monkeypatch.setenv("YOUTUBE_DEFAULT_CATEGORY", "27")
    spec = spec_from_mapping({"file": str(SAMPLE_VIDEO), "title": "t"}, upload_defaults({"defaults": {"privacy": "private"}}))
    assert spec.privacy == "unlisted" and spec.category_id == "27" and spec.made_for_kids is False


def test_body_shape():
    body = UploadSpec(file=SAMPLE_VIDEO, title="t", tags=[], made_for_kids=True).body()
    assert "tags" not in body["snippet"] and body["status"]["selfDeclaredMadeForKids"] is True


# ------------------------------------------------------------ update_video -------
def test_merge_keeps_existing_fields():
    current = {
        "id": "V",
        "snippet": {"title": "old", "description": "keep me", "tags": ["a"], "categoryId": "22", "channelId": "UC", "thumbnails": {}},
        "status": {"privacyStatus": "private", "publishAt": "2030-01-01T00:00:00Z", "selfDeclaredMadeForKids": False, "embeddable": True, "uploadStatus": "processed"},
    }
    body, diff = merge_for_update(current, {"snippet": {"title": "new"}, "status": {"privacyStatus": "unlisted", "publishAt": None}})
    assert body["snippet"] == {"title": "new", "description": "keep me", "tags": ["a"], "categoryId": "22"}  # read-only fields dropped
    assert body["status"] == {"privacyStatus": "unlisted", "selfDeclaredMadeForKids": False, "embeddable": True}
    assert {d["field"] for d in diff} == {"snippet.title", "status.privacyStatus", "status.publishAt"}


def test_update_cli_needs_confirmation():
    r = run_script("skills/youtube-upload/scripts/update_video.py", "--video-id", "V", "--title", "baru")
    assert r.returncode == 2
    r = run_script("skills/youtube-upload/scripts/update_video.py", "--video-id", "V", "--delete")
    assert r.returncode == 2


def test_delete_requires_repeating_the_id():
    r = run_script("skills/youtube-upload/scripts/update_video.py", "--video-id", "V", "--delete", "--confirm", "--confirm-delete", "OTHER")
    assert r.returncode == 2 and "irreversible" in r.stderr


def test_update_validates_before_contacting_youtube():
    r = run_script("skills/youtube-upload/scripts/update_video.py", "--video-id", "V", "--title", "<bad>", "--confirm")
    assert r.returncode == 5


# ---------------------------------------------------------------- schedule -------
def test_schedule_tomorrow_computation():
    sched = load_script("youtube-upload", "schedule")
    now = datetime(2026, 11, 9, 23, 30, tzinfo=ZoneInfo("Asia/Jakarta"))
    dt = sched.resolve_time(SimpleNamespace(at=None, tomorrow="19:00", tz="Asia/Jakarta"), now=now)
    assert dt.isoformat() == "2026-11-10T19:00:00+07:00"


def test_schedule_cli_prints_upload_flag():
    r = run_script("skills/youtube-upload/scripts/schedule.py", "--tomorrow", "19:00", "--tz", "Asia/Jakarta", "--json")
    assert r.returncode == 0, r.stderr
    d = json.loads(r.stdout)
    assert d["publish_at_utc"].endswith("T12:00:00Z") and "--privacy private --publish-at" in d["upload_flag"]


def test_schedule_cli_rejects_past_time():
    r = run_script("skills/youtube-upload/scripts/schedule.py", "--at", "2020-01-01T10:00:00+07:00")
    assert r.returncode == 5 and "not in the future" in r.stderr
