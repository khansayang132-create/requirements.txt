"""The company layer: planning, the queue, recovery, gates and publishing — with YouTube faked.

No video is rendered here (departments are stubbed where rendering would happen); the real
production line is exercised by tools/make_episode.py and the CI sample render.
"""

from __future__ import annotations

import types
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from wonderland import ceo as ceo_mod
from wonderland import finance
from wonderland.ceo import Studio
from wonderland.db import iso
from wonderland.departments import publishing, research
from wonderland.protocol import AgentReport, BlockedError, TransientError


class Clock:
    def __init__(self, t: datetime):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def studio(tmp_path):
    clock = Clock(datetime(2026, 11, 12, 0, 0, tzinfo=timezone.utc))   # 05:00 in Karachi
    s = Studio(state=tmp_path / "state", now_fn=clock)
    s.clock = clock
    return s


def stub_departments(monkeypatch, behaviour=None):
    """Replace every department with a stub that succeeds (or does what ``behaviour[kind]`` says)."""
    behaviour = behaviour or {}
    calls: list[str] = []

    def handler(studio, task, ep):
        calls.append(task["key"])
        fn = behaviour.get(task["kind"])
        if fn:
            return fn(studio, task, ep)
        return AgentReport(task["agent"], task["key"], "success", output={"stub": True})

    monkeypatch.setattr(Studio, "_handler", lambda self, kind: handler)
    return calls


# ------------------------------------------------------------------ planning
def test_plan_is_idempotent_and_covers_buffer(studio):
    first = studio.plan()
    assert len(first["episodes"]) == 12                     # 4 slots × (today + 2 buffer days)
    assert studio.plan() == {"episodes": [], "tasks": 0}
    ids = {e["id"] for e in studio.db.episodes()}
    assert "ep-20261112-s1" in ids and "ep-20261114-s4" in ids
    chain = studio.db.task("ep-20261112-s1:verify")
    assert chain["depends_on"] == ["ep-20261112-s1:publish"]


def test_passed_slots_are_not_planned(studio):
    studio.clock.t = datetime(2026, 11, 12, 9, 0, tzinfo=timezone.utc)   # 14:00 Karachi: slots 1 and 2 passed
    eps = studio.plan()["episodes"]
    assert "ep-20261112-s1" not in eps and "ep-20261112-s2" not in eps and "ep-20261112-s3" in eps


def test_backlog_limit_pauses_planning(studio):
    studio.cfg["max_unpublished"] = 5
    assert len(studio.plan()["episodes"]) == 5


# ------------------------------------------------------------------ queue
def test_cycle_runs_chain_in_order(studio, monkeypatch):
    calls = stub_departments(monkeypatch)
    studio.run_cycle()
    one = [c for c in calls if c.startswith("ep-20261112-s1:")]
    assert [c.split(":")[1] for c in one] == list(ceo_mod.EPISODE_CHAIN)
    assert calls.index("day-20261112:research") < calls.index("ep-20261112-s1:script")


def test_transient_errors_retry_with_backoff_then_succeed(studio, monkeypatch):
    state = {"n": 0}

    def flaky(s, task, ep):
        if task["key"] == "ep-20261112-s1:animation" and state["n"] < 2:
            state["n"] += 1
            raise TransientError("encoder busy")
        return AgentReport(task["agent"], task["key"], "success")

    stub_departments(monkeypatch, {"animation": flaky})
    studio.run_cycle()
    t = studio.db.task("ep-20261112-s1:animation")
    assert t["status"] == "pending" and t["not_before"]          # waiting out the backoff, not failed
    studio.clock.t += timedelta(hours=1)
    studio.run_cycle()
    studio.clock.t += timedelta(hours=1)
    studio.run_cycle()
    assert studio.db.task("ep-20261112-s1:animation")["status"] == "done"


def test_permanent_failure_stops_only_that_episode(studio, monkeypatch):
    def broken(s, task, ep):
        if task["episode_id"] == "ep-20261112-s2":
            raise ValueError("bad storyboard")
        return AgentReport(task["agent"], task["key"], "success")

    stub_departments(monkeypatch, {"storyboard": broken})
    studio.run_cycle()
    assert studio.db.task("ep-20261112-s2:storyboard")["status"] == "failed"
    assert studio.db.task("ep-20261112-s2:animation")["status"] == "cancelled"
    assert studio.db.episode("ep-20261112-s2")["status"] == "failed"
    assert studio.db.task("ep-20261112-s3:animation")["status"] == "done"
    assert studio.db.scalar("SELECT COUNT(*) FROM notifications WHERE title LIKE 'Failed:%'") >= 1


