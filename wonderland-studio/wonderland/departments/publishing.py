"""Publishing department: upload, schedule and verify — through the official YouTube Data API only.

It reuses ``youtube-automation-os`` (resumable uploads, quota ledger, retries, duplicate index)
instead of talking to Google itself. Rules it enforces:

* nothing leaves the studio unless the episode passed the compliance gate;
* ``publishing.mode``: off = never upload; review = only episodes the owner approved (and only
  the exact file that was approved); auto = every episode that passed the gate;
* the toolkit's safety lock (``YOUTUBE_DRY_RUN=true``) blocks real uploads;
* the very first upload is a controlled test: no second upload until the first one has been
  verified on YouTube;
* uploads are private with a scheduled ``publishAt`` — YouTube itself flips them public at the
  slot time, so a studio outage never makes an episode late;
* the same file is never uploaded twice (sha256 index + per-episode idempotency key); after a
  crash the interrupted upload is resumed or found on the channel, never repeated;
* "published" is only recorded after ``videos.list`` shows the video public.
"""

from __future__ import annotations

import os
import sys
from datetime import timedelta
from pathlib import Path

from ..db import iso, parse_iso
from ..protocol import AgentReport, BlockedError, PermanentError, TransientError

UPLOAD_OPS = ["videos.insert", "videos.list", "channels.list", "playlistItems.list"]
PLAYLIST_OPS = ["playlists.list", "playlists.insert", "playlistItems.insert"]


def toolkit_root(studio) -> Path:
    return Path(os.environ.get("WONDERLAND_YTAOS_ROOT") or (studio.root.parent / "youtube-automation-os"))


def toolkit(studio):
    """Import the YouTube toolkit (``youtube-automation-os/src``) as package ``src``."""
    root = toolkit_root(studio)
    if not (root / "src" / "uploader.py").is_file():
        raise BlockedError(f"YouTube toolkit not found at {root}", needs="keep youtube-automation-os next to wonderland-studio")
    os.environ.setdefault("YTAOS_ROOT", str(root))
    os.environ.setdefault("YTAOS_STATE_DIR", str(studio.state / "youtube"))
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        import src.cli as cli  # noqa: PLC0415
        import src.exceptions as exc  # noqa: PLC0415
        import src.uploader as uploader  # noqa: PLC0415
        from src.config import dry_run_locked  # noqa: PLC0415
    except ImportError as e:   # google libraries not installed
        raise BlockedError(f"YouTube toolkit dependencies missing: {e}", needs="bash youtube-automation-os/scripts/setup.sh") from e
    return cli, uploader, exc, dry_run_locked


def make_client(studio, ops: list[str]):
    """The YouTube client for ``ops``. Tests set ``studio.youtube_factory``."""
    factory = getattr(studio, "youtube_factory", None)
    if factory:
        return factory(ops)
    cli, _, exc, _ = toolkit(studio)
    try:
        rt = cli.runtime()
        return cli.make_client(rt, ops), rt
    except (exc.AuthError, exc.ConfigError) as e:
        raise BlockedError(f"YouTube is not connected: {e}",
                           needs="owner signs in once: cd youtube-automation-os && .venv/bin/python skills/youtube-auth/scripts/authenticate.py "
                                 "--scopes upload,manage,analytics") from e


def _spec(uploader, ep: dict, studio):
    meta = ep["metadata"]
    disclosure = (ep.get("compliance") or {}).get("disclosure") or {}
    publish_at = parse_iso(ep["publish_at"])
    pub = studio.cfg.get("publishing", {})
    return uploader.UploadSpec(
        file=Path(ep["video_path"]), title=meta["title"], description=meta["description"], tags=meta["tags"],
        category_id=meta["category_id"], privacy="private", made_for_kids=True, publish_at=iso(publish_at),
        default_language=meta.get("default_language"), default_audio_language=meta.get("default_language"),
        notify_subscribers=bool(pub.get("notify_subscribers", True)), idempotency_key=f"wonderland:{ep['id']}",
        contains_synthetic_media=disclosure.get("contains_synthetic_media") if isinstance(disclosure.get("contains_synthetic_media"), bool) else None,
    )


