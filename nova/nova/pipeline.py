"""The end-to-end workflow: script -> analysis -> enhancement -> directions -> per-sentence synthesis
with real engine controls -> profile voice conversion -> pauses and breaths -> mastering -> export.

Every output is checked with ffprobe after it is written, and the manifest records what each
stage actually did (including controls an engine does not support)."""
from __future__ import annotations

import json
import os
import re
import tempfile
import time
import uuid
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import numpy as np

from . import audio as A
from .clone import convert, shift_pitch
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
                         voice: str | None = None, reference: str | None = None) -> tuple[np.ndarray, int, dict]:
    delivery = (profile or {}).get("voice", {}).get("delivery", {})
    p = d.prosody
    prosody = Prosody(
        rate=p.rate * controls.get("speed", 1.0) * delivery.get("rate", 1.0),
        pitch_semitones=p.pitch_semitones + controls.get("pitch", 0.0),
        pitch_range=p.pitch_range,
        volume_db=p.volume_db + controls.get("volume_db", 0.0) + delivery.get("volume_db", 0.0),
        emphasis=p.emphasis,
    )
    # A neural cloning engine given the profile's own recording reproduces the voice itself;
    # WORLD conversion or pitch shifting on top would only add vocoder artefacts.
    neural_clone = bool(reference) and engine.clones_from_reference
    converting = profile is not None and not neural_clone
    engine_prosody = replace(prosody, pitch_semitones=0.0, pitch_range=1.0) if converting else prosody
    text = apply_pronunciation(d.text, controls.get("pronunciation"))
    chunks = [text]
    if d.breath_after_word:
        ws = text.split()
        chunks = [" ".join(ws[:d.breath_after_word]), " ".join(ws[d.breath_after_word:])]
    v = reference if neural_clone else _voice_for(engine, d.language, profile, voice)
    pieces, sr, conv_reports = [], None, []
    for i, chunk in enumerate(c for c in chunks if c.strip()):
        x, rate = engine.synthesize(chunk, d.language, engine_prosody, v)
        x = trim_edges(x, rate)  # engines pad each phrase; NOVA's directed pauses replace that padding
        if converting:
            x, rate, rep = convert(x, rate, profile["voice"], prosody.pitch_semitones, prosody.pitch_range,
                                   source_scale=base_formant_scale(engine, d.language, v))
            conv_reports.append(rep)
        elif (not neural_clone and not engine.capabilities.pitch
              and (prosody.pitch_semitones or prosody.pitch_range != 1.0)):
            x, rate, rep = shift_pitch(x, rate, prosody.pitch_semitones, prosody.pitch_range)
            conv_reports.append({"pitch_shift": rep})
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
        "sentence": d.index, "scene": d.scene, "text": d.text, "spoken_text": text, "tone": d.tone,
        "voice": "profile reference (neural clone)" if neural_clone else v,
        "prosody": {"rate": round(prosody.rate, 3), "pitch_semitones": round(prosody.pitch_semitones, 2),
                    "pitch_range": round(prosody.pitch_range, 3), "volume_db": round(prosody.volume_db, 2),
                    "emphasis": prosody.emphasis},
        "applied_by": (map_to_engine(d, engine.capabilities, converting) | (
            {"pitch": "neural clone (emotion via exaggeration)", "pitch_range": "neural clone (exaggeration)",
             "voice_identity": "neural clone from reference"} if neural_clone else {})),
        "conversion": conv_reports, "duration_s": round(out.size / sr, 3),
    }
    return out, sr, report


NEURAL_CHUNK_CHARS = 280  # Chatterbox speaks up to about this much in one natural breath group


def merge_scenes(directions: list[Direction]) -> list[Direction]:
    """For a neural cloning engine: speak each scene in one call (split only when it is long), so the
    melody flows across sentences instead of resetting at every full stop. Per-sentence rate changes
    are dropped: on this engine they could only be applied by time-stretching, which sounds robotic."""
    out: list[Direction] = []
    for d in directions:
        last = out[-1] if out else None
        if (last is not None and last.scene == d.scene and len(last.text) + 1 + len(d.text) <= NEURAL_CHUNK_CHARS):
            pitch_range = max(last.prosody.pitch_range, d.prosody.pitch_range)
            last.text = f"{last.text} {d.text}"
            last.prosody = replace(last.prosody, pitch_range=pitch_range)
            last.pause_after_ms = d.pause_after_ms
            if getattr(d, "pause_fixed", False):
                last.pause_fixed = True
            continue
        m = replace(d, prosody=replace(d.prosody, rate=1.0), breath_after_word=None, applied={})
        if getattr(d, "pause_fixed", False):
            m.pause_fixed = True
        out.append(m)
    for i, d in enumerate(out):
        d.index = i
    return out


