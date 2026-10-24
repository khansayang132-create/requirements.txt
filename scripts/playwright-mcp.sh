#!/usr/bin/env bash
# Playwright MCP (browser automation) for Claude Code sessions on this repo.
#
#   scripts/playwright-mcp.sh        serve the Playwright MCP tools over stdio
#
# Pinned version, not @latest: a new npm release can't change the tools under us.
# The browser profile is in memory (--isolated), so no logins or cookies persist.
# Screenshots and traces go to ~/.cache/lskhan-playwright, outside the repo.
set -euo pipefail

VERSION="0.0.83"
OUT="${PLAYWRIGHT_MCP_OUTPUT_DIR:-$HOME/.cache/lskhan-playwright}"
mkdir -p "$OUT"

args=(--isolated --output-dir "$OUT")

# No screen (cloud session, CI, SSH): run headless.
[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] || [ "$(uname)" = Darwin ] || args+=(--headless)

# Claude Code cloud containers ship Chromium here; use it instead of downloading one.
if [ -x /opt/pw-browsers/chromium ]; then
  args+=(--executable-path /opt/pw-browsers/chromium)
fi

# Chromium refuses to start as root with its sandbox on (cloud containers run as root).
[ "$(id -u)" != 0 ] || args+=(--no-sandbox)

# Chromium ignores HTTPS_PROXY, and cloud sessions reach the web only through it.
# TLS stays verified: the cloud proxy's CA is already in the browser trust store.
proxy="${HTTPS_PROXY:-${https_proxy:-}}"
[ -z "$proxy" ] || args+=(--proxy-server "$proxy" --proxy-bypass "127.0.0.1,localhost")

# stdout belongs to the MCP protocol; npx's own chatter goes to stderr.
exec npx -y "@playwright/mcp@$VERSION" "${args[@]}" "$@"
