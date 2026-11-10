"""End-to-end pipeline behaviour against the real google-api-python-client with scripted HTTP
(LEVEL 3 integration: real request building, real resumable-upload protocol, fake Google)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
import yaml
from conftest import SAMPLE_SRT, SAMPLE_THUMB, SAMPLE_VIDEO, ScriptedHttp, load_script, ok, read_log

from src.exceptions import AuthError, ConfirmationRequired, DuplicateUploadError, UploadUncertainError
from src.state import JobLocked
from src.youtube_client import YouTubeClient, build_services

pipeline_mod = load_script("youtube-pipeline", "pipeline")
Pipeline = pipeline_mod.Pipeline

TITLE = "Aku kira menikah beda negara cuma soal cinta"
SIZE = SAMPLE_VIDEO.stat().st_size
SESSION = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&upload_id=SESSION1"


def write_config(tmp_path, *, thumbnail=True, transcript=True, publish_at=None, privacy="private", key=None, topic=False):
    cfg = {
        "video": {"file": str(SAMPLE_VIDEO), "idempotency_key": key},
        "metadata": {"title": None if topic else TITLE, "description": "Cerita nyata kami.", "tags": ["nikah beda negara", "indonesia pakistan"]},
        "publish": {"privacy": privacy, "publish_at": publish_at, "made_for_kids": False, "default_language": "id"},
        "thumbnail": {"file": str(SAMPLE_THUMB)} if thumbnail else {},
        "transcript": {"enabled": transcript, "source": "file", "file": str(SAMPLE_SRT), "language": "id", "name": "Bahasa Indonesia"},
    }
    if topic:
        from conftest import ROOT

        cfg["metadata"]["topic_file"] = str(ROOT / "data/topics/sample_topic.yaml")
    name = f"pipeline_{key or 'main'}.yaml"
    p = tmp_path / name
    p.write_text(yaml.safe_dump(cfg, allow_unicode=True))
    return p


def remote_video(vid="VID1", privacy="private", title=TITLE, publish_at=None):
    status = {"uploadStatus": "uploaded", "privacyStatus": privacy, "selfDeclaredMadeForKids": False}
    if publish_at:
        status["publishAt"] = publish_at
    return {"id": vid, "snippet": {"title": title, "categoryId": "22"}, "status": status, "processingDetails": {"processingStatus": "processing"}}


def factory_for(rt, script):
    http = ScriptedHttp(script)
    youtube, _ = build_services(http=http)
    client = YouTubeClient(youtube, None, quota=rt.quota, policy=rt.policy)
    calls = []

    def factory(runtime, ops):
        calls.append(ops)
        return client

    return factory, http, calls


def full_success_script(vid="VID1", **remote):
    return [
        ({"status": "200", "location": SESSION}, ""),          # videos.insert: start resumable session
        ok({"id": vid, "snippet": {"title": TITLE}}),          # PUT bytes → created
        ok({"items": [{"default": {"url": "https://i.ytimg.com/vi/x/default.jpg"}}]}),  # thumbnails.set
        ok({"id": "CAP1", "snippet": {"language": "id"}}),     # captions.insert
        ok({"items": [remote_video(vid, **remote)]}),          # videos.list (verification)
    ]


# --------------------------------------------------------------- dry run ---------
def test_dry_run_makes_no_api_calls_and_writes_report(rt, tmp_path):
    def forbidden(*a, **k):
        raise AssertionError("dry run must not build an API client")

    report = Pipeline(write_config(tmp_path, topic=True), rt, client_factory=forbidden).run(dry_run=True, confirm=False)
    assert report["mode"] == "dry_run"
    statuses = {s["name"]: s["status"] for s in report["steps"]}
    assert statuses["upload"] == "dry_run" and statuses["validate_thumbnail"] == "ok" and statuses["process_transcript"] == "ok"
    assert statuses["verify_auth"] == "warning"  # no token in the test environment, reported not hidden
    assert [s["n"] for s in report["steps"]] == list(range(1, 15))
    assert report["planned_calls"] == ["videos.insert", "thumbnails.set", "videos.list", "captions.insert"]
    assert report["request_body"]["status"]["selfDeclaredMadeForKids"] is False
    assert json.loads(open(report["report_file"]).read())["job_id"] == report["job_id"]
    assert rt.quota.report()["buckets"]["data_api"]["used_estimate"] == 0


def test_dry_run_wins_over_confirm(rt, tmp_path):
    report = Pipeline(write_config(tmp_path), rt, client_factory=lambda *a: pytest.fail("no client in dry run")).run(dry_run=True, confirm=True)
    assert report["mode"] == "dry_run"


def test_refuses_without_confirm_and_explains(rt, tmp_path):
    with pytest.raises(ConfirmationRequired) as exc:
        Pipeline(write_config(tmp_path), rt, client_factory=lambda *a: pytest.fail("no client")).run(dry_run=False, confirm=False)
    assert "--confirm" in str(exc.value) and "Validation report" in str(exc.value)
    assert exc.value.exit_code == 2


def test_env_safety_lock_blocks_confirm(rt, tmp_path, monkeypatch):
    monkeypatch.setenv("YOUTUBE_DRY_RUN", "true")
    factory, http, _ = factory_for(rt, [])
    with pytest.raises(ConfirmationRequired, match="YOUTUBE_DRY_RUN"):
        Pipeline(write_config(tmp_path), rt, client_factory=factory).run(dry_run=False, confirm=True)
    assert http.requests == []


def test_missing_credentials_stop_before_anything(rt, tmp_path):
    with pytest.raises(AuthError, match="authenticate.py"):
        Pipeline(write_config(tmp_path), rt).run(dry_run=False, confirm=True)
    assert rt.store.list_jobs() == []


# --------------------------------------------------------------- execute ---------
def test_full_run_uploads_once_and_completes(rt, tmp_path, log_path):
    factory, http, calls = factory_for(rt, full_success_script())
    report = Pipeline(write_config(tmp_path), rt, client_factory=factory).run(dry_run=False, confirm=True)
    assert report["exit_code"] == 0, report["steps"]
    assert report["video_id"] == "VID1" and report["job_status"] == "COMPLETED"
    assert set(calls[0]) == {"videos.insert", "videos.list", "thumbnails.set", "captions.insert"}

    start = http.requests[0]
    assert start["method"] == "POST" and "/upload/youtube/v3/videos" in start["uri"] and "uploadType=resumable" in start["uri"]
    body = json.loads(start["body"])
    assert body["snippet"]["title"] == TITLE and body["snippet"]["defaultLanguage"] == "id"
    assert body["status"] == {"privacyStatus": "private", "selfDeclaredMadeForKids": False}
    assert http.requests[1]["method"] == "PUT" and http.requests[1]["uri"] == SESSION
    assert http.requests[1]["headers"]["Content-Range"] == f"bytes 0-{SIZE - 1}/{SIZE}"
    assert "/thumbnails/set" in http.requests[2]["uri"] and "/captions" in http.requests[3]["uri"]
    assert "/youtube/v3/videos" in http.requests[4]["uri"] and http.requests[4]["method"] == "GET"

    job = rt.store.load(report["job_id"])
    assert job["status"] == "COMPLETED" and job["resumable_uri"] is None
    assert [h["to"] for h in job["history"]] == ["UPLOADING", "UPLOADED", "THUMBNAIL_SET", "VERIFIED", "COMPLETED"]
    assert rt.store.find_upload(job["file_sha256"])["video_id"] == "VID1"
    used = rt.quota.report()["buckets"]
    assert used["videos_insert"]["used_estimate"] == 1 and used["data_api"]["used_estimate"] == 50 + 400 + 1
    records = read_log(log_path)
    assert {r["request_id"] for r in records} == {rt.request_id}


def test_scheduled_publish_sends_utc_publish_at(rt, tmp_path):
    when = (datetime.now(timezone.utc) + timedelta(days=1)).replace(microsecond=0)
    local = when.astimezone(timezone(timedelta(hours=7))).isoformat()
    utc = when.strftime("%Y-%m-%dT%H:%M:%SZ")
    factory, http, _ = factory_for(rt, [({"status": "200", "location": SESSION}, ""), ok({"id": "VID2"}), ok({"items": [remote_video("VID2", publish_at=utc)]})])
    report = Pipeline(write_config(tmp_path, thumbnail=False, transcript=False, publish_at=local), rt, client_factory=factory).run(dry_run=False, confirm=True)
    assert json.loads(http.requests[0]["body"])["status"]["publishAt"] == utc
    assert report["exit_code"] == 0
    assert any(c["name"] == "publishAt" and c["ok"] for c in rt.store.load(report["job_id"])["verification"]["checks"])


def test_rerun_is_idempotent(rt, tmp_path):
    cfg = write_config(tmp_path)
    factory, _, _ = factory_for(rt, full_success_script())
    first = Pipeline(cfg, rt, client_factory=factory).run(dry_run=False, confirm=True)
    factory2, http2, _ = factory_for(rt, [ok({"items": [remote_video()]})])  # only verification is allowed
    second = Pipeline(cfg, rt, client_factory=factory2).run(dry_run=False, confirm=True)
    assert second["video_id"] == first["video_id"] == "VID1"
    assert [r["method"] for r in http2.requests] == ["GET"]
    steps = {s["name"]: s for s in second["steps"]}
    assert steps["upload"]["status"] == "skipped"
    assert "already set" in json.dumps(steps["apply_assets"]["detail"])


def test_same_file_under_another_job_is_refused(rt, tmp_path):
    factory, _, _ = factory_for(rt, full_success_script())
    Pipeline(write_config(tmp_path), rt, client_factory=factory).run(dry_run=False, confirm=True)
    factory2, http2, _ = factory_for(rt, [])
    with pytest.raises(DuplicateUploadError, match="VID1"):
        Pipeline(write_config(tmp_path, key="second-try"), rt, client_factory=factory2).run(dry_run=False, confirm=True)
    assert http2.requests == []


def test_interrupted_upload_resumes_from_saved_session(rt, tmp_path):
    cfg = write_config(tmp_path, thumbnail=False, transcript=False)
    factory, http, _ = factory_for(rt, [({"status": "200", "location": SESSION}, ""), TimeoutError("timed out"), TimeoutError("timed out"), TimeoutError("timed out")])
    with pytest.raises(UploadUncertainError, match="do not start a new upload"):
        Pipeline(cfg, rt, client_factory=factory).run(dry_run=False, confirm=True)
    job = rt.store.list_jobs()[0]
    assert job["status"] == "UPLOAD_UNCERTAIN" and job["resumable_uri"] == SESSION and not job["video_id"]
    # the retry after a timeout asked Google for the byte count instead of re-sending blindly
    assert http.requests[2]["headers"]["Content-Range"] == f"bytes */{SIZE}"

    factory2, http2, _ = factory_for(rt, [({"status": "308", "range": "bytes=0-9999"}, ""), ok({"id": "VID3"}), ok({"items": [remote_video("VID3")]})])
    report = Pipeline(cfg, rt, client_factory=factory2).run(dry_run=False, confirm=True)
    assert report["video_id"] == "VID3" and report["exit_code"] == 0
    assert [r["method"] for r in http2.requests] == ["PUT", "PUT", "GET"]  # no new POST = no second upload
    assert http2.requests[0]["headers"]["Content-Range"] == f"bytes */{SIZE}"
    assert http2.requests[1]["headers"]["Content-Range"] == f"bytes 10000-{SIZE - 1}/{SIZE}"
    assert rt.quota.report()["buckets"]["videos_insert"]["used_estimate"] == 1


def _interrupt(rt, cfg):
    factory, _, _ = factory_for(rt, [({"status": "200", "location": SESSION}, "")] + [TimeoutError("t")] * 3)
    with pytest.raises(UploadUncertainError):
        Pipeline(cfg, rt, client_factory=factory).run(dry_run=False, confirm=True)


def test_expired_session_checks_channel_before_anything_else(rt, tmp_path):
    cfg = write_config(tmp_path, thumbnail=False, transcript=False)
    _interrupt(rt, cfg)
    found = {**remote_video("VID4"), "fileDetails": {"fileSize": str(SIZE)}}
    factory, http, _ = factory_for(rt, [
        ({"status": "404"}, "Not Found"),                                                         # session gone
        ok({"items": [{"id": "UC1", "contentDetails": {"relatedPlaylists": {"uploads": "UU1"}}}]}),  # channels.list
        ok({"items": [{"contentDetails": {"videoId": "VID4"}}]}),                                 # playlistItems.list
        ok({"items": [found]}),                                                                   # videos.list (title+size)
        ok({"items": [remote_video("VID4")]}),                                                    # verification
    ])
    report = Pipeline(cfg, rt, client_factory=factory).run(dry_run=False, confirm=True)
    assert report["video_id"] == "VID4"
    assert not any(r["method"] == "POST" for r in http.requests)


def test_inconclusive_remote_check_needs_a_human(rt, tmp_path):
    cfg = write_config(tmp_path, thumbnail=False, transcript=False)
    _interrupt(rt, cfg)
    factory, http, _ = factory_for(rt, [
        ({"status": "404"}, "Not Found"),
        ok({"items": [{"id": "UC1", "contentDetails": {"relatedPlaylists": {"uploads": "UU1"}}}]}),
        ok({"items": []}),
    ])
    with pytest.raises(UploadUncertainError, match="--force-reupload"):
        Pipeline(cfg, rt, client_factory=factory).run(dry_run=False, confirm=True)
    assert rt.store.list_jobs()[0]["status"] == "NEEDS_MANUAL_CHECK"
    assert not any(r["method"] == "POST" for r in http.requests)


def test_public_request_locked_private_is_reported(rt, tmp_path):
    factory, _, _ = factory_for(rt, [({"status": "200", "location": SESSION}, ""), ok({"id": "VID5"}), ok({"items": [remote_video("VID5", privacy="private")]})])
    report = Pipeline(write_config(tmp_path, thumbnail=False, transcript=False, privacy="public"), rt, client_factory=factory).run(dry_run=False, confirm=True)
    assert report["exit_code"] == pipeline_mod.PARTIAL
    assert any("audit" in w for w in report["warnings"])
    assert rt.store.load(report["job_id"])["status"] != "COMPLETED"


def test_job_lock_prevents_concurrent_runs(rt):
    with rt.store.lock("abc"):
        with pytest.raises(JobLocked):
            with rt.store.lock("abc"):
                pass
    with rt.store.lock("abc"):  # released afterwards
        pass


def test_invalid_config_is_rejected_early(rt, tmp_path):
    from src.exceptions import ValidationError

    p = tmp_path / "bad.yaml"
    p.write_text("video: {}\nmetadata: {}\n")
    with pytest.raises(ValidationError) as exc:
        Pipeline(p, rt).run(dry_run=True, confirm=False)
    assert any("video.file" in i for i in exc.value.issues)


def test_pipeline_cli_dry_run_and_refusal():
    from conftest import run_script

    r = run_script("skills/youtube-pipeline/scripts/pipeline.py", "--config", "examples/sample_pipeline.yaml", "--dry-run", "--json")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["mode"] == "dry_run"
    r = run_script("skills/youtube-pipeline/scripts/pipeline.py", "--config", "examples/sample_pipeline.yaml")
    assert r.returncode == 2 and "--confirm" in r.stderr


def test_state_manager_lists_recent_jobs(rt, tmp_path):
    from conftest import run_script

    factory, _, _ = factory_for(rt, full_success_script())
    Pipeline(write_config(tmp_path), rt, client_factory=factory).run(dry_run=False, confirm=True)
    r = run_script("skills/youtube-pipeline/scripts/state_manager.py", "list", "--since", "2d", "--json")
    rows = json.loads(r.stdout)
    assert rows and rows[0]["video_id"] == "VID1" and rows[0]["status"] == "COMPLETED"
