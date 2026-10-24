#!/usr/bin/env bash
# Build LSKhan Studio's web page into studio/prebuilt/, then commit studio/prebuilt/.
# Run it on a computer or in CI after changing anything `run.sh hash` covers. Needs jac-client
# (pip install jac-client==0.3.25) and the bot's packages (bash studio/run.sh setup), because the
# build imports the server code; jac fetches its own bun.
# It is a PWA build on purpose: with manifest.json in the dist, jac serves the prebuilt JS as-is.
# A plain web build makes jac rebuild on the first page request, which needs bun, and bun doesn't
# run on Android. The phone only serves the result (run.sh).
set -euo pipefail

STUDIO_DIR=$(cd "$(dirname "$0")" && pwd)
JAC="${JAC:-jac}"
cd "$STUDIO_DIR"

rm -rf .jac/client/dist  # jac reuses any existing client.*.js, even a stale one
"$JAC" install
"$JAC" build --client pwa main.jac

rm -rf prebuilt
mkdir prebuilt
cp .jac/client/dist/* prebuilt/
rm -f prebuilt/*.map
bash run.sh hash > prebuilt/SOURCE_HASH
echo "✅ Built studio/prebuilt/ ($(du -sh prebuilt | cut -f1)). Commit it."
