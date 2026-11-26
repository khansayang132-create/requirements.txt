"""The end-to-end workflow: script -> analysis -> enhancement -> directions -> per-sentence synthesis
with real engine controls -> profile voice conversion -> pauses and breaths -> mastering -> export.

Every output is checked with ffprobe after it is written, and the manifest records what each
stage actually did (including controls an engine does not support)."""
from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import replace
from pathlib import Path

import numpy as np

from . import audio as A
from .clone import convert
from .config import Settings
from .director import Direction, direct, map_to_engine, render_script
from .enhance import enhance
from .mastering import master
from .profiles import ProfileStore
from .script_judge import judge
from .tts import Prosody, TTSEngine, get_engine

SCENE_GAP_MS = 700
BREATH_MS = 280
VALID_EMOTIONS = {"neutral", "happiness", "sadness", "excitement", "confidence", "authority", "romance",
                  "professional", "documentary", "commercial"}


def apply_pronunciation(text: str, lexicon: dict[str, str] | None) -> str:
    for word, spoken in (lexicon or {}).items():
        if word.strip():
            text = re.sub(rf"(?<!\w){re.escape(word)}(?!\w)", spoken, text, flags=re.I)
    return text


def _voice_for(engine: TTSEngine, language: str, profile: dict | None, voice: str | None) -> str | None:
    if voice:
        return voice
    if engine.name != "espeak-ng":
        return None
    from .tts.espeak import LANG_VOICES
    variant = (profile or {}).get("base_variant", "m3")
    return f"{LANG_VOICES.get(language, 'en-us')}+{variant}"


CALIBRATION = {"en": "The quick brown fox jumps over the lazy dog while we read a calm and simple sentence aloud.",
               "id": "Pagi ini kami berjalan ke pasar untuk membeli buah, sayur, dan ikan segar bersama keluarga."}
_scale_cache: dict[tuple, float] = {}


def base_formant_scale(engine: TTSEngine, language: str, voice: str | None) -> float:
    key = (engine.name, language, voice)
    if key not in _scale_cache:
        from .analysis import formant_scale
        x, sr = engine.synthesize(CALIBRATION.get(language, CALIBRATION["en"]), language, Prosody(), voice)
        _scale_cache[key] = formant_scale(x, sr)
    return _scale_cache[key]


def synthesize_direction(d: Direction, engine: TTSEngine, profile: dict | None, controls: dict,
                         voice: str | None = None) -> tuple[np.ndarray, int, dict]:
    delivery = (profile or {}).get("voice", {}).get("delivery", {})
    p = d.prosody
    prosody = Prosody(
        rate=p.rate * controls.get("speed", 1.0) * delivery.get("rate", 1.0),
        pitch_semitones=p.pitch_semitones + controls.get("pitch", 0.0),
        pitch_range=p.pitch_range,
        volume_db=p.volume_db + controls.get("volume_db", 0.0) + delivery.get("volume_db", 0.0),
        emphasis=p.emphasis,
    )
    converting = profile is not None
    engine_prosody = replace(prosody, pitch_semitones=0.0, pitch_range=1.0) if converting else prosody
    text = apply_pronunciation(d.text, controls.get("pronunciation"))
    chunks = [text]
    if d.breath_after_word:
        ws = text.split()
        chunks = [" ".join(ws[:d.breath_after_word]), " ".join(ws[d.breath_after_word:])]
    v = _voice_for(engine, d.language, profile, voice)
    pieces, sr, conv_reports = [], None, []
    for i, chunk in enumerate(c for c in chunks if c.strip()):
        x, rate = engine.synthesize(chunk, d.language, engine_prosody, v)
        if converting:
            x, rate, rep = convert(x, rate, profile["voice"], prosody.pitch_semitones, prosody.pitch_range,
                                   source_scale=base_formant_scale(engine, d.language, v))
            conv_reports.append(rep)
        if not engine.capabilities.volume and prosody.volume_db:
            x = x * 10 ** (prosody.volume_db / 20)
        if sr is None:
            sr = rate
        elif rate != sr:
            x = A.resample(x, rate, sr)
        if i:
            pieces.append(A.silence(BREATH_MS * controls.get("pause_scale", 1.0) / 1000, sr))
        pieces.append(x)
    out = A.concat(pieces, sr)
    report = {
        "sentence": d.index, "text": d.text, "spoken_text": text, "tone": d.tone, "voice": v,
        "prosody": {"rate": round(prosody.rate, 3), "pitch_semitones": round(prosody.pitch_semitones, 2),
                    "pitch_range": round(prosody.pitch_range, 3), "volume_db": round(prosody.volume_db, 2),
                    "emphasis": prosody.emphasis},
        "applied_by": map_to_engine(d, engine.capabilities, converting),
        "conversion": conv_reports, "duration_s": round(out.size / sr, 3),
    }
    return out, sr, report