def _gatekeep(studio, ep: dict) -> None:
    mode = studio.publish_mode
    if ep["status"] in ("uploaded", "scheduled", "published"):
        return
    if ep["status"] != "produced":
        raise PermanentError(f"episode is '{ep['status']}', not produced; it did not pass the compliance gate")
    if mode == "off":
        raise BlockedError("publishing.mode is off", needs="owner sets publishing.mode to review or auto in config/studio.yaml")
    if mode == "review":
        if not ep["approved"]:
            raise BlockedError(f"{ep['id']} is waiting for review", needs=f"owner watches {ep['video_path']} then runs: python -m wonderland approve {ep['id']}")
        if ep.get("approved_sha256") != ep.get("video_sha256"):
            raise BlockedError("the video changed after it was approved", needs=f"owner re-approves {ep['id']}")
    first = studio.db.one("SELECT id FROM episodes WHERE video_id IS NOT NULL AND verified_at IS NULL AND id != ? ORDER BY uploaded_at LIMIT 1", (ep["id"],))
    ever_verified = studio.db.scalar("SELECT COUNT(*) FROM episodes WHERE verified_at IS NOT NULL")
    if first and not ever_verified:
        raise BlockedError(f"the first (test) upload {first['id']} has not been verified on YouTube yet",
                           needs="wait for the test upload to be verified (python -m wonderland run-cycle), then uploads continue")


def _playlist(studio, client, title: str) -> str | None:
    cache = studio.db.get("playlists", {}) or {}
    if title in cache:
        return cache[title]
    for p in client.list_playlists():
        cache[p["snippet"]["title"]] = p["id"]
    if title not in cache:
        made = client.create_playlist(title, f"{title} — short original cartoons from {studio.universe['brand']['universe']}.", "public")
        cache[title] = made["id"]
    studio.db.set("playlists", cache, studio.now())
    return cache[title]


def handle_publish(studio, task: dict, ep: dict) -> AgentReport:
    _gatekeep(studio, ep)
    if ep.get("video_id"):
        return AgentReport("publishing", task["key"], "success", output={"video_id": ep["video_id"], "note": "already uploaded"},
                           evidence=[f"https://youtu.be/{ep['video_id']}"], next_action="verify")
    _, uploader, exc, locked = toolkit(studio) if not getattr(studio, "youtube_factory", None) else (None, _uploader_module(studio), None, lambda: False)
    if locked():
        raise BlockedError("the YouTube toolkit safety lock is on (YOUTUBE_DRY_RUN=true)", needs="owner sets YOUTUBE_DRY_RUN=false in youtube-automation-os/.env")
    now = studio.now()
    lead = timedelta(minutes=int(studio.cfg.get("publishing", {}).get("lead_minutes", 20)))
    if parse_iso(ep["publish_at"]) <= now + lead:
        studio.db.update_episode(ep["id"], now, status="skipped", error="publishing slot passed before the upload could start")
        return AgentReport("publishing", task["key"], "skipped", errors=["slot time passed"], next_action="none; the episode is kept, not uploaded late")
    client, rt = make_client(studio, UPLOAD_OPS)
    spec = _spec(uploader, ep, studio)
    v = uploader.validate_spec(spec)
    if not v.ok:
        raise PermanentError("upload spec invalid: " + "; ".join(map(str, v.errors))[:500])
    store = rt.store
    sha = ep["video_sha256"]
    previous = store.find_upload(sha)
    if previous:
        video_id = previous["video_id"]               # crash after upload, before we recorded it: never upload twice
    else:
        try:
            _, video = uploader.run_upload(client, store, spec, chunk_size=8 * 1024 * 1024)
        except Exception as e:  # noqa: BLE001
            name = type(e).__name__
            if name in ("QuotaExceededError",):
                raise TransientError(f"YouTube quota exhausted for today: {e}") from e
            if name in ("UploadUncertainError",):
                raise BlockedError(f"upload state uncertain: {e}", needs="owner checks YouTube Studio → Content") from e
            if name in ("AuthError", "ScopeError"):
                raise BlockedError(str(e), needs="owner re-runs authenticate.py with --scopes upload,manage,analytics") from e
            raise
        video_id = video["id"]
    studio.db.update_episode(ep["id"], studio.now(), video_id=video_id, uploaded_at=studio.now(), status="uploaded", scheduled_for=ep["publish_at"])
    evidence = [f"https://youtu.be/{video_id}", {"sha256": sha}, {"publishAt": ep["publish_at"]}]
    if studio.cfg.get("publishing", {}).get("add_to_playlists", True):
        try:
            pclient, _ = make_client(studio, PLAYLIST_OPS)
            pid = _playlist(studio, pclient, ep["metadata"]["playlist"])
            pclient.add_to_playlist(pid, video_id)
            evidence.append({"playlist": pid})
        except Exception as e:  # noqa: BLE001 - a playlist problem must not undo a good upload
            studio.db.log("warning", "publishing", f"{ep['id']}: playlist step failed: {e}", studio.now())
    return AgentReport("publishing", task["key"], "success",
                       output={"video_id": video_id, "privacy": "private", "publish_at": ep["publish_at"], "reused_previous_upload": bool(previous)},
                       evidence=evidence, next_action="verify")


