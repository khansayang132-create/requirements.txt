#!/usr/bin/env bash
# Download the Indonesian Piper voice NOVA uses by default. Safe to re-run: a file whose
# SHA-256 already matches is kept. Works on Linux and Termux (needs curl and sha256sum).
set -euo pipefail
DEST="${NOVA_MODELS_DIR:-$HOME/.nova/models}"
BASE="https://huggingface.co/rhasspy/piper-voices/resolve/main/id/id_ID/news_tts/medium"
MODEL="id_ID-news_tts-medium.onnx"
SHA="ed8f02aa593f7af6b19acbdb8142e0da0dd72f46194eb33d38e0eb10a52597e8"
mkdir -p "$DEST"
cd "$DEST"
if [ -f "$MODEL" ] && echo "$SHA  $MODEL" | sha256sum -c --status; then
  echo "OK    $DEST/$MODEL (already present, checksum matches)"
else
  curl -fSL --retry 3 -o "$MODEL.part" "$BASE/$MODEL"
  echo "$SHA  $MODEL.part" | sha256sum -c --status || { rm -f "$MODEL.part"; echo "FAIL  checksum mismatch" >&2; exit 1; }
  mv "$MODEL.part" "$MODEL"
  echo "OK    $DEST/$MODEL (downloaded, checksum verified)"
fi
curl -fsSL --retry 3 -o "$MODEL.json" "$BASE/$MODEL.json"
echo "OK    $DEST/$MODEL.json"