def render(directions: list[Direction], engine: TTSEngine, profile: dict | None, controls: dict,
           voice: str | None = None) -> tuple[np.ndarray, int, list[dict]]:
    pieces, reports, sr = [], [], None
    pause_scale = controls.get("pause_scale", 1.0)
    for i, d in enumerate(directions):
        x, rate, rep = synthesize_direction(d, engine, profile, controls, voice)
        if sr is None:
            sr = rate
        elif rate != sr:
            x = A.resample(x, rate, sr)
        pieces.append(x)
        nxt = directions[i + 1] if i + 1 < len(directions) else None
        gap = d.pause_after_ms
        if nxt is not None and nxt.scene != d.scene:
            gap = max(gap, SCENE_GAP_MS)
        if nxt is not None and gap:
            pieces.append(A.silence(gap * pause_scale / 1000, sr))
        reports.append(rep)
    return A.concat(pieces, sr), sr, reports


def _controls(req: dict) -> dict:
    return {
        "speed": float(np.clip(req.get("speed", 1.0), 0.5, 2.0)),
        "pitch": float(np.clip(req.get("pitch", 0.0), -12, 12)),
        "volume_db": float(np.clip(req.get("volume_db", 0.0), -12, 12)),
        "pause_scale": float(np.clip(req.get("pause_scale", 1.0), 0.0, 3.0)),
        "pronunciation": req.get("pronunciation") or {},
    }


def generate(settings: Settings, store: ProfileStore, req: dict, progress=lambda p, msg: None) -> dict:
    """req: {segments: [{text, emotion?}], mode, profile_id?, engine?, voice?, enhance: bool,
    speed, pitch, volume_db, pause_scale, pronunciation, format(s), sample_rate, target_lufs}"""
    t0 = time.time()
    segments = req.get("segments") or ([{"text": req["text"]}] if req.get("text") else [])
    if not segments or not any((s.get("text") or "").strip() for s in segments):
        raise ValueError("no script text")
    mode = req.get("mode", "natural")
    formats = req.get("formats") or [req.get("format", "wav")]
    if any(f not in ("wav", "mp3") for f in formats):
        raise ValueError("formats must be wav and/or mp3")
    target_sr = int(req.get("sample_rate", 48000))
    if target_sr not in A.SUPPORTED_RATES:
        raise ValueError(f"sample_rate must be one of {A.SUPPORTED_RATES}")
    engine = get_engine(settings, req.get("engine"))
    profile = store.get(req["profile_id"]) if req.get("profile_id") else None
    controls = _controls(req)
    emotion = req.get("emotion") if req.get("emotion") in VALID_EMOTIONS else None

    progress(5, "analysing script")
    all_dirs: list[Direction] = []
    seg_reports = []
    for si, seg in enumerate(segments):
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        analysis = judge(text)
        enhanced = enhance(text, mode) if req.get("enhance", True) else None
        final_text = enhanced["enhanced"] if enhanced else text
        seg_emotion = seg.get("emotion") if seg.get("emotion") in VALID_EMOTIONS else emotion
        lang = analysis["language"]["primary"] if analysis["language"]["primary"] in ("en", "id") else "en"
        dirs = direct(final_text, mode, seg_emotion, scene=si, script_language=lang)
        start = len(all_dirs)
        for k, d in enumerate(dirs):
            d.index = start + k
        all_dirs.extend(dirs)
        seg_reports.append({"scene": si, "label": seg.get("label") or f"Scene {si + 1}",
                            "emotion": seg_emotion or analysis["emotion"]["dominant"],
                            "score": analysis["score"], "enhanced": bool(enhanced),
                            "text": final_text})

    progress(25, f"synthesising {len(all_dirs)} sentences with {engine.name}")
    raw, sr, sentence_reports = render(all_dirs, engine, profile, controls, req.get("voice"))
    progress(80, "mastering")
    mastered, out_sr, master_report = master(raw, sr, target_sr=target_sr,
                                             target_lufs=float(req.get("target_lufs", -16.0)))

    job_id = req.get("job_id") or uuid.uuid4().hex
    out_dir = settings.outputs_dir / job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    files = {}
    for fmt in formats:
        path = A.export(out_dir / f"voiceover.{fmt}", mastered, out_sr, fmt)
        info = A.probe(path)
        if info["duration"] <= 0 or abs(info["duration"] - mastered.size / out_sr) > 0.2:
            raise A.AudioError(f"{fmt} output failed verification: {info}")
        files[fmt] = {"path": str(path), "bytes": path.stat().st_size, "probe": info}
    manifest = {
        "id": job_id, "engine": engine.name, "mode": mode,
        "profile": {"id": profile["id"], "name": profile["name"], "kind": profile.get("kind", "cloned")} if profile else None,
        "controls": {k: v for k, v in controls.items() if k != "pronunciation"} | {
            "pronunciation_entries": len(controls["pronunciation"])},
        "segments": seg_reports, "directions_script": render_script(all_dirs),
        "sentences": sentence_reports, "mastering": master_report, "files": files,
        "elapsed_s": round(time.time() - t0, 2),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    progress(100, "done")
    return manifest


def preview_profile(settings: Settings, store: ProfileStore, profile_id: str, text: str | None = None) -> Path:
    profile = store.get(profile_id)
    lang = profile.get("language") or "en"
    text = text or ("Halo, ini adalah suara saya. Senang bertemu dengan kamu." if lang == "id"
                    else "Hello, this is my voice. It is nice to meet you.")
    manifest = generate(settings, store, {"text": text, "profile_id": profile_id, "enhance": False,
                                          "format": "wav", "sample_rate": 24000,
                                          "job_id": f"preview-{profile_id}"})
    return Path(manifest["files"]["wav"]["path"])
