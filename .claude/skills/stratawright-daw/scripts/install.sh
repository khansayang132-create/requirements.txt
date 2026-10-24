#!/usr/bin/env bash
# Install the stratawright-daw skill for Claude Code on this machine (all projects),
# and build a zip for claude.ai (Settings → Capabilities → Skills → Upload).
# Safe to re-run: it replaces the installed copy with this one.
#   bash install.sh            # install to ~/.claude/skills and write ./stratawright-daw.zip
#   bash install.sh --zip-only # only build the zip
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAME="$(basename "$SRC")"
OUT_ZIP="${ZIP_OUT:-$PWD/$NAME.zip}"

if [ "${1:-}" != "--zip-only" ]; then
  DEST="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}/$NAME"
  mkdir -p "$(dirname "$DEST")"
  rm -rf "$DEST.tmp"
  cp -R "$SRC" "$DEST.tmp"
  find "$DEST.tmp" -name '__pycache__' -type d -prune -exec rm -rf {} +
  rm -rf "$DEST"
  mv "$DEST.tmp" "$DEST"
  chmod +x "$DEST/scripts/daw.py"
  echo "Installed: $DEST"
fi

python3 - "$SRC" "$OUT_ZIP" <<'PY'
import os, sys, zipfile
src, out = sys.argv[1], sys.argv[2]
name = os.path.basename(src)
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for root, dirs, files in os.walk(src):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for f in sorted(files):
            if f.endswith(".zip"):
                continue
            p = os.path.join(root, f)
            z.write(p, os.path.join(name, os.path.relpath(p, src)))
print("Zip for claude.ai:", out)
PY
