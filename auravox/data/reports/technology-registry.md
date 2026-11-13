# Voice technology registry (checked 2026-11-13)

Nothing here is installed automatically.

| Technology | Capabilities | Code licence | Weights licence | Hardware | Installed here | Status | Limits |
|---|---|---|---|---|---|---|---|
| [eSpeak NG](https://github.com/espeak-ng/espeak-ng) | tts, multilingual, phoneme_extraction, emotion(prosody) | GPL-3.0 | none (rule-based) | any CPU | python module espeakng_loader | PASS | robotic formant voice |
| [Piper (piper1-gpl)](https://github.com/OHF-Voice/piper1-gpl) | tts, multilingual, phoneme_alignment | GPL-3.0 | per voice: mostly CC-BY-4.0 / CC-BY-NC-SA / MIT; check MODEL_CARD | CPU (real-time on 1 core) | python module piper | BLOCKED | no emotion control beyond rate/noise; models on huggingface.co |
| [Kokoro-82M (kokoro-onnx)](https://github.com/thewh1teagle/kokoro-onnx) | tts, multilingual(limited) | MIT (runtime) | Apache-2.0 | CPU | not installed | NOT INSTALLED | ~340 MB model from GitHub releases; no phoneme timing API |
| [Coqui XTTS-v2](https://github.com/idiap/coqui-ai-TTS) | tts, multilingual, authorized_voice_cloning, emotion(reference) | MPL-2.0 (code) | Coqui Public Model License (non-commercial) | GPU recommended (4+ GB) | not installed | NOT INSTALLED | weights non-commercial; 1.8 GB |
| [F5-TTS](https://github.com/SWivid/F5-TTS) | tts, authorized_voice_cloning | MIT (code) | CC-BY-NC-4.0 | GPU | not installed | NOT INSTALLED | non-commercial weights |
| [Chatterbox](https://github.com/resemble-ai/chatterbox) | tts, emotion(exaggeration), authorized_voice_cloning | MIT | MIT | GPU recommended | not installed | NOT INSTALLED | English-first; watermarking built in |
| [OpenVoice v2](https://github.com/myshell-ai/OpenVoice) | voice_conversion, speech_to_speech, authorized_voice_cloning | MIT | MIT | GPU recommended | not installed | NOT INSTALLED | tone-colour converter; needs a base TTS |
| [RVC](https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI) | voice_conversion, speech_to_speech | MIT | per trained model | GPU | not installed | NOT INSTALLED | training per voice; consent required |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | speech_recognition, word_timestamps | MIT | MIT (OpenAI Whisper) | CPU ok (small/base) | not installed | NOT INSTALLED | models download from huggingface.co |
| [Montreal Forced Aligner](https://github.com/MontrealCorpusTools/Montreal-Forced-Aligner) | forced_alignment, phoneme_extraction | MIT | acoustic models per language (various) | CPU | not installed | NOT INSTALLED | conda install; models downloaded separately |
| [pyannote.audio](https://github.com/pyannote/pyannote-audio) | speaker_diarization, speaker_identification, vad | MIT | gated on huggingface.co (accept terms) | GPU recommended | not installed | NOT INSTALLED | needs a HF token for gated weights |
| [Silero VAD](https://github.com/snakers4/silero-vad) | vad | MIT | MIT | CPU | not installed | NOT INSTALLED | model via torch hub / pip package |
| [Demucs](https://github.com/facebookresearch/demucs) | audio_separation | MIT | MIT | GPU recommended | not installed | NOT INSTALLED | archived upstream (2025) |
| [DeepFilterNet](https://github.com/Rikorose/DeepFilterNet) | audio_enhancement, denoise | MIT/Apache-2.0 | MIT/Apache-2.0 | CPU | not installed | NOT INSTALLED | Rust build for some platforms |
| [AudioCraft (AudioGen/MusicGen)](https://github.com/facebookresearch/audiocraft) | sound_effects, music | MIT (code) | CC-BY-NC-4.0 | GPU | not installed | NOT INSTALLED | non-commercial weights |
| [FFmpeg (loudnorm, acompressor, equalizer)](https://ffmpeg.org) | audio_mastering, export | LGPL/GPL | n/a | CPU | /usr/bin/ffmpeg | NOT TESTED | - |
| [AURAVOX viseme mapper + HUMANVERSE/Blender](this repository) | lip_synchronization | MIT | n/a | CPU | built in | NOT TESTED | needs phoneme timing |
