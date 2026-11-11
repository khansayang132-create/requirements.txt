"""The production line: one approved story → one finished, quality-checked episode.

Every stage is a function of files in the episode folder, so a stage can be re-run after a
crash without redoing the ones before it, and two runs of the same story give the same film.

    story.json ─ voice ─ storyboard ─ animation ─ sound ─ edit ─ qa
                  │          │           │          │       │     └ qa.json
                  │          │           │          │       └ final.mp4 · final.srt · cover.png · sheet.png
                  │          │           │          └ sound.wav (+ foley.json when the Foley pass runs)
                  │          │           └ silent.mp4
                  │          └ storyboard.json (shots with real timings)
                  └ cached voice clips (state/voice/<provider>/…)

``prepare`` rebuilds the timed shots from the story and the cached voice clips; it is cheap and
deterministic, which is why later stages call it instead of loading pickled objects.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

from .audio import synth
from .audio.tts import VoiceDesk
from .departments import animation, editing, qa, storyboard
from .departments import audio as audio_dept

STAGES = ("voice", "storyboard", "animation", "sound", "edit", "qa")


@dataclass
class Prepared:
    shots: list
    voices: list[dict]
    timing: dict
    seed: int
    fps: int


def episode_seed(story: dict, salt: str = "") -> int:
    text = salt + "|" + story.get("title", "") + "|" + " ".join(b["text"] for b in story["beats"])
    return int(hashlib.sha1(text.encode()).hexdigest()[:8], 16)


def make_desk(cfg: dict, state: Path) -> VoiceDesk:
    a = cfg.get("audio", {})
    return VoiceDesk(a.get("voice_providers", ["kokoro", "espeak"]), Path(state) / "voice", Path(state) / "models",
                     paid_authorized=bool(cfg.get("budget", {}).get("paid_providers_authorized", False)))


def prepare(story: dict, universe: dict, cfg: dict, desk: VoiceDesk, salt: str = "") -> Prepared:
    """Record (or load cached) voices, build the shots and give them their real durations."""
    v = cfg["video"]
    fps = int(v.get("fps", 24))
    seed = episode_seed(story, salt)
    voices = audio_dept.record_voices(story, universe, desk)
    shots = storyboard.build_shots(story)
    mood = story.get("mood", "bright")
    bar = synth.tempo_for(seed, mood)[1] if story.get("song") else None
    timing = storyboard.time_shots(shots, voices, fps, mood, float(v.get("min_seconds", 20)) + 1.0, float(v.get("max_seconds", 60)) - 1.5, bar)
    audio_dept.attach_voices(shots, voices, fps)
    return Prepared(shots=shots, voices=voices, timing=timing, seed=seed, fps=fps)


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    tmp.replace(path)


def stage_storyboard(ep: Path, prep: Prepared) -> dict:
    _write(ep / "storyboard.json", {"timing": prep.timing, "shots": storyboard.shots_to_json(prep.shots)})
    providers = sorted({v["provider"] for v in prep.voices})
    return {"timing": prep.timing, "voice_providers": providers, "voice_lines": len(prep.voices),
            "voice_cost_usd": round(sum(v["cost_usd"] for v in prep.voices), 6), "voice_chars": sum(v["chars"] for v in prep.voices)}


def stage_animation(ep: Path, prep: Prepared, universe: dict, cfg: dict) -> dict:
    v = cfg["video"]
    return animation.render_video(prep.shots, universe, ep / "silent.mp4", ep / "work", width=int(v["width"]), height=int(v["height"]),
                                  fps=prep.fps, crf=int(v.get("crf", 19)), preset=v.get("preset", "medium"),
                                  workers=v.get("workers"), backend=v.get("backend", "auto"))


def stage_sound(ep: Path, prep: Prepared, story: dict, universe: dict, cfg: dict) -> dict:
    return audio_dept.build_soundtrack(prep.shots, prep.voices, story, prep.seed, ep / "sound.wav", music=bool(cfg.get("audio", {}).get("music", True)),
                                       universe=universe, fps=prep.fps, report_path=ep / "foley.json")


def stage_edit(ep: Path, prep: Prepared, cfg: dict) -> dict:
    lufs = float(cfg.get("audio", {}).get("loudness_lufs", -14))
    editing.mux(ep / "silent.mp4", ep / "sound.wav", ep / "final.mp4", loudness=lufs)
    editing.write_srt(prep.shots, ep / "final.srt")
    sheet = editing.contact_sheet(ep / "final.mp4", prep.shots, ep / "sheet.png")
    cover = editing.cover_frame(ep / "final.mp4", prep.shots, ep / "cover.png")
    return {"video": str(ep / "final.mp4"), "captions": str(ep / "final.srt"), "contact_sheet": sheet, "cover": cover}


def stage_qa(ep: Path, prep: Prepared, cfg: dict) -> dict:
    v = cfg["video"]
    report = qa.technical_qa(ep / "final.mp4", width=int(v["width"]), height=int(v["height"]), fps=prep.fps,
                             min_seconds=float(v.get("min_seconds", 20)), max_seconds=float(v.get("max_seconds", 60)),
                             loudness=float(cfg.get("audio", {}).get("loudness_lufs", -14)))
    report["sync"] = qa.sync_report(prep.shots, prep.fps)
    report["cover_ok"] = qa.image_ok(ep / "cover.png")
    report["ok"] = bool(report["ok"] and report["sync"]["ok"] and report["cover_ok"])
    _write(ep / "qa.json", report)
    return report


def produce(story: dict, universe: dict, cfg: dict, ep: Path, desk: VoiceDesk | None = None, salt: str = "", log=None) -> dict:
    """Run every stage for one story. Returns the full production report (also written to ``episode.json``)."""
    ep = Path(ep)
    ep.mkdir(parents=True, exist_ok=True)
    say = log or (lambda *_: None)
    desk = desk or make_desk(cfg, ep.parent)
    _write(ep / "story.json", story)
    t0 = time.time()
    prep = prepare(story, universe, cfg, desk, salt)
    report: dict = {"title": story["title"], "seed": prep.seed, "storyboard": stage_storyboard(ep, prep)}
    say(f"storyboard: {prep.timing['shots']} shots, {prep.timing['total_seconds']}s")
    report["animation"] = stage_animation(ep, prep, universe, cfg)
    say(f"animation: {report['animation']['frames']} frames in {report['animation']['render_seconds']}s")
    report["sound"] = stage_sound(ep, prep, story, universe, cfg)
    report["edit"] = stage_edit(ep, prep, cfg)
    report["qa"] = stage_qa(ep, prep, cfg)
    report["seconds_total"] = round(time.time() - t0, 1)
    say(f"qa: {'PASS' if report['qa']['ok'] else 'FAIL ' + str(report['qa']['failed'])} in {report['seconds_total']}s")
    _write(ep / "episode.json", report)
    return report
