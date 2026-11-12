"""Compliance gate: the last check before an episode may leave the studio.

Nothing is uploaded unless every item here passes:

* the script passes the child-safety review again (the same rules as at writing time);
* the title, description and tags pass the metadata review (no stuffing, nothing misleading);
* technical quality control passed and the file is the one that was checked;
* every sound in the episode has a licence entry;
* the audience setting is "made for kids" — this channel's content is directed at children,
  and declaring otherwise would misstate it;
* the altered/synthetic-content decision is recorded with its reason.

Passing the gate marks the episode ``produced``. Publishing is a separate decision.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from ..protocol import AgentReport, PermanentError, QualityError
from ..render.environments import ENVS
from ..render.props import PROPS
from . import compliance

REQUIRED_LICENCE_KINDS = ("music", "sfx", "voice")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def review(studio, ep: dict) -> dict:
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "passed": bool(ok), "detail": detail})

    story, meta, qa = ep.get("story") or {}, ep.get("metadata") or {}, ep.get("qa") or {}
    chars = {c["id"] for c in studio.universe["characters"]}
    sv = compliance.review_story(story, set(PROPS), chars, set(ENVS)) if story else {"ok": False, "errors": ["no story"], "warnings": []}
    check("script_child_safety", sv["ok"], "passed" if sv["ok"] else "; ".join(sv["errors"][:3]))
    mv = compliance.review_metadata(meta) if meta else {"ok": False, "errors": ["no metadata"]}
    check("metadata_honest", mv["ok"], "passed" if mv["ok"] else "; ".join(mv["errors"][:3]))
    check("technical_qc", bool(qa.get("ok")), "passed" if qa.get("ok") else f"failed: {qa.get('failed')}")

    video = Path(ep["video_path"]) if ep.get("video_path") else None
    exists = bool(video and video.is_file())
    check("video_file_present", exists, str(video) if exists else "final video is missing")
    same = exists and _sha256(video) == ep.get("video_sha256")
    check("video_is_the_checked_file", same, "sha256 matches the file that passed quality control" if same else "file changed after quality control")
    srt = Path(ep["dir"]) / "final.srt" if ep.get("dir") else None
    check("captions_present", bool(srt and srt.is_file() and srt.stat().st_size > 0), str(srt))

    lic = studio.db.q("SELECT kind, license FROM licences WHERE episode_id=?", (ep["id"],))
    kinds = {r["kind"] for r in lic}
    missing = [k for k in REQUIRED_LICENCE_KINDS if k not in kinds]
    check("licence_ledger_complete", not missing and all(r["license"] for r in lic),
          f"{len(lic)} entries" if not missing else f"missing: {', '.join(missing)}")

    mfk = bool(studio.cfg.get("publishing", {}).get("made_for_kids", True)) and bool(meta.get("made_for_kids", True))
    check("audience_made_for_kids", mfk, sv.get("made_for_kids_reason", "") if mfk else "publishing.made_for_kids must be true for this channel")
    providers = ((ep.get("production") or {}).get("storyboard") or {}).get("voice_providers") or []
    disclosure = compliance.disclosure_decision(studio.cfg, ", ".join(providers) or "unknown")
    max_s = float(studio.cfg["video"].get("max_seconds", 60))
    dur = float(ep.get("duration") or 0)
    check("shorts_length", 0 < dur <= max_s, f"{dur:.1f}s (limit {max_s:g}s)")
    return {"ok": all(c["passed"] for c in checks), "checks": checks, "warnings": sv.get("warnings", []), "made_for_kids": mfk,
            "made_for_kids_reason": sv.get("made_for_kids_reason", ""), "disclosure": disclosure,
            "failed": [c["name"] for c in checks if not c["passed"]]}


def handle_compliance(studio, task: dict, ep: dict) -> AgentReport:
    result = review(studio, ep)
    studio.db.update_episode(ep["id"], studio.now(), compliance=result)
    if not result["ok"]:
        detail = "; ".join(f"{c['name']}: {c['detail']}" for c in result["checks"] if not c["passed"])
        if "script_child_safety" in result["failed"] or "technical_qc" in result["failed"]:
            raise QualityError("compliance gate: " + detail)
        raise PermanentError("compliance gate: " + detail)
    studio.db.update_episode(ep["id"], studio.now(), status="produced", error=None)
    mode = studio.publish_mode
    nxt = {"off": "publishing is off: the episode is kept for review",
           "review": f"waiting for the owner's approval: python -m wonderland approve {ep['id']}",
           "auto": "publish"}[mode]
    return AgentReport("compliance", task["key"], "success",
                       output={"checks": len(result["checks"]), "made_for_kids": result["made_for_kids"], "disclosure": result["disclosure"],
                               "warnings": result["warnings"]},
                       evidence=[{c["name"]: c["detail"]} for c in result["checks"]], next_action=nxt)
