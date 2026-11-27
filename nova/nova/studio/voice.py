"""ENGINE 05: Voice performance direction - adapter registry and voice selection.

Each adapter declares what its engine really supports. Emotional control is listed only where
the engine changes the sound for it; everything else is realised through rate, pitch, volume and
pauses at segment level, and the declaration says so."""
from __future__ import annotations

from ..config import Settings
from ..profiles import PRESETS, ProfileStore
from ..tts import engines

ADAPTER_FACTS = {
    "chatterbox-id": {"languages": ["id"], "max_chars": 280, "sample_rates": [24000],
                      "emotional_controls": ["intensity via exaggeration (pitch range)"],
                      "parameters": ["rate (time-stretch)", "volume (gain)", "pauses", "voice cloning from reference"],
                      "notes": "neural, natural; zero-shot cloning; CPU 4-6x slower than real time"},
    "piper": {"languages": ["id"], "max_chars": 2000, "sample_rates": [22050],
              "emotional_controls": [],
              "parameters": ["rate (length scale)", "volume (gain)", "pitch (post shift)", "pauses"],
              "notes": "neural, fast; one Indonesian voice; no native emotion"},
    "espeak-ng": {"languages": ["en", "id", "ur", "ar", "and more"], "max_chars": 5000, "sample_rates": [22050],
                  "emotional_controls": [],
                  "parameters": ["rate", "pitch", "pitch range (intonation)", "volume", "word emphasis", "pauses"],
                  "notes": "formant synthesis: robotic; always available; only engine here with Urdu and Arabic"},
    "sherpa-onnx": {"languages": ["depends on model"], "max_chars": 2000, "sample_rates": [22050],
                    "emotional_controls": [], "parameters": ["rate", "volume", "pauses"],
                    "notes": "installed, no model downloaded: not verified"},
}
FORMATS = ["wav", "mp3"]


def adapters(settings: Settings) -> list[dict]:
    out = []
    for name, eng in engines(settings).items():
        facts = ADAPTER_FACTS.get(name, {})
        try:
            ok = eng.available()
        except Exception as exc:  # report, never crash the listing
            ok, err = False, str(exc)
        else:
            err = ""
        try:
            voices = eng.voices() if ok else []
        except Exception:
            voices = []
        out.append({"name": name, "status": "available" if ok else "unavailable", "error": err[:200],
                    "languages": facts.get("languages", list(eng.capabilities.languages)),
                    "voices": voices[:50], "emotional_controls": facts.get("emotional_controls", []),
                    "parameters": facts.get("parameters", []), "max_chars": facts.get("max_chars", 1000),
                    "sample_rates": facts.get("sample_rates", []), "output_formats": FORMATS,
                    "clones_from_reference": bool(eng.clones_from_reference), "notes": facts.get("notes", "")})
    return out


def catalog(settings: Settings, store: ProfileStore) -> list[dict]:
    """Voices the user can choose: their profiles (cloned with consent, or designed) and presets."""
    items = [{"id": p["id"], "name": p["name"], "kind": p["kind"], "language": p.get("language"),
              "gender": None, "source": "profile"} for p in store.list()]
    for key, p in PRESETS.items():
        items.append({"id": f"preset:{key}", "name": p["name"], "kind": "preset", "language": p["language"],
                      "gender": "female" if p["pitch_hz"] > 165 else "male", "source": "preset"})
    return items


def select(settings: Settings, store: ProfileStore, language: str, voice: str | None) -> dict:
    """Pick engine and voice for a language. Returns {engine, profile_id, preset, reason}."""
    avail = {a["name"]: a for a in adapters(settings) if a["status"] == "available"}
    profile_id, preset = None, None
    if voice and voice.startswith("preset:"):
        preset = voice.split(":", 1)[1]
        if preset not in PRESETS:
            raise ValueError(f"unknown preset {preset!r}")
    elif voice:
        store.get(voice)  # raises if missing
        profile_id = voice
    if language == "id":
        for name in ("chatterbox-id", "piper", "espeak-ng"):
            if name in avail and (name != "chatterbox-id" or profile_id or preset):
                return {"engine": name, "profile_id": profile_id, "preset": preset,
                        "reason": f"best available Indonesian engine: {name}"}
    if "espeak-ng" in avail:
        return {"engine": "espeak-ng", "profile_id": profile_id, "preset": preset,
                "reason": f"only installed engine for '{language}' (robotic)"}
    raise RuntimeError(f"no voice engine available for language {language!r}")
