#!/usr/bin/env bash
# Chromium Commander (browser agent) for Claude Code sessions on this repo.
#
#   scripts/chromium.sh setup    npm ci in chromium-commander/ (skipped when the lockfile is unchanged),
#                                and install Playwright's Chromium if it is missing
#   scripts/chromium.sh mcp      same, then serve the browser tools over stdio (the "chromium" server in .mcp.json)
#   scripts/chromium.sh doctor   environment check plus a real headless launch
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CC="$ROOT/chromium-commander"

stamp() { sha256sum "$CC/package-lock.json" | cut -d' ' -f1; }
ready() { [ -d "$CC/node_modules/playwright" ] && [ "$(cat "$CC/node_modules/.cc-stamp" 2>/dev/null)" = "$(stamp)" ]; }

setup() {
  command -v node >/dev/null || { echo "chromium setup: node (>= 20) is required" >&2; return 1; }
  exec 9>"$CC/.setup.lock"
  flock 9  # the session hook and the MCP server may both get here first
  if ! ready; then
    echo "chromium setup: installing npm dependencies..."
    (cd "$CC" && PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm ci --no-audit --no-fund --loglevel=error)
    stamp > "$CC/node_modules/.cc-stamp"
  fi
  if ! (cd "$CC" && node -e "process.exit(require('fs').existsSync(require('playwright').chromium.executablePath()) ? 0 : 1)"); then
    echo "chromium setup: downloading Playwright's Chromium..."
    (cd "$CC" && npx playwright install chromium)
  fi
  flock -u 9
}

case "${1:-}" in
  setup)
    setup && echo "chromium commander ready" ;;
  mcp)
    # stdout belongs to the MCP protocol, so everything else goes to stderr.
    setup >&2
    exec node "$CC/src/mcp-server.js" ;;
  doctor)
    setup >&2
    exec node "$CC/src/cli.js" doctor ;;
  *)
    echo "usage: $0 setup|mcp|doctor" >&2; exit 2 ;;
esac
