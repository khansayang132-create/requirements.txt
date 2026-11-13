# Voice, sound, edit

- **Voice**: eSpeak NG through its C library with phoneme events (`hvlib/voice.py`): clear but robotic. Piper
  (neural) is supported when `piper` and a local `.onnx` voice exist (`HV_PIPER_VOICE`); its models download from
  huggingface.co, which needs approval for the download. Never clone a real person.
- **Music**: synthesised per mood (warm, sad, joyful, wonder): pad chords, plucked arpeggio, bass. Original.
- **Ambience**: park (wind + birdsong chirps), street (hum), room (soft noise).
- **Foley**: a footstep on every frame where the animation plants a foot (cues from the scene build), weight scaled
  by character height, surface by location.
- **Mix**: dialogue on its cue frame; music and ambience ducked ~10 dB under speech; peak-normalised per scene.
- **Edit** (`hv edit`): title card, scenes, credits; 0.4 s fades; light contrast/saturation pass; scale to the
  delivery profile (YouTube 1920×1080 or Shorts 1080×1920 via `deliver_resolution`); 24 fps; H.264 CRF 18 +
  AAC 192k; subtitles from the dialogue cues (SRT sidecar + mov_text track); EBU R128 two-pass loudness to
  −16 LUFS integrated, −1.5 dBTP.