def test_crashed_worker_is_recovered(studio, monkeypatch):
    stub_departments(monkeypatch)
    studio.plan()
    claimed = studio.db.claim("dead-worker", studio.now(), lease_seconds=60, respect_cycle=False)
    assert claimed and studio.db.task(claimed["key"])["status"] == "running"
    studio.clock.t += timedelta(minutes=5)                      # the lease expired; the worker never came back
    studio.run_cycle()
    assert studio.db.task(claimed["key"])["status"] == "done"


def test_restart_continues_from_database(studio, monkeypatch, tmp_path):
    stub_departments(monkeypatch)
    studio.plan()
    for _ in range(5):
        studio.tick(catch_up=True)
    done_before = studio.db.scalar("SELECT COUNT(*) FROM tasks WHERE status='done'")
    again = Studio(state=studio.state, now_fn=studio.clock)    # a new process on the same state folder
    again.run_cycle()
    assert again.db.scalar("SELECT COUNT(*) FROM tasks WHERE status='done'") > done_before
    assert again.db.scalar("SELECT COUNT(*) FROM tasks WHERE status='pending' AND kind='script'") == 0


def test_quality_failure_orders_a_new_story_then_gives_up(studio, monkeypatch):
    from wonderland.protocol import QualityError

    def qa(s, task, ep):
        if task["episode_id"] == "ep-20261112-s1":
            raise QualityError("freeze")
        return AgentReport(task["agent"], task["key"], "success")

    calls = stub_departments(monkeypatch, {"qa": qa})
    studio.run_cycle()
    assert calls.count("ep-20261112-s1:script") == 3               # first story + max_regenerations (2)
    assert studio.db.episode("ep-20261112-s1")["status"] == "failed"


def test_blocked_work_is_parked_and_rechecked(studio, monkeypatch):
    def needs_owner(s, task, ep):
        raise BlockedError("not signed in", needs="owner signs in")

    stub_departments(monkeypatch, {"publish": needs_owner})
    studio.run_cycle()
    t = studio.db.task("ep-20261112-s1:publish")
    assert t["status"] == "blocked" and t["attempts"] == 0
    assert studio.db.task("ep-20261112-s1:verify")["status"] == "pending"
    assert {"task": "ep-20261112-s1:publish", "reason": "not signed in"} in studio.worklist()["blocked"]


def test_every_report_has_the_protocol_fields(studio, monkeypatch):
    stub_departments(monkeypatch)
    studio.run_cycle()
    for r in studio.db.reports(limit=20):
        assert {"agent", "task_id", "status", "output", "evidence", "errors", "next_action"} <= set(r)
    with pytest.raises(ValueError):
        AgentReport("x", "1", "failed")                           # a failure must say what failed
    with pytest.raises(ValueError):
        AgentReport("x", "1", "done")


# ------------------------------------------------------------------ owner actions
def produced_episode(studio, ep_id="ep-20261112-s1", tmp_path: Path | None = None) -> dict:
    studio.plan()
    folder = studio.episode_dir(ep_id)
    video = folder / "final.mp4"
    video.write_bytes(b"\x00" * 2048)
    import hashlib
    studio.db.update_episode(ep_id, studio.now(), status="produced", video_path=str(video), video_sha256=hashlib.sha256(video.read_bytes()).hexdigest(),
                             dir=str(folder), title="Count to 3 With Zuzu",
                             metadata={"title": "Count to 3 With Zuzu", "description": "Zuzu counts.", "tags": ["counting"], "category_id": "27",
                                       "playlist": "Count With Me", "default_language": "en", "made_for_kids": True},
                             compliance={"ok": True, "disclosure": {"contains_synthetic_media": False}})
    return studio.db.episode(ep_id)


def test_approve_and_reject(studio):
    ep = produced_episode(studio)
    assert studio.approve(ep["id"])["approved"] is True
    with pytest.raises(ValueError):
        studio.approve("ep-20261112-s2")                           # not produced
    rej = studio.reject("ep-20261112-s2", "not good enough")
    assert rej["status"] == "rejected"
    assert studio.db.scalar("SELECT COUNT(*) FROM tasks WHERE episode_id='ep-20261112-s2' AND status='pending'") == 0


