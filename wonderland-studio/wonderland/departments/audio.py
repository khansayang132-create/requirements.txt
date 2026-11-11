"""Audio department: voices, original music, sound effects, the final mix, and the
licence ledger entries that prove where every sound came from.

Order of work (the picture depends on the voice, so voice comes first):
1. ``record_voices``  one clip per line, in the speaker's voice profile (cached);
2. the storyboard times the shots from those clips;
3. ``attach_voices``  gives each shot its clip and its lip-sync envelope;
4. ``build_soundtrack``  composes the tune, places the effects and mixes everything.
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

from ..audio import synth
from ..audio.tts import SR, VoiceDesk, loudness_envelope, read_wav
from ..render.stage import Shot, Voice


def voice_profiles(universe: dict) -> dict[str, dict]:
    out = {"narrator": universe["narrator"]["voice"]}
    for c in universe["characters"]:
        out[c["id"]] = c["voice"]
    return out


def record_voices(story: dict, universe: dict, desk: VoiceDesk) -> list[dict]:
    profiles = voice_profiles(universe)
    clips = []
    for beat in story["beats"]:
        clip = desk.speak(beat["text"], profiles.get(beat["speaker"], profiles["narrator"]))
        clip["speaker"] = beat["speaker"]
        clip["text"] = beat["text"]
        clips.append(clip)
    return clips


def attach_voices(shots: list[Shot], voices: list[dict], fps: int) -> None:
    for shot, v in zip(shots, voices):
        x, _ = read_wav(Path(v["path"]))
        shot.voice = Voice(path=v["path"], start=v["start"], duration=v["duration"], envelope=loudness_envelope(x, fps))


def build_soundtrack(shots: list[Shot], voices: list[dict], story: dict, seed: int, out_wav: Path, music: bool = True, *,
                     universe: dict | None = None, fps: int = 24, report_path: Path | None = None) -> dict:
    total = sum(s.duration for s in shots)
    placed = []
    for v in voices:
        x, _ = read_wav(Path(v["path"]))
        placed.append((v["shot_start"] + v["start"], x))
    events = []
    t = 0.0
    for s in shots:
        for e in s.sfx:
            events.append((t + float(e.get("at", 0.2)), e["name"]))
        t += s.duration
    tune, info = (None, {"origin": "no music"})
    if music:
        tune, info = synth.compose(seed, total, story.get("mood", "bright"))
    mix = synth.mix_episode(total, placed, tune, events)
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(mix, -1, 1) * 32767).astype("<i2")
    stereo = np.repeat(pcm[:, None], 2, axis=1)
    with wave.open(str(out_wav), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(stereo.tobytes())
    providers = sorted({v["provider"] for v in voices})
    licences = [
        {"kind": "music", "name": f"episode score ({info.get('mood', '-')}, {info.get('tempo_bpm', '-')} bpm)", "origin": info["origin"],
         "license": "original work of this studio; no third-party material", "evidence": f"seed={info.get('seed')}"},
        {"kind": "sfx", "name": ", ".join(sorted({n for _, n in events})) or "none", "origin": "synthesized in-house (wonderland.audio.synth)",
         "license": "original work of this studio; no third-party material", "evidence": f"{len(events)} events"},
    ]
    for p in providers:
        lic = next(v["license"] for v in voices if v["provider"] == p)
        licences.append({"kind": "voice", "name": f"text-to-speech: {p}", "origin": f"synthesized speech ({p})", "license": lic,
                         "evidence": f"{sum(1 for v in voices if v['provider'] == p)} lines"})
    return {"path": str(out_wav), "seconds": round(total, 3), "music": info, "sfx_events": len(events), "voice_providers": providers,
            "voice_cost_usd": round(sum(v["cost_usd"] for v in voices), 6), "voice_chars": sum(v["chars"] for v in voices),
            "peak": round(float(np.max(np.abs(mix))), 3), "licences": licences}
