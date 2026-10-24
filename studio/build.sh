#!/usr/bin/env bash
# Build LSKhan Studio's web page into studio/prebuilt/, then commit studio/prebuilt/.
# Run it on a computer or in CI after changing main.jac, jac.toml, global.css, studio_ai.py,
# components/ or lib/. Needs jac-client (pip install jac-client==0.3.25); jac fetches its own bun.
# The phone only serves the result (run.sh), so it never needs bun, node or llvmlite.
set -euo pipefail

STUDIO_DIR=$(cd "$(dirname "$0")" && pwd)
JAC="${JAC:-jac}"
cd "$STUDIO_DIR"

rm -rf .jac/client/dist  # jac reuses any existing client.*.js, even a stale one
"$JAC" install
"$JAC" build main.jac

rm -rf prebuilt
mkdir prebuilt
cp .jac/client/dist/client.*.js .jac/client/dist/styles.css .jac/client/dist/*.woff2 prebuilt/
bash run.sh hash > prebuilt/SOURCE_HASH
echo "✅ Built studio/prebuilt/ ($(du -sh prebuilt | cut -f1)). Commit it."