def render(directions: list[Direction], engine: TTSEngine, profile: dict | None, controls: dict,
           voice: str | None = None, reference: str | None = None) -> tuple[np.ndarray, int, list[dict]]:
    pieces, reports, sr = [], [], None
    pause_scale = controls.get("pause_scale", 1.0)
    for i, d in enumerate(directions):
        x, rate, rep = synthesize_direction(d, engine, profile, controls, voice, reference)
        if sr is None:
            sr = rate
        elif rate != sr:
            x = A.resample(x, rate, sr)
        start = sum(pc.size for pc in pieces)
        pieces.append(x)
        rep["raw_start_s"], rep["raw_end_s"] = round(start / sr, 4), round((start + x.size) / sr, 4)
        nxt = directions[i + 1] if i + 1 < len(directions) else None
        gap = d.pause_after_ms
        if nxt is not None and nxt.scene != d.scene and not getattr(d, "pause_fixed", False):
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
        "soften": float(np.clip(req.get("soften", 0.0), 0.0, 1.0)),
        "pronunciation": req.get("pronunciation") or {},
    }


SYNTH_PASSAGE = ("Halo, selamat pagi. Hari ini cuacanya cerah sekali, jadi aku mau jalan-jalan sebentar ke pasar. "
                 "Aku suka melihat buah-buahan segar dan mengobrol dengan para penjual yang ramah.")


VOICES_DIR = Path(__file__).resolve().parent.parent / "voices"


def build_synthetic_reference(engine: TTSEngine, profile: dict) -> tuple[np.ndarray, int]:
    """The engine's own default voice reading a neutral passage, reshaped by WORLD to the design.
    A preset ships its reference in nova/voices/ so every computer gets the identical voice."""
    packaged = VOICES_DIR / f"{profile.get('preset') or '-'}.reference.wav"
    if packaged.is_file():
        return A.load_audio(packaged)
    x, sr = engine.synthesize(SYNTH_PASSAGE, "id", Prosody(rate=0.95), None)
    y, ysr, _ = convert(x, sr, profile["voice"])
    return y / (np.max(np.abs(y)) + 1e-9) * 0.9, ysr


def trim_edges(x: np.ndarray, sr: int, threshold_db: float = -45.0, keep_ms: float = 40.0) -> np.ndarray:
    """Cut leading/trailing near-silence relative to the phrase's own peak, keeping a short margin."""
    if x.size == 0:
        return x
    env = np.abs(x)
    loud = np.flatnonzero(env > np.max(env) * 10 ** (threshold_db / 20))
    if loud.size == 0:
        return x
    keep = int(sr * keep_ms / 1000)
    return x[max(0, loud[0] - keep): min(x.size, loud[-1] + keep)]


