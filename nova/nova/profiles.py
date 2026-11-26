"""Voice profiles with explicit consent.

A profile can only be created when the request carries a consent record: the speaker's name, a
statement in their own words that names them and says they consent, and a confirmation that the
uploader is that speaker or holds their written permission. The record is stored with a SHA-256
of the exact audio it covers.

Protection at rest: the reference audio and the profile JSON are encrypted with Fernet
(AES-128-CBC + HMAC-SHA256). The key comes from NOVA_SECRET_KEY or a generated key file
(mode 600). Directories are mode 700. Deleting a profile removes every file it owns."""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import soundfile as sf
from cryptography.fernet import Fernet, InvalidToken

from .config import Settings

ID_RE = re.compile(r"^[a-f0-9]{32}$")
CONSENT_WORDS = ("consent", "setuju", "izin", "mengizinkan", "permission")


# Designed voices are built from chosen parameters, not from anyone's recording, so they need no
# consent record. Values are generic targets, not measurements of a real speaker.
PRESETS = {
    "soft-young-indonesian-woman": {
        "name": "Soft Young Indonesian Woman", "language": "id", "pitch_hz": 228, "range_semitones": 7.0,
        "formant_scale_hz": 1440, "breathiness": 0.32, "rate": 0.94, "volume_db": -2.0, "variant": "f3",
        "description": "Gentle, warm, young female voice for Indonesian storytelling.",
    },
    "warm-indonesian-man": {
        "name": "Warm Indonesian Man", "language": "id", "pitch_hz": 118, "range_semitones": 6.0,
        "formant_scale_hz": 1180, "breathiness": 0.1, "rate": 0.96, "volume_db": 0.0, "variant": "m3",
        "description": "Calm, warm male narrator.",
    },
    "clear-english-narrator": {
        "name": "Clear English Narrator (female)", "language": "en", "pitch_hz": 205, "range_semitones": 6.5,
        "formant_scale_hz": 1410, "breathiness": 0.12, "rate": 0.98, "volume_db": 0.0, "variant": "f3",
        "description": "Neutral, clear studio narration.",
    },
}


def designed_voice(params: dict) -> dict:
    pitch = float(params["pitch_hz"])
    if not 70 <= pitch <= 400:
        raise ValueError("pitch_hz must be between 70 and 400")
    rng = float(params.get("range_semitones", 6.0))
    sd_log = (rng / 3.29) * np.log(2) / 12  # 5th-95th percentile spread of a normal distribution
    fscale = float(params.get("formant_scale_hz", 1400 if pitch >= 165 else 1180))
    return {
        "pitch": {"f0_median_hz": pitch, "f0_mean_log": round(float(np.log(pitch)), 4),
                  "f0_std_log": round(float(sd_log), 4), "range_semitones": rng},
        "depth": {"formant_scale_hz": fscale},
        "breathiness": float(np.clip(params.get("breathiness", 0.0), 0, 0.6)),
        "delivery": {"rate": float(np.clip(params.get("rate", 1.0), 0.6, 1.5)),
                     "volume_db": float(np.clip(params.get("volume_db", 0.0), -12, 6))},
        "source": "designed (parameters, no reference recording)",
    }


class ConsentError(ValueError):
    pass


class ProfileNotFound(KeyError):
    pass


def validate_consent(consent: dict) -> dict:
    name = (consent.get("speaker_name") or "").strip()
    statement = (consent.get("statement") or "").strip()
    if not consent.get("confirmed"):
        raise ConsentError("consent was not confirmed")
    if consent.get("relationship") not in ("self", "authorized"):
        raise ConsentError("relationship must be 'self' (my own voice) or 'authorized' (written permission)")
    if len(name) < 2:
        raise ConsentError("speaker name is required")
    if len(statement) < 20:
        raise ConsentError("consent statement must be at least 20 characters")
    lowered = statement.lower()
    if name.lower() not in lowered:
        raise ConsentError("the consent statement must name the speaker")
    if not any(w in lowered for w in CONSENT_WORDS):
        raise ConsentError("the consent statement must say that the speaker consents")
    return {"speaker_name": name, "statement": statement, "relationship": consent["relationship"]}


class ProfileStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        settings.ensure_dirs()
        self.fernet = Fernet(self._key())

    def _key(self) -> bytes:
        env = os.environ.get("NOVA_SECRET_KEY")
        if env:
            return env.encode()
        kf = self.settings.key_file
        if not kf.exists():
            fd = os.open(kf, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as fh:
                fh.write(Fernet.generate_key())
        return kf.read_bytes().strip()

    def _dir(self, profile_id: str) -> Path:
        if not ID_RE.match(profile_id or ""):
            raise ProfileNotFound(profile_id)
        return self.settings.profiles_dir / profile_id

    def _write(self, path: Path, data: bytes) -> None:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(self.fernet.encrypt(data))

    def _read(self, path: Path) -> bytes:
        try:
            return self.fernet.decrypt(path.read_bytes())
        except InvalidToken as exc:
            raise ProfileNotFound(f"{path.parent.name}: cannot decrypt (wrong key or tampered)") from exc

    def create(self, name: str, audio: np.ndarray, sr: int, consent: dict, analysis: dict,
               language: str = "", accent: str = "") -> dict:
        record = validate_consent(consent)
        buf = io.BytesIO()
        sf.write(buf, np.clip(audio, -1, 1), sr, format="WAV", subtype="PCM_16")
        wav_bytes = buf.getvalue()
        profile_id = uuid.uuid4().hex
        d = self._dir(profile_id)
        d.mkdir(mode=0o700)
        now = datetime.now(timezone.utc).isoformat()
        record.update({"timestamp": now, "audio_sha256": hashlib.sha256(wav_bytes).hexdigest()})
        profile = {
            "id": profile_id, "kind": "cloned", "name": name.strip() or record["speaker_name"], "created_at": now,
            "language": language, "accent": accent, "sample_rate": sr,
            "duration_s": round(audio.size / sr, 2), "consent": record, "voice": analysis,
            "base_variant": "f3" if analysis["pitch"]["f0_median_hz"] >= 165 else "m3",
        }
        self._write(d / "reference.wav.enc", wav_bytes)
        self._write(d / "profile.json.enc", json.dumps(profile).encode())
        return profile

    def create_designed(self, params: dict) -> dict:
        preset_id = params.get("preset") or ""
        if params.get("preset"):
            if params["preset"] not in PRESETS:
                raise ValueError(f"unknown preset {params['preset']!r}")
            params = PRESETS[params["preset"]] | {k: v for k, v in params.items() if k != "preset" and v is not None}
        voice = designed_voice(params)
        profile_id = uuid.uuid4().hex
        d = self._dir(profile_id)
        d.mkdir(mode=0o700)
        profile = {
            "id": profile_id, "kind": "designed", "name": (params.get("name") or "Designed voice").strip(),
            "created_at": datetime.now(timezone.utc).isoformat(), "language": params.get("language", ""),
            "accent": "", "duration_s": 0, "consent": None, "voice": voice,
            "description": params.get("description", ""), "preset": preset_id,
            "base_variant": params.get("variant") or ("f3" if voice["pitch"]["f0_median_hz"] >= 165 else "m3"),
        }
        self._write(d / "profile.json.enc", json.dumps(profile).encode())
        return profile

    def get(self, profile_id: str) -> dict:
        path = self._dir(profile_id) / "profile.json.enc"
        if not path.exists():
            raise ProfileNotFound(profile_id)
        return json.loads(self._read(path))

    def reference_audio(self, profile_id: str) -> tuple[np.ndarray, int]:
        path = self._dir(profile_id) / "reference.wav.enc"
        if not path.exists():
            raise ProfileNotFound(f"{profile_id}: no reference recording (designed voice?)")
        data = self._read(path)
        profile = self.get(profile_id)
        if hashlib.sha256(data).hexdigest() != profile["consent"]["audio_sha256"]:
            raise ProfileNotFound(f"{profile_id}: reference audio does not match its consent record")
        x, sr = sf.read(io.BytesIO(data), dtype="float64")
        return x, int(sr)

    def synthetic_reference(self, profile_id: str, build) -> tuple[np.ndarray, int]:
        """Reference audio for a *designed* voice: synthesised by NOVA (an engine's default voice
        reshaped to the design), so it belongs to no real person and needs no consent record.
        Built once by `build() -> (audio, sr)`, then stored encrypted so every render uses the
        identical reference and the voice stays the same from day to day."""
        profile = self.get(profile_id)
        if profile.get("kind") != "designed":
            raise ValueError("synthetic references are only for designed voices")
        path = self._dir(profile_id) / "synthetic_reference.wav.enc"
        if path.exists():
            x, sr = sf.read(io.BytesIO(self._read(path)), dtype="float64")
            return x, int(sr)
        x, sr = build()
        buf = io.BytesIO()
        sf.write(buf, np.clip(x, -1, 1), sr, format="WAV", subtype="PCM_16")
        self._write(path, buf.getvalue())
        return x, sr

    def list(self) -> list[dict]:
        out = []
        for d in sorted(self.settings.profiles_dir.iterdir()):
            if d.is_dir() and ID_RE.match(d.name):
                try:
                    p = self.get(d.name)
                except ProfileNotFound:
                    continue
                out.append({k: p.get(k) for k in ("id", "name", "created_at", "language", "duration_s")}
                           | {"kind": p.get("kind", "cloned"),
                              "speaker": p["consent"]["speaker_name"] if p.get("consent") else None,
                              "description": p.get("description", "")})
        return sorted(out, key=lambda p: p["created_at"], reverse=True)

    def delete(self, profile_id: str) -> None:
        d = self._dir(profile_id)
        if not d.exists():
            raise ProfileNotFound(profile_id)
        shutil.rmtree(d)
