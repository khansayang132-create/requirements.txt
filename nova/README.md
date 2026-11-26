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

Tests: `.venv/bin/python -m pytest -q` (45 tests, about 30 s; the 3 Piper tests skip until `scripts/get-voices.sh` has run, the Chatterbox test runs only with `NOVA_CHATTERBOX_TEST=1` and `requirements-neural.txt` installed, and the real-LLM test only with `NOVA_LLM_TEST_URL` set).

## Settings (environment variables)

| Variable | Purpose |
|---|---|
| `NOVA_DATA_DIR` | Where profiles, projects and outputs live (default `~/.nova`, mode 700). |
| `NOVA_API_KEY` | Optional bearer token for every `/api` route except `/api/health`. Set it before binding to anything but 127.0.0.1. |
| `NOVA_SECRET_KEY` | Fernet key for profile encryption. If unset, one is generated in `$NOVA_DATA_DIR/secret.key` (mode 600). Losing the key makes saved profiles unreadable. |
| `NOVA_PIPER_MODEL` | Path to a Piper `.onnx` voice (with its `.onnx.json`). Default: `~/.nova/models/id_ID-news_tts-medium.onnx` if present. When available, Piper is preferred over espeak-ng. |
| `NOVA_CHATTERBOX` | `1` enables neural voice cloning with Chatterbox-TTS-Indonesian (needs `requirements-neural.txt`). Preferred over the other engines when enabled. |
| `NOVA_SHERPA_MODEL_DIR` | Folder with a Sherpa-ONNX VITS model (`*.onnx`, `tokens.txt`, optional `espeak-ng-data/`). |
| `NOVA_LLM_BASE_URL`, `NOVA_LLM_MODEL`, `NOVA_LLM_API_KEY`, `NOVA_LLM_THINKING` | Optional OpenAI-compatible LLM (see "Free local AI for the script tools" below). Used to rewrite scripts and add director notes. Its rewrite is accepted only if the meaning check passes. |

## Set up from the app (Settings page)

Everything below can also be done in **Settings** without environment variables:

- **AI for script tools:** pick a provider (llama.cpp, Ollama, LM Studio, vLLM, Jan, KoboldCpp or
  Custom), check the endpoint, press **Load models**, then **Test connection**. The test shows the
  model's reply and how long it took, or a plain-language fix (server not running, wrong key,
  model not found, rate limit, empty "thinking" reply). Choices are saved in
  `$NOVA_DATA_DIR/runtime.json` (mode 600) and override the `NOVA_LLM_*` variables; an API key is
  stored encrypted and never sent back to the browser.
- **Voices:** **Download voice** installs the Indonesian Piper voice with progress and a SHA-256
  check (a corrupted download installs nothing). The Chatterbox switch turns neural cloning on once
  `requirements-neural.txt` is installed; **Load model now** downloads and loads it ahead of the
  first render.
- When no engine is chosen, Chatterbox is used only for cloned profiles with a recording; designed
  voices and the plain engine voice use Piper (or espeak-ng).
- **Master a voiceover** (Audio Studio): upload a finished voiceover, your own recording or audio
  you generated elsewhere, and get it back at the chosen loudness (−14 LUFS for TikTok/Reels by
  default) with peaks limited and edges tidied. The voice is not converted, and the upload is
  deleted after mastering. API: `POST /api/master` (multipart `audio`, `target_lufs`, `formats`).
- The Enhancer shows whether the AI rewrite was used or rejected, and Script Intelligence shows the
  AI director notes.

## Free local AI for the script tools

The enhancer's rewrite and the director notes can use any free local model behind an
OpenAI-compatible server. NOVA's backend makes the call, not the browser, so CORS settings
(such as `OLLAMA_ORIGINS`) are not needed. `NOVA_LLM_BASE_URL` accepts the base address,
`…/v1`, or the full `…/v1/chat/completions` URL.

Small, fast models are the right choice; Gemma 4 E2B (3.1 GB, Apache-2.0) was tested here:

```bash
# llama.cpp (tested): build or download llama-server, then
llama-server -hf unsloth/gemma-4-E2B-it-GGUF:Q4_K_M --host 127.0.0.1 --port 8093 -c 4096 --jinja
export NOVA_LLM_BASE_URL=http://127.0.0.1:8093 NOVA_LLM_MODEL=gemma
```

