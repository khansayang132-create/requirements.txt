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
| Noise reduction only when needed | Clean audio untouched; a −41 dB noise floor lowered 8 dB with speech level changed 0.4 dB |
| API endpoints | 13 API tests incl. validation, path traversal, API-key auth, projects CRUD |
| Studio UI, phone and desktop | `design-check` on all 9 routes at 390 and 1440 px, dark: 0 errors. A Playwright run of analyse → enhance → direct → select voice → generate → download had no JS errors at both widths |

## IMPLEMENTED, NOT VERIFIED

- **Piper and Sherpa-ONNX engines.** The packages install and import; model downloads (Hugging Face, GitHub releases) are blocked by the sandbox proxy, so no audio was produced with them.
- **LLM enhancement and notes.** The client and the meaning-check gate exist; no local GGUF model or server was available.
- **Browser recording.** MediaRecorder upload decoded through ffmpeg; the headless check has no microphone.

## LIMITS (by design, stated in the UI and manifest)

- espeak-ng is robotic. Natural, human-sounding speech needs a neural voice (README, "Making it sound like a real person").
- The built-in cloning is WORLD signal processing: it matches pitch, intonation, vocal tract and breathiness, not fine timbre.
- Accent and pronunciation of a recording are recorded as *declared*; measuring them needs a speech recogniser.
