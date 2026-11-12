"""Audio department: voices, original music, sound effects, the final mix, and the
licence ledger entries that prove where every sound came from.

Order of work (the picture depends on the voice, so voice comes first):
1. ``record_voices``  one clip per line, in the speaker's voice profile (cached);
2. the storyboard times the shots from those clips;
3. ``attach_voices``  gives each shot its clip and its lip-sync envelope;
4. ``build_soundtrack``  composes the tune, spots the Foley from the animation (``audio.foley``),
   lays the ambience bed per location, adds title/end stings, mixes five buses to 48 kHz stereo,
   masters to the loudness target and writes ``foley.json`` with the evidence.
"""

from __future__ import annotations

import json
import math
import time
import wave
from pathlib import Path

import numpy as np

from ..audio import foley, synth
from ..audio.tts import VoiceDesk, loudness_envelope, read_wav
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


def _write_wav24(path: Path, stereo: np.ndarray, sr: int) -> None:
    """(2, n) float -> 24-bit PCM stereo WAV (TPDF dither at 24-bit is inaudible; it just avoids truncation)."""
    rng = np.random.default_rng(0)
    x = np.clip(stereo.T, -1, 1) * 8388607.0
    x = np.round(x + (rng.random(x.shape) - rng.random(x.shape))).clip(-8388608, 8388607).astype("<i4")
    raw = x.reshape(-1).view(np.uint8).reshape(-1, 4)[:, :3].tobytes()
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(3)
        w.setframerate(sr)
        w.writeframes(raw)


def _ratio_db(a: np.ndarray, b: np.ndarray) -> float | None:
    ea, eb = float(np.sum(a.astype(np.float64) ** 2)), float(np.sum(b.astype(np.float64) ** 2))
    return round(10 * math.log10(ea / eb), 2) if ea > 0 and eb > 0 else None