# ------------------------------------------------------------------ publishing (YouTube faked)
@dataclass
class FakeSpec:
    file: Path
    title: str
    description: str = ""
    tags: list = field(default_factory=list)
    category_id: str = "27"
    privacy: str = "private"
    made_for_kids: bool = True
    publish_at: str | None = None
    default_language: str | None = None
    default_audio_language: str | None = None
    notify_subscribers: bool | None = None
    idempotency_key: str | None = None
    contains_synthetic_media: bool | None = None


class FakeStore:
    def __init__(self):
        self.index = {}

    def find_upload(self, sha):
        return self.index.get(sha)


class FakeYouTube:
    def __init__(self):
        self.uploads = 0
        self.privacy = "private"
        self.playlists = {}

    def get_video(self, vid, parts=""):
        return {"id": vid, "status": {"uploadStatus": "processed", "privacyStatus": self.privacy}}

    def list_playlists(self):
        return [{"id": v, "snippet": {"title": k}} for k, v in self.playlists.items()]

    def create_playlist(self, title, description, privacy):
        self.playlists[title] = f"PL{len(self.playlists)}"
        return {"id": self.playlists[title]}

    def add_to_playlist(self, pid, vid):
        return {}


def fake_uploader(yt: FakeYouTube, store: FakeStore):
    def run_upload(client, st, spec, chunk_size, **kw):
        yt.uploads += 1
        vid = f"vid{yt.uploads}"
        store.index[spec_sha[0]] = {"video_id": vid}
        return {}, {"id": vid}

    spec_sha = [None]

    def verify_video(client, vid, spec):
        return {"exists": True, "ok": True, "checks": [], "url": f"https://youtu.be/{vid}"}

    mod = types.SimpleNamespace(UploadSpec=FakeSpec, validate_spec=lambda s: types.SimpleNamespace(ok=True, errors=[]),
                                run_upload=run_upload, verify_video=verify_video)
    mod.spec_sha = spec_sha
    return mod


def wire_youtube(studio):
    yt, store = FakeYouTube(), FakeStore()
    mod = fake_uploader(yt, store)
    studio.uploader_module = mod
    studio.youtube_factory = lambda ops: (yt, types.SimpleNamespace(store=store))
    return yt, store, mod


def publish(studio, ep_id):
    task = studio.db.task(f"{ep_id}:publish")
    return publishing.handle_publish(studio, task, studio.db.episode(ep_id))


def test_publishing_off_blocks(studio):
    produced_episode(studio)
    wire_youtube(studio)
    studio.cfg["publishing"]["mode"] = "off"
    with pytest.raises(BlockedError, match="mode is off"):
        publish(studio, "ep-20261112-s1")


def test_review_mode_needs_approval_of_this_exact_file(studio):
    ep = produced_episode(studio)
    yt, _, _ = wire_youtube(studio)
    studio.cfg["publishing"]["mode"] = "review"
    with pytest.raises(BlockedError, match="waiting for review"):
        publish(studio, ep["id"])
    studio.approve(ep["id"])
    studio.db.update_episode(ep["id"], studio.now(), video_sha256="changed")
    with pytest.raises(BlockedError, match="changed after it was approved"):
        publish(studio, ep["id"])
    assert yt.uploads == 0


def test_upload_schedule_verify_publish_and_no_duplicates(studio):
    ep = produced_episode(studio)
    yt, store, mod = wire_youtube(studio)
    mod.spec_sha[0] = ep["video_sha256"]
    studio.cfg["publishing"]["mode"] = "auto"
    rep = publish(studio, ep["id"])
    assert rep.status == "success" and yt.uploads == 1
    ep = studio.db.episode(ep["id"])
    assert ep["status"] == "uploaded" and ep["video_id"] == "vid1"
    assert "Count With Me" in yt.playlists

    # uploaded is NOT published: verify sees it private and scheduled
    v = publishing.handle_verify(studio, studio.db.task(f"{ep['id']}:verify"), ep)
    assert v.output["status"] == "scheduled" and v.next_action.startswith("recheck:")
    assert studio.db.episode(ep["id"])["status"] == "scheduled"

    # recovery: the episode row lost its video id (crash before it was saved) — the file is NOT uploaded again
    studio.db.update_episode(ep["id"], studio.now(), video_id=None, status="produced")
    publish(studio, ep["id"])
    assert yt.uploads == 1 and studio.db.episode(ep["id"])["video_id"] == "vid1"

    yt.privacy = "public"
    studio.clock.t = datetime(2026, 11, 12, 4, 10, tzinfo=timezone.utc)
    v = publishing.handle_verify(studio, studio.db.task(f"{ep['id']}:verify"), studio.db.episode(ep["id"]))
    assert v.output["status"] == "published" and studio.db.episode(ep["id"])["status"] == "published"


