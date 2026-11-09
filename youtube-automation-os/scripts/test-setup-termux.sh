#!/data/data/com.termux/files/usr/bin/bash
# CI test for scripts/setup.sh inside the termux/termux-docker image (a real Termux userland,
# Android's Python, no prebuilt wheels): install, self-test, idempotent re-run, then the full test suite.
set -euxo pipefail

echo "deb https://packages-cf.termux.dev/apt/termux-main stable main" > "$PREFIX/etc/apt/sources.list"
for attempt in 1 2 3; do
    apt-get update -q >/dev/null && apt-get install -y -q python python-pip python-pillow clang >/dev/null && break
    [[ $attempt == 3 ]] && exit 1
    sleep 10
done

rm -rf "$HOME/yt"; cp -r /mnt/repo/youtube-automation-os "$HOME/yt"; cd "$HOME/yt"
rm -rf .venv .env token.json

bash scripts/setup.sh | tee /tmp/first.log
grep -q "Self-test passed" /tmp/first.log
test "$(stat -c %a .env)" = 600
grep -q '^YOUTUBE_DRY_RUN=true$' .env

# Idempotent: second run installs nothing and keeps .env.
echo "# keep me" >> .env
bash scripts/setup.sh | tee /tmp/second.log
grep -q "Dependencies already installed" /tmp/second.log
grep -q "# keep me" .env

bash scripts/setup.sh check | grep -q "Authorize once"

# The whole suite on Android's Python.
.venv/bin/python -m pip install -q pytest==9.2.0
.venv/bin/python -m pytest -q -p no:cacheprovider
echo "termux setup test passed"
