# NOVA status

Checked 2026-11-26 in the cloud build sandbox (Python 3.13, espeak-ng 1.51, ffmpeg).
VERIFIED means a test or a measured run shows it working. Nothing here is called production-ready.

## VERIFIED

| Feature | Evidence |
|---|---|
| Create a voice profile with consent | `test_create_save_and_reload_profile`; refusals without consent, without naming the speaker, and with a wrong relationship return 403 (`test_profile_requires_consent`) |
| Save and reload profiles | A fresh app instance reads the same profile from disk; files encrypted (speaker name absent from the bytes), mode 600; delete removes them |
| Designed voices and preview | `test_designed_profile_and_preview` (WAV served) |
| Analyse English, Indonesian and mixed scripts | `test_analyze_*` in `test_script.py` and `test_api.py` |
| Quality score with evidence | `test_quality_flags_problems_and_scores_lower`, unnatural-translation detection |
| Enhancement in three modes, meaning preserved | `test_enhance_three_modes_preserve_meaning`; changed message is rejected (`test_meaning_check_rejects_changed_message`) |
| Compare original and enhanced | Word diff rebuilds the enhanced text exactly (`test_compare_original_and_enhanced`) |
| Sentence-by-sentence direction | Tone, rate, pitch, range, volume, emphasis, pause, breath (`test_director_*`) |
| Engine controls really change the audio | espeak-ng measured: pitch +4 → F0 100→118 Hz; rate 1.4 → 4.49→3.13 s; range 0.3/1.8 → 2.0/9.7 semitones; volume −6 dB → peak 0.81→0.39 |
| Generate audio with a cloned voice | `test_generate_with_cloned_voice_wav_mp3`: every sentence converted, output −16 ±1 LUFS, true peak ≤ −0.9 dBTP |
| Profile conversion hits the target | Output F0 within 25 Hz of a 220 Hz profile (`test_conversion_moves_pitch_to_profile`); designed-voice run measured 228 Hz for a 228 Hz target; formant warp identical across sentences (calibrated per base voice) |
| Multi-segment voiceover, combined | `test_generate_multi_segment`: four scenes with neutral/excited/sad/authority directions in one mastered MP3 |
| WAV and MP3 export, verified | ffprobe codec, sample rate and duration checked on every output and in tests |
| Loudness measurement | Matches ffmpeg `ebur128` (−25.49 vs −25.5 LUFS; test tolerance 0.3 LU) |
| Noise reduction only when needed | Runs only above a −50 dB noise floor (an inaudible −59 dB floor on studio TTS is left alone); a −41 dB floor was lowered 8 dB with speech level changed 0.4 dB |
| API endpoints | 13 API tests incl. validation, path traversal, API-key auth, projects CRUD |
| Indonesian Piper voice (neural) | Downloaded with `scripts/get-voices.sh`, SHA-256 matches the published LFS hash; female speaker (F0 ≈ 254 Hz) at 22 kHz, ~0.8 s to render 9 s; rate changes length; `test_piper.py` (3 tests) incl. a full API job with WAV/MP3 |
| Neural voice cloning (Chatterbox-TTS-Indonesian) | `test_chatterbox.py` through the API: a consented profile from a 248 Hz reference produced a 230 Hz clone (the model's default voice is 114 Hz); identity from the neural clone, no WORLD conversion. Full script: 18.5 s rendered in 96 s on 4 CPU cores. Runs only with `NOVA_CHATTERBOX_TEST=1` (not in CI: ~9 GB of downloads) |
| Local LLM for rewrite and director notes | llama.cpp `llama-server` built from source with Gemma 4 E2B Q4_K_M (checksum-verified): `test_real_local_llm` passed via `NOVA_LLM_TEST_URL`; rewrite about 4 s, notes about 11 s in Bahasa Indonesia; the meaning gate accepted one rewrite and rejected one. `test_llm.py` covers thinking-off, retry when the field is rejected, reasoning-only replies, URL forms and the gate against a fake server (runs in CI) |
| Director pitch on engines without pitch control | WORLD pitch shift: +3 st and range ×1.4 measured as >12% higher F0 and a wider range (`test_pitch_shift_for_engines_without_pitch`) |
| Set up from the app (Settings page) | Live browser run at 390 px from a clean data folder with no AI variables: llama.cpp chosen, models loaded, test reply in 1.4 s; Indonesian voice downloaded and verified from the button; Chatterbox switched on and loaded; AI notes and an accepted AI rewrite (93% content words) shown; a render used Piper for a designed voice. No JS errors. `test_settings.py` (4 tests): saved settings reload, key encrypted and hidden, bad URLs refused, errors explained, voice install with checksum failure path, Chatterbox toggle needs the package |
| Master an uploaded voiceover | Live: an 11.8 s ElevenLabs MP3 went −18.3 → −14.05 LUFS, true peak −1.74 → −1.0 dBTP, length unchanged, no noise reduction (ffmpeg ebur128: −14.1 LUFS, −1.0 peak); UI at 390 and 1440 px, no JS errors. `test_master.py`: target loudness, peaks, upload deleted, bad files rejected. Long files: a 4 min 14 s file mastered in 19.6 s at 1.5 GB peak memory (the earlier limiter needed ~9 GB and was killed); very quiet sources (+8.6 dB needed) stop about 0.75 LU short of target rather than limit harder |
| LSKhan Studio autopilot bridge | The real plan `auto-2026-11-26` (read from the Studio database, not committed) parsed from JSON and from the "Salin naskah" text identically: 7 scenes, 10 placeholders; rendering refused until all were answered. Live UI at 390 and 1440 px with a test plan: missing answers highlighted and refused, then rendered and verified, timing table with a speed tip, no JS errors. `test_lskhan.py` (5 tests). The scheduled tasks were not changed |
| Free daily voice (designed voice on Chatterbox) | Synthetic reference (Chatterbox default voice reshaped to the Soft Young Indonesian Woman preset) cloned by Chatterbox: 225-241 Hz female. Full 7-scene plan via `python -m nova.daily`: 64.8 s at first; trimming engine edge silence gave 57.3 s; time-stretch 1.25x and pause scale 0.6 gave 45.7 s, -14.2 LUFS, about 4.5 min on 4 CPU cores. `test_daily.py` (3), time-stretch test. Not rated by a listener yet |
| Python 3.11 (the cloud task's Python) | Fresh 3.11 venv: `pip install -r requirements-neural.txt` resolves (numpy 1.26.4, fastapi 0.163.2, starlette 0.52.1); full suite 52 passed, 2 skipped; `nova.daily --engine chatterbox-id` rendered 45.65 s (ffprobe 45.67 s). The first scheduled test failed because numpy>=2 and fastapi==0.165 (starlette 1.x) conflicted with chatterbox-tts and gradio |
| Android app compatibility (`/api/voice-director`) | Request and response fields read from the app's `MainActivity.kt` (repo `nova-voice-studio-android`, read only). Live: NOVA on port 8013, the app's exact JSON over HTTP: voices listed; produce returned `status: success`, `nova_android_….wav`, 5.17 s at 48 kHz; the downloaded file starts `RIFF…WAVE` (the app's own check), ffprobe pcm_s16le 48 kHz 5.167 s; an unknown voice returned 404 with `detail`. `test_voice_director.py` (5 tests). Not run on a phone: no Android device or emulator here |
| Studio UI, phone and desktop | `design-check` on all 9 routes at 390 and 1440 px, dark: 0 errors. A Playwright run of analyse → enhance → direct → select voice → generate → download had no JS errors at both widths |

## IMPLEMENTED, NOT VERIFIED

- **Sherpa-ONNX engine.** The package installs and imports; no Sherpa model was downloaded, so no audio was produced with it.
- **How natural the voices sound to a listener.** Measurements are objective. The owner listened to the Piper samples and rejected them (robotic, wrong accent). Chatterbox has not yet been rated by a listener, nor tested with a real human reference recording.
- **LLM through Ollama, LM Studio or vLLM.** Only llama.cpp was run; the others use the same OpenAI-compatible API but were not started here.
- **Browser recording.** MediaRecorder upload decoded through ffmpeg; the headless check has no microphone.

## LIMITS (by design, stated in the UI and manifest)

- espeak-ng is robotic; it is the fallback when the Piper voice is not installed.
- The Piper voice speaks Indonesian only and has no word-emphasis control.
- Without Chatterbox, cloning is WORLD signal processing: it matches pitch, intonation, vocal tract and breathiness, not fine timbre.
- Chatterbox is slow on CPU (4-6x real time) and needs ~9 GB of disk for PyTorch and weights.
- Accent and pronunciation of a recording are recorded as *declared*; measuring them needs a speech recogniser.
