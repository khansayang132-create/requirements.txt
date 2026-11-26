# NOVA Omniverse: voice cloning & voiceover studio

NOVA reads a script, judges it, improves its delivery, decides how every sentence should be
spoken, renders it with a local voice and masters the result to WAV and MP3. Everything runs
locally; no paid API is needed.

```
script → Script Intelligence (language, emotion, parameters, 0–100 score)
       → Enhancer (natural / professional / expressive, meaning check, diff)
       → Voice Director (tone, rate, pitch, range, volume, emphasis, breaths, pauses per sentence)
       → TTS engine with real controls (espeak-ng, Piper, Sherpa-ONNX)
       → voice profile conversion (WORLD vocoder: pitch, intonation, vocal tract, breathiness)
       → mastering (BS.1770 loudness, noise reduction when needed, silence, fades, true-peak limit)
       → WAV / MP3, each verified with ffprobe
```

What is verified and what is not is in [`STATUS.md`](STATUS.md). Read it before you rely on a feature.

## Run it

```bash
sudo apt install espeak-ng ffmpeg          # Termux: pkg install espeak ffmpeg
cd nova
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn nova.api:app --host 127.0.0.1 --port 8790
```

Open http://127.0.0.1:8790. Don't use port 8765: Headroom uses it on the phone and in cloud sessions.

Tests: `.venv/bin/python -m pytest -q` (30 tests, about 20 s).

## Settings (environment variables)

| Variable | Purpose |
|---|---|
| `NOVA_DATA_DIR` | Where profiles, projects and outputs live (default `~/.nova`, mode 700). |
| `NOVA_API_KEY` | Optional bearer token for every `/api` route except `/api/health`. Set it before binding to anything but 127.0.0.1. |
| `NOVA_SECRET_KEY` | Fernet key for profile encryption. If unset, one is generated in `$NOVA_DATA_DIR/secret.key` (mode 600). Losing the key makes saved profiles unreadable. |
| `NOVA_PIPER_MODEL` | Path to a Piper `.onnx` voice (with its `.onnx.json`). When set, Piper is preferred over espeak-ng. |
| `NOVA_SHERPA_MODEL_DIR` | Folder with a Sherpa-ONNX VITS model (`*.onnx`, `tokens.txt`, optional `espeak-ng-data/`). |
| `NOVA_LLM_BASE_URL`, `NOVA_LLM_MODEL`, `NOVA_LLM_API_KEY` | Optional OpenAI-compatible LLM (e.g. `llama-server -m model.gguf --port 8080` → `http://127.0.0.1:8080/v1`). Used to rewrite scripts and add director notes. Its rewrite is accepted only if the meaning check passes. |

## Making it sound like a real person

espeak-ng is a formant synthesiser: it is always available and every control works, but it
sounds robotic. For natural speech, add a neural voice. These downloads are blocked in the build
sandbox, so they are **not verified here**:

```bash
# Indonesian Piper voice (from the rhasspy/piper-voices repository on Hugging Face)
mkdir -p ~/.nova/models && cd ~/.nova/models
curl -LO https://huggingface.co/rhasspy/piper-voices/resolve/main/id/id_ID/news_tts/medium/id_ID-news_tts-medium.onnx
curl -LO https://huggingface.co/rhasspy/piper-voices/resolve/main/id/id_ID/news_tts/medium/id_ID-news_tts-medium.onnx.json
export NOVA_PIPER_MODEL=~/.nova/models/id_ID-news_tts-medium.onnx
```

The director's pitch, range and the profile's voice are then applied by the conversion stage,
and rate by Piper's `length_scale`. The manifest says which stage applied each control.

### Neural cloning engines

The built-in cloning is signal processing. It matches a profile's pitch, intonation spread,
vocal-tract length and breathiness. It does not copy fine timbre the way a trained cloning model
(XTTS, F5-TTS, OpenVoice, Sherpa-ONNX ZipVoice) does. To add one, implement `TTSEngine` in
`nova/tts/` (one `synthesize()` method plus `capabilities`) and register it in
`nova/tts/__init__.py`. Pass the profile's encrypted reference audio through
`ProfileStore.reference_audio()`, which re-checks it against its consent record.

## Consent and protection

- A voice profile from a recording is refused (HTTP 403) unless the request carries the speaker's
  name, a statement that names them and says they consent, a relationship of `self` or
  `authorized`, and an explicit confirmation. The record is stored with the SHA-256 of the exact
  audio it covers.
- Reference audio and profile data are encrypted at rest (Fernet), files are mode 600, and
  deleting a profile removes every file it owns.
- **Designed voices** are built from parameters (pitch, range, vocal tract, breathiness, pace,
  volume), not from anyone's recording, so they need no consent. Presets: Soft Young Indonesian
  Woman, Warm Indonesian Man, Clear English Narrator.
- Don't clone a voice you don't own or have written permission for, including voices from other
  services' libraries. Those are licensed for use inside that service.

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health`, `/api/system` | Status; engines with their real controls; presets |
| POST | `/api/profiles` (multipart) | Create a profile from a recording, with consent fields |
| POST | `/api/profiles/design` | Create a designed voice (`preset` and/or parameters) |
| GET/DELETE | `/api/profiles[/{id}]` | List, read, delete |
| POST | `/api/profiles/{id}/preview` | Render a short preview |
| POST | `/api/script/analyze`, `/enhance`, `/direct` | Script Intelligence, Enhancer, Director |
| POST | `/api/generate` | Start a background job (`text` or `segments`, controls, formats, sample rate, loudness) |
| GET | `/api/jobs/{id}` | Progress and result manifest |
| GET | `/api/files/{job}/voiceover.wav\|mp3\|manifest.json` | Download |
| CRUD | `/api/projects` | Saved scripts, scenes and settings |

## Code map

| File | Role |
|---|---|
| `nova/analysis.py` | Voice analysis: WORLD F0, LPC formants, HNR, jitter, tilt, rate, pauses, breaths |
| `nova/clone.py` | Profile-matched WORLD conversion |
| `nova/profiles.py` | Consent validation, encrypted store, designed voices and presets |
| `nova/script_judge.py`, `textutil.py` | Language, emotion, voiceover parameters, quality score |
| `nova/enhance.py` | Three enhancement modes, meaning check, word diff |
| `nova/director.py` | Per-sentence direction and engine mapping |
| `nova/tts/` | espeak-ng, Piper and Sherpa-ONNX engines |
| `nova/mastering.py` | Loudness, noise reduction, silence, fades, limiter |
| `nova/pipeline.py` | End-to-end generation and the manifest |
| `nova/api.py`, `web/` | FastAPI app and the studio UI |