def test_first_upload_is_a_controlled_test(studio):
    a = produced_episode(studio, "ep-20261112-s1")
    yt, _, mod = wire_youtube(studio)
    studio.cfg["publishing"]["mode"] = "auto"
    mod.spec_sha[0] = a["video_sha256"]
    publish(studio, a["id"])
    b = produced_episode(studio, "ep-20261112-s2")
    studio.db.update_episode(b["id"], studio.now(), video_sha256="other")
    with pytest.raises(BlockedError, match="first \\(test\\) upload"):
        publish(studio, b["id"])
    assert yt.uploads == 1


def test_missed_slot_is_not_uploaded_late(studio):
    ep = produced_episode(studio)
    yt, _, _ = wire_youtube(studio)
    studio.cfg["publishing"]["mode"] = "auto"
    studio.clock.t = datetime(2026, 11, 12, 3, 55, tzinfo=timezone.utc)   # 08:55 Karachi, slot is 09:00
    rep = publish(studio, ep["id"])
    assert rep.status == "skipped" and yt.uploads == 0


# ------------------------------------------------------------------ money, research, reports
def test_paid_provider_needs_authorization_and_limits(studio):
    with pytest.raises(BlockedError, match="not authorized"):
        finance.require_budget(studio, 0.01, "voice")
    studio.cfg["budget"].update(paid_providers_authorized=True, daily_usd_limit=0.05, monthly_usd_limit=1.0)
    finance.require_budget(studio, 0.01, "voice")
    studio.db.add_cost(studio.now(), f"{studio.local_day():%Y-%m-%d}", "voice", "elevenlabs", 0.045)
    with pytest.raises(BlockedError, match="today's limit"):
        finance.require_budget(studio, 0.01, "voice")


def test_research_database_is_sourced_and_honest(studio):
    task = {"key": "day-x:research"}
    rep = research.handle_research(studio, task, None)
    assert rep.status == "success"
    rows = research.search(studio.db, "kids")
    assert rows and all(r["source"] and r["date"] and r["confidence"] and r["recommended_action"] for r in rows)
    assert not studio.db.q("SELECT id FROM research WHERE source='editorial judgement' AND confidence='high'")
    with pytest.raises(ValueError):
        research.add_finding(studio.db, {"topic": "t", "source": "editorial judgement", "date": "2026-01-01", "findings": "f",
                                         "confidence": "high", "recommended_action": "a"}, studio.now())
    assert "search-volume" in studio.db.get("research_brief")["basis"] or "no external demand" in studio.db.get("research_brief")["basis"]


def test_reports_never_invent_numbers(studio):
    from wonderland import ops
    studio.plan()
    r = ops.build_report(studio, "weekly")
    assert "Nothing is estimated" in r["body"]
    assert r["data"]["channel"] == "YouTube not connected or no data yet"
    assert "impressions" in r["data"]["not_available"]


def test_health_and_backup(studio):
    from wonderland import ops
    h = ops.health(studio)
    assert {c["name"] for c in h["checks"]} >= {"disk_space", "ffmpeg", "database", "budget"}
    path = ops.backup(studio)
    assert path.is_file() and path.stat().st_size > 0


def test_notifications_are_deduplicated(studio):
    a = studio.db.notify("error", "x", "y", studio.now(), fingerprint="same")
    b = studio.db.notify("error", "x", "y", studio.now(), fingerprint="same")
    assert a and b is None


def test_times_are_utc_iso(studio):
    assert iso(studio.now()).endswith("Z")


def test_catch_up_finishes_one_episode_at_a_time(studio, monkeypatch):
    calls = stub_departments(monkeypatch)
    studio.run_cycle()
    first = [c for c in calls if c.startswith("ep-")]
    assert first[: len(ceo_mod.EPISODE_CHAIN)] == [f"ep-20261112-s1:{k}" for k in ceo_mod.EPISODE_CHAIN]