def _uploader_module(studio):
    return getattr(studio, "uploader_module", None) or toolkit(studio)[1]


def handle_verify(studio, task: dict, ep: dict) -> AgentReport:
    if not ep or not ep.get("video_id"):
        raise PermanentError("no video id to verify")
    uploader = _uploader_module(studio)
    client, _ = make_client(studio, ["videos.list"])
    result = uploader.verify_video(client, ep["video_id"], _spec(uploader, ep, studio))
    now = studio.now()
    if not result["exists"]:
        studio.db.update_episode(ep["id"], now, status="failed", error="video not found on YouTube after upload", youtube_status="missing")
        raise PermanentError("the uploaded video is not on the channel")
    video = client.get_video(ep["video_id"], parts="status")
    status = (video or {}).get("status", {})
    privacy = status.get("privacyStatus")
    publish_at = parse_iso(ep["publish_at"])
    rejected = status.get("uploadStatus") in ("rejected", "failed")
    studio.db.update_episode(ep["id"], now, youtube_status=f"{status.get('uploadStatus')}/{privacy}")
    if rejected:
        studio.db.update_episode(ep["id"], now, status="failed", error=f"YouTube {status.get('uploadStatus')}: {status.get('rejectionReason') or status.get('failureReason')}")
        raise PermanentError(f"YouTube {status.get('uploadStatus')} the video")
    if privacy == "public":
        studio.db.update_episode(ep["id"], now, status="published", published_at=now, verified_at=now)
        return AgentReport("publishing", task["key"], "success", output={"status": "published", "checks": result["checks"]},
                           evidence=[result["url"], {"privacyStatus": privacy}], next_action="analytics")
    if not result["ok"]:
        raise PermanentError("YouTube does not match what was sent: " + "; ".join(f"{c['name']}={c['actual']}" for c in result["checks"] if not c["ok"]))
    if not ep.get("verified_at"):
        studio.db.update_episode(ep["id"], now, status="scheduled", verified_at=now)
    if now < publish_at:
        recheck = publish_at + timedelta(minutes=10)
    elif now < publish_at + timedelta(hours=6):
        recheck = now + timedelta(minutes=30)
    else:
        raise PermanentError(f"still {privacy} six hours after the scheduled time")
    return AgentReport("publishing", task["key"], "success", output={"status": "scheduled", "privacy": privacy, "checks": result["checks"]},
                       evidence=[result["url"], {"privacyStatus": privacy}, {"publishAt": ep["publish_at"]}], next_action=f"recheck:{iso(recheck)}")
