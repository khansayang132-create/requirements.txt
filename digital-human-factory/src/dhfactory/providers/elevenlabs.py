"""ElevenLabs voices through the official SDK (`elevenlabs`, github.com/elevenlabs/elevenlabs-python).

Uses text_to_speech.convert_with_timestamps, so subtitles and sync checks use the provider's real character timings.
Voice cloning is NOT done here: cloning needs documented consent from the voice owner, which the pipeline records in
configuration/voice-authorizations.json before any cloned voice id may be used.
"""

from __future__ import annotations

import base64
import json
import subprocess
from pathlib import Path

from ..errors import DHFError, ProviderError
from ..media.ffmpeg import binary
from .base import Provider, VoiceResult, register


@register
class ElevenLabsProvider(Provider):
    name = "elevenlabs"
    capabilities = frozenset({"voice"})
    env_var = "ELEVENLABS_API_KEY"

    def client(self):
        from elevenlabs.client import ElevenLabs

        return ElevenLabs(api_key=self.require_key(), timeout=self.settings.http_timeout)

    def health(self, client=None) -> dict:
        c = client or self.client()
        sub = c.user.subscription.get()
        return {"ok": True, "tier": getattr(sub, "tier", None), "characters_used": sub.character_count, "character_limit": sub.character_limit}

    def tts(self, cues_text: list[str], out: Path, language: str = "en", *, voice_id: str, model_id: str = "eleven_multilingual_v2",
            authorized_clones: set[str] | None = None, client=None) -> VoiceResult:
        if authorized_clones is not None and voice_id.startswith("clone:") and voice_id not in authorized_clones:
            raise DHFError(f"voice {voice_id} is a clone without a recorded authorization")
        c = client or self.client()
        text = " ".join(cues_text)
        try:
            resp = c.text_to_speech.convert_with_timestamps(voice_id=voice_id, text=text, model_id=model_id, language_code=language,
                                                            output_format="mp3_44100_128")
        except Exception as e:  # SDK raises ApiError subclasses; keep the message short and secret-free
            raise ProviderError(self.name, f"{type(e).__name__}: {str(e)[:200]}") from e
        mp3 = out.with_suffix(".mp3")
        mp3.write_bytes(base64.b64decode(resp.audio_base_64))
        subprocess.run([binary(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(mp3), "-ar", "48000", "-ac", "1", str(out)], check=True)
        al = resp.alignment
        cues = _cues_from_alignment(cues_text, al.characters, al.character_start_times_seconds, al.character_end_times_seconds)
        (out.parent / "alignment.json").write_text(json.dumps({"characters": al.characters, "start": al.character_start_times_seconds,
                                                                "end": al.character_end_times_seconds}), encoding="utf-8")
        return VoiceResult(audio=out, duration=max(al.character_end_times_seconds or [0.0]), cues=cues, provider=self.name,
                           cost_usd=self.estimate_usd("voice", len(text)), timing_source="provider")


def _cues_from_alignment(sentences: list[str], chars: list[str], starts: list[float], ends: list[float]) -> list[dict]:
    """Map each sentence onto the provider's character timings (the joined text is sentences joined by single spaces)."""
    cues, pos = [], 0
    for s in sentences:
        a, b = pos, min(len(chars), pos + len(s)) - 1
        if a < len(starts) and b >= a:
            cues.append({"text": s, "start": round(starts[a], 3), "end": round(ends[b], 3)})
        pos += len(s) + 1
    return cues
