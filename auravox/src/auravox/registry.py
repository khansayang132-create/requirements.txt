"""Voice technology registry: what exists, where it comes from, under which licence, and what is installed here.

Entries are researched facts with the date they were checked; `status()` adds live local evidence (installed, import
works, health check). Nothing listed here is installed automatically.
"""

from __future__ import annotations

import importlib.util
import shutil

CHECKED = "2026-11-13"

# capability keys follow the AURAVOX spec (System 02)
TECH = [
    {"name": "eSpeak NG", "id": "espeak-ng", "source": "https://github.com/espeak-ng/espeak-ng", "licence": "GPL-3.0",
     "weights": "none (rule-based)", "caps": ["tts", "multilingual", "phoneme_extraction", "emotion(prosody)"], "offline": True,
     "hardware": "any CPU", "python": "espeakng_loader", "limits": "robotic formant voice"},
    {"name": "Piper (piper1-gpl)", "id": "piper", "source": "https://github.com/OHF-Voice/piper1-gpl", "licence": "GPL-3.0",
     "weights": "per voice: mostly CC-BY-4.0 / CC-BY-NC-SA / MIT; check MODEL_CARD", "caps": ["tts", "multilingual", "phoneme_alignment"],
     "offline": True, "hardware": "CPU (real-time on 1 core)", "python": "piper", "limits": "no emotion control beyond rate/noise; models on huggingface.co"},
    {"name": "Kokoro-82M (kokoro-onnx)", "id": "kokoro", "source": "https://github.com/thewh1teagle/kokoro-onnx", "licence": "MIT (runtime)",
     "weights": "Apache-2.0", "caps": ["tts", "multilingual(limited)"], "offline": True, "hardware": "CPU", "python": "kokoro_onnx",
     "limits": "~340 MB model from GitHub releases; no phoneme timing API"},
    {"name": "Coqui XTTS-v2", "id": "xtts", "source": "https://github.com/idiap/coqui-ai-TTS", "licence": "MPL-2.0 (code)",
     "weights": "Coqui Public Model License (non-commercial)", "caps": ["tts", "multilingual", "authorized_voice_cloning", "emotion(reference)"],
     "offline": True, "hardware": "GPU recommended (4+ GB)", "python": "TTS", "limits": "weights non-commercial; 1.8 GB"},
    {"name": "F5-TTS", "id": "f5", "source": "https://github.com/SWivid/F5-TTS", "licence": "MIT (code)", "weights": "CC-BY-NC-4.0",
     "caps": ["tts", "authorized_voice_cloning"], "offline": True, "hardware": "GPU", "python": "f5_tts", "limits": "non-commercial weights"},
    {"name": "Chatterbox", "id": "chatterbox", "source": "https://github.com/resemble-ai/chatterbox", "licence": "MIT",
     "weights": "MIT", "caps": ["tts", "emotion(exaggeration)", "authorized_voice_cloning"], "offline": True, "hardware": "GPU recommended",
     "python": "chatterbox", "limits": "English-first; watermarking built in"},
    {"name": "OpenVoice v2", "id": "openvoice", "source": "https://github.com/myshell-ai/OpenVoice", "licence": "MIT", "weights": "MIT",
     "caps": ["voice_conversion", "speech_to_speech", "authorized_voice_cloning"], "offline": True, "hardware": "GPU recommended",
     "python": "openvoice", "limits": "tone-colour converter; needs a base TTS"},
    {"name": "RVC", "id": "rvc", "source": "https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI", "licence": "MIT",
     "weights": "per trained model", "caps": ["voice_conversion", "speech_to_speech"], "offline": True, "hardware": "GPU",
     "python": None, "limits": "training per voice; consent required"},
    {"name": "faster-whisper", "id": "whisper", "source": "https://github.com/SYSTRAN/faster-whisper", "licence": "MIT", "weights": "MIT (OpenAI Whisper)",
     "caps": ["speech_recognition", "word_timestamps"], "offline": True, "hardware": "CPU ok (small/base)", "python": "faster_whisper",
     "limits": "models download from huggingface.co"},
    {"name": "Montreal Forced Aligner", "id": "mfa", "source": "https://github.com/MontrealCorpusTools/Montreal-Forced-Aligner", "licence": "MIT",
     "weights": "acoustic models per language (various)", "caps": ["forced_alignment", "phoneme_extraction"], "offline": True,
     "hardware": "CPU", "python": "montreal_forced_aligner", "limits": "conda install; models downloaded separately"},
    {"name": "pyannote.audio", "id": "pyannote", "source": "https://github.com/pyannote/pyannote-audio", "licence": "MIT",
     "weights": "gated on huggingface.co (accept terms)", "caps": ["speaker_diarization", "speaker_identification", "vad"], "offline": True,
     "hardware": "GPU recommended", "python": "pyannote.audio", "limits": "needs a HF token for gated weights"},
    {"name": "Silero VAD", "id": "silero-vad", "source": "https://github.com/snakers4/silero-vad", "licence": "MIT", "weights": "MIT",
     "caps": ["vad"], "offline": True, "hardware": "CPU", "python": "silero_vad", "limits": "model via torch hub / pip package"},
    {"name": "Demucs", "id": "demucs", "source": "https://github.com/facebookresearch/demucs", "licence": "MIT", "weights": "MIT",
     "caps": ["audio_separation"], "offline": True, "hardware": "GPU recommended", "python": "demucs", "limits": "archived upstream (2025)"},
    {"name": "DeepFilterNet", "id": "deepfilternet", "source": "https://github.com/Rikorose/DeepFilterNet", "licence": "MIT/Apache-2.0",
     "weights": "MIT/Apache-2.0", "caps": ["audio_enhancement", "denoise"], "offline": True, "hardware": "CPU", "python": "df",
     "limits": "Rust build for some platforms"},
    {"name": "AudioCraft (AudioGen/MusicGen)", "id": "audiocraft", "source": "https://github.com/facebookresearch/audiocraft",
     "licence": "MIT (code)", "weights": "CC-BY-NC-4.0", "caps": ["sound_effects", "music"], "offline": True, "hardware": "GPU",
     "python": "audiocraft", "limits": "non-commercial weights"},
    {"name": "FFmpeg (loudnorm, acompressor, equalizer)", "id": "ffmpeg", "source": "https://ffmpeg.org", "licence": "LGPL/GPL",
     "weights": "n/a", "caps": ["audio_mastering", "export"], "offline": True, "hardware": "CPU", "python": None, "binary": "ffmpeg",
     "limits": "-"},
    {"name": "AURAVOX viseme mapper + HUMANVERSE/Blender", "id": "lipsync", "source": "this repository", "licence": "MIT",
     "weights": "n/a", "caps": ["lip_synchronization"], "offline": True, "hardware": "CPU", "python": None, "limits": "needs phoneme timing"},
]


def status(engines_health: dict | None = None) -> list[dict]:
    out = []
    for t in TECH:
        installed = False
        how = "not installed"
        if t.get("binary"):
            installed = bool(shutil.which(t["binary"]))
            how = shutil.which(t["binary"]) or how
        elif t.get("python"):
            installed = importlib.util.find_spec(t["python"].split(".")[0]) is not None
            how = f"python module {t['python']}" if installed else how
        elif t["id"] == "lipsync":
            installed, how = True, "built in"
        h = (engines_health or {}).get(t["id"])
        st = h[0] if h else ("NOT TESTED" if installed else "NOT INSTALLED")
        out.append({**t, "installed": installed, "local": how, "status": st, "health": h[1] if h else "", "checked": CHECKED})
    return out