@contextmanager
def _reference_file(store: ProfileStore, profile: dict | None, engine: TTSEngine):
    """The reference a neural cloning engine speaks from, as a private temp WAV for one render:
    a cloned profile's own recording (re-checked against its consent record), or for a designed
    voice a synthetic reference NOVA builds once from the engine's default voice and the design."""
    if not (profile and engine.clones_from_reference):
        yield None
        return
    if profile.get("kind", "cloned") == "cloned":
        x, sr = store.reference_audio(profile["id"])
    else:
        x, sr = store.synthetic_reference(profile["id"], lambda: build_synthetic_reference(engine, profile))
    x = x[: sr * 20]  # a 10-20 s prompt is what zero-shot cloning uses
    x = x / (np.max(np.abs(x)) + 1e-9) * 0.9  # the model expects samples inside [-1, 1]
    with tempfile.TemporaryDirectory() as td:
        os.chmod(td, 0o700)
        path = A.write_wav(Path(td) / "reference.wav", x, sr)
        yield str(path)


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
    profile = store.get(req["profile_id"]) if req.get("profile_id") else None
    engine = get_engine(settings, req.get("engine"),
                        has_reference=profile is not None)
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
        if seg.get("prosody"):  # an external director (the studio's emotion engine) sets the delivery
            po = seg["prosody"]
            for d in dirs:
                d.prosody = replace(d.prosody, **{k: float(po[k]) for k in ("rate", "pitch_semitones",
                                                                            "pitch_range", "volume_db") if k in po})
                if po.get("emphasis") is not None:
                    d.prosody = replace(d.prosody, emphasis=list(po["emphasis"]))
        start = len(all_dirs)
        for k, d in enumerate(dirs):
            d.index = start + k
        if dirs and seg.get("pause_after_ms") is not None:  # the caller sets the gap after this segment
            dirs[-1].pause_after_ms = max(0, min(int(seg["pause_after_ms"]), 5000))
            dirs[-1].pause_fixed = True  # an explicit pause replaces the default scene gap
        all_dirs.extend(dirs)
        seg_reports.append({"scene": si, "label": seg.get("label") or f"Scene {si + 1}",
                            "emotion": seg_emotion or analysis["emotion"]["dominant"],
                            "score": analysis["score"], "enhanced": bool(enhanced),
                            "text": final_text})

    neural = bool(profile) and engine.clones_from_reference
    if neural:
        all_dirs = merge_scenes(all_dirs)
    progress(25, f"synthesising {len(all_dirs)} {'scenes' if neural else 'sentences'} with {engine.name}")
    tone_pitch = controls["pitch"] if neural else 0.0
    with _reference_file(store, profile, engine) as reference:
        if neural and (tone_pitch or controls["soften"]):
            # A neural clone gets its pitch and softness from the reference itself: the model then
            # speaks that way natively, with no processing on the finished voice.
            rx, rsr = A.load_audio(reference)
            toned = Path(reference).with_name("reference-toned.wav")
            A.write_wav(toned, A.voice_tone(rx, rsr, tone_pitch, controls["soften"]) * 0.98, rsr)
            reference = str(toned)
        raw, sr, sentence_reports = render(all_dirs, engine, profile, controls, req.get("voice"), reference)
    if not neural and controls["soften"]:
        progress(78, "adjusting voice tone")
        raw = A.voice_tone(raw, sr, 0.0, controls["soften"])
    polish_report = None
    if req.get("polish"):  # high-pass, gentle compression, de-essing only when sibilant
        from .studio.mix import polish
        raw, polish_report = polish(raw, sr)
    progress(80, "mastering")
    mastered, out_sr, master_report = master(raw, sr, target_sr=target_sr,
                                             target_lufs=float(req.get("target_lufs", -16.0)))

    from .mastering import map_time
    tmap = master_report["time_map"]
    timeline = [{"index": r["sentence"], "scene": r["scene"], "text": r["spoken_text"],
                 "start_s": round(map_time(r["raw_start_s"], tmap), 3),
                 "end_s": round(map_time(r["raw_end_s"], tmap), 3)} for r in sentence_reports]
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
        "sentences": sentence_reports, "timeline": timeline, "polish": polish_report, "mastering": master_report, "files": files,
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


def master_upload(settings: Settings, src: Path, req: dict, progress=lambda p, msg: None) -> dict:
    """Polish an existing voiceover (your own recording or audio you generated elsewhere):
    loudness for the chosen platform, true-peak limit, edge silence, fades, WAV/MP3. The voice
    itself is not re-synthesised or converted."""
    from .mastering import integrated_loudness, true_peak_db

    formats = req.get("formats") or ["wav", "mp3"]
    if any(f not in ("wav", "mp3") for f in formats):
        raise ValueError("formats must be wav and/or mp3")
    target_sr = int(req.get("sample_rate", 48000))
    if target_sr not in A.SUPPORTED_RATES:
        raise ValueError(f"sample_rate must be one of {A.SUPPORTED_RATES}")
    progress(10, "reading audio")
    x, sr = A.load_audio(src)
    if x.size < sr * 0.5:
        raise ValueError("audio is shorter than half a second")
    if x.size > sr * 1800:
        raise ValueError("audio is longer than 30 minutes")
    before = {"lufs": round(integrated_loudness(x, sr), 2), "true_peak_dbtp": round(true_peak_db(x), 2),
              "duration_s": round(x.size / sr, 2), "sample_rate": sr}
    progress(40, "mastering")
    y, out_sr, report = master(x, sr, target_sr=target_sr, target_lufs=float(req.get("target_lufs", -14.0)))
    job_id = req.get("job_id") or uuid.uuid4().hex
    out_dir = settings.outputs_dir / job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    files = {}
    for fmt in formats:
        path = A.export(out_dir / f"voiceover.{fmt}", y, out_sr, fmt)
        info = A.probe(path)
        if info["duration"] <= 0 or abs(info["duration"] - y.size / out_sr) > 0.2:
            raise A.AudioError(f"{fmt} output failed verification: {info}")
        files[fmt] = {"path": str(path), "bytes": path.stat().st_size, "probe": info}
    manifest = {"id": job_id, "kind": "master", "source": req.get("filename", src.name), "before": before,
                "mastering": report, "files": files}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    progress(100, "done")
    return manifest