def mix_metrics(res: dict, events: list[dict], duration: float) -> dict:
    """The numbers that stand in for listening: per-bus levels, voice-to-bed, spectrum, crest, side-chain proof."""
    st = res["stems"]
    g = float(10 ** (res["master_gain_db"] / 20))
    mono = {k: (v[0] + v[1]) * math.sqrt(0.5) * g for k, v in st.items()}
    bed = mono["music"] + mono["ambience"] + mono["foley"] + mono["sfx"]
    out = {"buses": {k: synth.analyse(v * g) for k, v in st.items()}, "mix": synth.analyse(res["mix"])}
    speech = res["gains"]["speech"] > 0.5
    blk = int(0.4 * synth.SR)
    worst = []
    if speech.any():
        out["voice_to_bed_db"] = _ratio_db(mono["voice"][speech], bed[speech])
        cand = [i for i in range(0, len(speech) - blk, blk // 2) if speech[i:i + blk].all()]   # 400 ms blocks inside speech
        lv = [float(np.sqrt(np.mean(mono["voice"][i:i + blk] ** 2))) for i in cand]
        ref = float(np.median(lv)) if lv else 0.0
        for i, v in zip(cand, lv):
            if v >= 0.4 * ref:                                 # words actually sounding (not the breath between them)
                r = _ratio_db(mono["voice"][i:i + blk], bed[i:i + blk])
                if r is not None:
                    worst.append(r)
    out["voice_to_bed_db_p10_400ms"] = round(float(np.percentile(worst, 10)), 2) if worst else None
    out["voice_to_bed_db_min_400ms"] = round(min(worst), 2) if worst else None
    gm = res["gains"]["music"]
    side = res["gains"]["fx_sidechain"]
    quiet = res["gains"]["speech"] < 0.05
    pk = (side > 0.9) & quiet
    out["music_sidechain"] = {
        "music_gain_db_at_fx_peaks_median": round(float(np.median(20 * np.log10(gm[pk]))), 2) if pk.any() else None,
        "music_gain_db_without_fx_or_voice_median": round(float(np.median(20 * np.log10(gm[quiet & (side < 0.05)]))), 2)
        if (quiet & (side < 0.05)).any() else None,
        "music_gain_db_under_voice_median": round(float(np.median(20 * np.log10(gm[speech])))) if speech.any() else None}
    out["events"] = foley.density(events, duration)
    out["events"]["foley"] = sum(1 for e in events if e["layer"] == "foley")
    out["events"]["sfx"] = sum(1 for e in events if e["layer"] == "sfx")
    kinds: dict[str, int] = {}
    for e in events:
        kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
    out["events"]["by_kind"] = dict(sorted(kinds.items()))
    out["master_gain_db"], out["limiter_db"] = res["master_gain_db"], res["limiter_db"]
    return out


def build_soundtrack(shots: list[Shot], voices: list[dict], story: dict, seed: int, out_wav: Path, music: bool = True, *,
                     universe: dict | None = None, fps: int = 24, report_path: Path | None = None) -> dict:
    """Compose, spot, lay, mix and master the episode's sound. Writes ``out_wav`` (48 kHz, stereo, 24-bit PCM)
    and, when ``report_path`` is given, the Foley/mix evidence (foley.json)."""
    t_start = time.time()
    SR = synth.SR
    total = sum(s.duration for s in shots)
    placed = []
    for v in voices:
        x, sr = read_wav(Path(v["path"]))
        placed.append((v["shot_start"] + v["start"], synth.resample(x, sr, SR)))
    events, stats = foley.spot(shots, universe, fps)
    starts, t = [], 0.0
    for s in shots:
        starts.append(t)
        t += s.duration
    tune, info = (None, {"origin": "no music"})
    stings = []
    if music:
        tune, info = synth.compose(seed, total, story.get("mood", "bright"))
        for i, s in enumerate(shots):
            style = s.overlay.style if s.overlay else None
            if style in ("title", "end"):
                stings.append({"t": round(starts[i] + 0.05, 3), "kind": style, "timecode": foley.timecode(starts[i] + 0.05, fps)})
    segs = [(starts[i], starts[i] + s.duration, s.env) for i, s in enumerate(shots)]
    amb = synth.ambience_track(segs, total, seed)
    res = synth.mix_layers(total, placed, tune, sfx=[e for e in events if e["layer"] == "sfx"],
                           foley=[e for e in events if e["layer"] == "foley"], ambience=amb,
                           stings=[(st["t"], synth.sting(int(info["key_root_midi"]), st["kind"])) for st in stings])
    mix = res["mix"]
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    _write_wav24(out_wav, mix, SR)
    metrics = mix_metrics(res, events, total)

    ambience = []
    for i, s in enumerate(shots):
        ambience.append({"shot": i, "start": round(starts[i], 3), "timecode": foley.timecode(starts[i], fps), "env": s.env,
                         "bed": synth.AMBIENCE.get(s.env, synth.AMBIENCE["playroom"])[0],
                         "crossfade_in": bool(i and shots[i - 1].env != s.env)})
    providers = sorted({v["provider"] for v in voices})
    origin = "original work of this studio; no third-party material"
    sfx_names = sorted({e["name"] for e in events if e["layer"] == "sfx"})
    licences = [
        {"kind": "music", "name": f"episode score ({info.get('mood', '-')}, {info.get('tempo_bpm', '-')} bpm)"
         + (f" + {len(stings)} sting(s)" if stings else ""), "origin": info["origin"], "license": origin, "evidence": f"seed={info.get('seed')}"},
        {"kind": "sfx", "name": ", ".join(sfx_names) or "none", "origin": "synthesized in-house (wonderland.audio.synth)",
         "license": origin, "evidence": f"{metrics['events']['sfx']} events"},
        {"kind": "foley", "name": ", ".join(sorted({e["sound"] for e in events if e["layer"] == "foley"})) or "none",
         "origin": "synthesized in-house from filtered noise and sine bodies (wonderland.audio.synth FOLEY), timed from the "
                   "animation poses (wonderland.audio.foley)", "license": origin, "evidence": f"{metrics['events']['foley']} events"},
        {"kind": "ambience", "name": ", ".join(sorted({s.env for s in shots})),
         "origin": "synthesized in-house (wonderland.audio.synth.ambience_loop)", "license": origin, "evidence": f"seed={seed}"},
    ]
    for p in providers:
        lic = next(v["license"] for v in voices if v["provider"] == p)
        licences.append({"kind": "voice", "name": f"text-to-speech: {p}", "origin": f"synthesized speech ({p})", "license": lic,
                         "evidence": f"{sum(1 for v in voices if v['provider'] == p)} lines"})
    buses = {k: {"gain": synth.BUS_GAIN[k], **metrics["buses"][k]} for k in synth.BUS_GAIN}
    report = {"path": str(out_wav), "seconds": round(total, 3), "music": info, "sfx_events": metrics["events"]["sfx"],
              "voice_providers": providers, "voice_cost_usd": round(sum(v["cost_usd"] for v in voices), 6),
              "voice_chars": sum(v["chars"] for v in voices), "peak": round(float(np.max(np.abs(mix))), 3), "licences": licences,
              "foley_events": metrics["events"]["foley"], "sample_rate": SR, "channels": 2, "bit_depth": 24,
              "ambience": ambience, "stings": stings, "buses": buses, "mix": metrics["mix"],
              "voice_to_bed_db": metrics.get("voice_to_bed_db"), "voice_to_bed_db_p10_400ms": metrics["voice_to_bed_db_p10_400ms"],
              "voice_to_bed_db_min_400ms": metrics["voice_to_bed_db_min_400ms"], "music_sidechain": metrics["music_sidechain"],
              "density": metrics["events"], "spotting": stats, "master_gain_db": metrics["master_gain_db"],
              "limiter_db": metrics["limiter_db"], "mix_settings": dict(synth.MIX), "build_seconds": round(time.time() - t_start, 2)}
    if report_path is not None:
        report_path = Path(report_path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        full = dict(report, fps=fps, events=events)
        tmp = report_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(full, indent=1, default=float), encoding="utf-8")
        tmp.replace(report_path)
        report["report"] = str(report_path)
    return report