| Server | `NOVA_LLM_BASE_URL` | `NOVA_LLM_MODEL` |
|---|---|---|
| llama.cpp `llama-server` | `http://127.0.0.1:PORT` | any name (one model loaded) |
| Ollama (`ollama pull gemma4:e2b`) | `http://127.0.0.1:11434` | the tag from `ollama list` |
| LM Studio (Developer tab, server running) | `http://127.0.0.1:1234` | the id at `/v1/models` |
| vLLM | `http://127.0.0.1:8000` | the served model id |

Thinking is switched off by default (`chat_template_kwargs.enable_thinking=false`, which
llama.cpp, vLLM and LM Studio read): with it on, Gemma 4 spent the whole reply budget on hidden
reasoning and returned nothing. If a server rejects the field, NOVA retries without it.
`NOVA_LLM_THINKING=1` turns thinking back on. An empty answer is never used as a rewrite.
Director notes are requested in the script's language (Bahasa Indonesia or English).

Measured on 4 CPU cores with Gemma 4 E2B: about 13 tokens/s, a rewrite in about 4 s, notes in
about 11 s. Every rewrite still has to pass the meaning check; in testing a natural-mode rewrite
was accepted (86% of content words kept) and an expressive-mode rewrite that added words was
rejected and replaced by the rule-based result. Only llama.cpp was run here; the other rows
follow each server's documented OpenAI-compatible API.

## Making it sound like a real person

espeak-ng sounds robotic. NOVA uses the neural Indonesian Piper voice automatically once it is
installed:

```bash
bash scripts/get-voices.sh      # ~60 MB into ~/.nova/models, SHA-256 checked, safe to re-run
```

- Voice: `id_ID-news_tts-medium` from rhasspy/piper-voices, one female speaker, 22 kHz. Its model
  card points to a Kaggle dataset for the licence; check it before commercial use.
- It speaks Indonesian. English sentences in a mixed script are read with Indonesian pronunciation.
- Piper controls rate (`length_scale`) and volume. The director's pitch and intonation range are
  applied afterwards by a WORLD pitch shift, or by the voice profile when one is selected. Piper has
  no word emphasis; the manifest reports it as "not supported".
- For the most natural sound, use "Engine voice (no profile)". A designed profile re-synthesises
  every sentence through the WORLD vocoder, which shapes the voice but costs some naturalness.
- `NOVA_PIPER_MODEL` points at a different voice; `NOVA_MODELS_DIR` moves the default folder.

### Your own voice, cloned (free, neural)

NOVA can clone a voice with **Chatterbox-TTS-Indonesian** (`grandhigh/Chatterbox-TTS-Indonesian`,
Apache-2.0, fine-tuned on Indonesian speech). It runs locally; no account or payment.

```bash
.venv/bin/pip install -r requirements-neural.txt   # PyTorch + Chatterbox, ~6 GB
export NOVA_CHATTERBOX=1 HF_HUB_DISABLE_XET=1        # weights (~3.2 GB) download on first render
.venv/bin/uvicorn nova.api:app --host 127.0.0.1 --port 8790
```

Then create a **cloned profile** from your own recording (Voice Cloning page, with the consent
form) and pick it in the Studio. The encrypted recording is decrypted to a private temp file for
each render and used as the model's reference; the neural model reproduces the voice, so NOVA
skips its WORLD conversion. Emotion maps to Chatterbox's `exaggeration`, pace to `cfg_weight`.

Recording tips for a good clone: 15-20 seconds of your normal Indonesian speaking voice, one
speaker, a quiet room, no music or echo, phone held 20-30 cm away, speak the way you want the
voiceover to sound (soft and calm in → soft and calm out). Only the first 20 seconds are used.

Speed: about 4-6x slower than real time on a 4-core CPU (18 s of audio took 96 s), much faster
on a GPU. Output carries Resemble's Perth watermark marking it as AI-generated. Designed voices
have no recording, so with this engine they use the model's default (male) voice plus WORLD
conversion; for a natural woman's voice, use a real recording.

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
| `nova/tts/` | Chatterbox (neural cloning), Piper, Sherpa-ONNX and espeak-ng engines |
| `nova/mastering.py` | Loudness, noise reduction, silence, fades, limiter |
| `nova/pipeline.py` | End-to-end generation and the manifest |
| `nova/api.py`, `web/` | FastAPI app and the studio UI |
