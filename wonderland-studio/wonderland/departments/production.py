"""The production departments as queue workers.

Each handler takes one task for one episode, does that department's stage of the pipeline,
writes what it produced into the episode ledger and returns an ``AgentReport`` whose evidence
is the real files and numbers. Handlers are idempotent: running one twice gives the same
files, so the CEO can retry after a crash without checking what was half-done.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from .. import pipeline
from ..protocol import AgentReport, BlockedError, PermanentError, QualityError
from . import story as story_dept


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _need_story(ep: dict) -> dict:
    if not ep or not ep.get("story"):
        raise PermanentError("episode has no story yet")
    return ep["story"]


def _merge_production(studio, ep: dict, key: str, value) -> None:
    prod = dict(studio.db.episode(ep["id"]).get("production") or {})
    prod[key] = value
    studio.db.update_episode(ep["id"], studio.now(), production=prod)


def _prepared(studio, ep: dict):
    return pipeline.prepare(_need_story(ep), studio.universe, studio.cfg, studio.desk, salt=f"{ep['id']}:{ep['attempt']}")


def handle_script(studio, task: dict, ep: dict) -> AgentReport:
    slot = next((s for s in studio.slots() if int(s["id"]) == int(ep["slot"])), None)
    if slot is None:
        raise PermanentError(f"slot {ep['slot']} is not defined in studio.yaml")
    history = studio.db.story_history(exclude=ep["id"])
    same_day = [h for h in history if h["day"] == ep["day"]]
    brief = studio.db.get("research_brief", {}) or {}
    weights = dict(studio.db.get("story_weights", {}) or {})
    for fmt, boost in (brief.get("format_boosts") or {}).items():
        weights[fmt] = round(weights.get(fmt, 1.0) * float(boost), 4)
    engine = story_dept.StoryEngine(studio.universe, studio.cfg.get("story"))
    try:
        story, report = engine.generate(list(slot["categories"]), f"{ep['id']}:{ep['attempt']}", history, same_day, weights or None)
    except RuntimeError as exc:
        studio.notify("warning", f"No new story for {ep['id']}", f"Slot left empty instead of repeating an old video. {str(exc)[:400]}",
                      fingerprint=f"nostory:{ep['slot']}")
        return AgentReport("story", task["key"], "skipped", errors=[str(exc)[:600]],
                           next_action="slot left empty; add story formats or an LLM story provider to extend the runway")
    data = story.as_dict()
    studio.db.update_episode(ep["id"], studio.now(), story=data, story_report=report, signature=report["signature"], script=story.script(),
                             title=story.title, category=story.category, format=story.format, cast=story.cast, error=None)
    return AgentReport("story", task["key"], "success",
                       output={"title": story.title, "category": story.category, "format": story.format, "lines": len(story.beats),
                               "scores": report["scores"], "candidates_considered": report["candidates_considered"], "attempt": ep["attempt"]},
                       evidence=[{"signature": report["signature"]}, {"compliance": report["compliance"]["ok"]},
                                 {"rejected_drafts": len(report["rejected"])}],
                       next_action="storyboard")


def handle_storyboard(studio, task: dict, ep: dict) -> AgentReport:
    from .. import finance

    story = _need_story(ep)
    provider = studio.desk.active()
    chars = sum(len(b["text"]) for b in story["beats"])
    if provider.cost_per_char > 0:
        finance.require_budget(studio, chars * provider.cost_per_char, f"{provider.name} voice for {ep['id']}")
    prep = _prepared(studio, ep)
    out = pipeline.stage_storyboard(studio.episode_dir(ep["id"]), prep)
    if out["voice_cost_usd"] > 0:
        studio.db.add_cost(studio.now(), ep["day"], "voice", ",".join(out["voice_providers"]), out["voice_cost_usd"], units=out["voice_chars"],
                           unit="chars", episode_id=ep["id"], note="text-to-speech")
    _merge_production(studio, ep, "storyboard", out)
    studio.db.update_episode(ep["id"], studio.now(), dir=str(studio.episode_dir(ep["id"])), duration=prep.timing["total_seconds"])
    return AgentReport("storyboard", task["key"], "success", output=out,
                       evidence=[str(studio.episode_dir(ep["id"]) / "storyboard.json")], next_action="animation")


def handle_animation(studio, task: dict, ep: dict) -> AgentReport:
    d = studio.episode_dir(ep["id"])
    out = pipeline.stage_animation(d, _prepared(studio, ep), studio.universe, studio.cfg)
    _merge_production(studio, ep, "animation", out)
    return AgentReport("animation", task["key"], "success", output=out, evidence=[str(d / "silent.mp4")], next_action="sound")


def handle_sound(studio, task: dict, ep: dict) -> AgentReport:
    d = studio.episode_dir(ep["id"])
    out = pipeline.stage_sound(d, _prepared(studio, ep), _need_story(ep), studio.universe, studio.cfg)
    studio.db.add_licences(ep["id"], out["licences"], studio.now())
    _merge_production(studio, ep, "sound", {k: v for k, v in out.items() if k != "licences"})
    return AgentReport("audio", task["key"], "success", output={k: v for k, v in out.items() if k != "licences"},
                       evidence=[str(d / "sound.wav"), {"licence_entries": len(out["licences"])}], next_action="edit")


def handle_edit(studio, task: dict, ep: dict) -> AgentReport:
    d = studio.episode_dir(ep["id"])
    for needed in ("silent.mp4", "sound.wav"):
        if not (d / needed).is_file():
            raise PermanentError(f"{needed} is missing; the earlier stage did not finish")
    out = pipeline.stage_edit(d, _prepared(studio, ep), studio.cfg)
    final = d / "final.mp4"
    sha = _sha256(final)
    _merge_production(studio, ep, "edit", out)
    studio.db.update_episode(ep["id"], studio.now(), video_path=str(final), video_sha256=sha, approved=False, approved_sha256=None)
    return AgentReport("editing", task["key"], "success", output={**out, "bytes": final.stat().st_size, "sha256": sha},
                       evidence=[str(final), str(d / "final.srt"), str(d / "sheet.png"), str(d / "cover.png")], next_action="qa")


def handle_qa(studio, task: dict, ep: dict) -> AgentReport:
    d = studio.episode_dir(ep["id"])
    report = pipeline.stage_qa(d, _prepared(studio, ep), studio.cfg)
    studio.db.update_episode(ep["id"], studio.now(), qa=report, duration=report["metrics"].get("duration"))
    if not report["ok"]:
        failed = report["failed"] + ([] if report["sync"]["ok"] else ["lip_sync"]) + ([] if report["cover_ok"] else ["cover_frame"])
        raise QualityError("technical quality control failed: " + ", ".join(failed))
    return AgentReport("quality", task["key"], "success",
                       output={"checks": len(report["checks"]), "metrics": report["metrics"], "sync": report["sync"]},
                       evidence=[str(d / "qa.json"), str(d / "sheet.png")], next_action="seo")


__all__ = ["handle_script", "handle_storyboard", "handle_animation", "handle_sound", "handle_edit", "handle_qa", "BlockedError"]
