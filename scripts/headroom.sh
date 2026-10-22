#!/usr/bin/env bash
# Headroom (context compression) for Claude Code sessions on this repo.
#
#   scripts/headroom.sh setup   install Headroom if missing and start its proxy
#   scripts/headroom.sh mcp     same, then serve Headroom's MCP tools over stdio
#   scripts/headroom.sh status  is the proxy up?
#
# The upload beacon is always off. The proxy binds to 127.0.0.1 only.
set -euo pipefail

HR_HOME="${HEADROOM_VENV:-$HOME/.cache/lskhan-headroom}"
PORT="${HEADROOM_PORT:-8765}"
VERSION="0.41.0"
export HEADROOM_BEACON=off DO_NOT_TRACK=1
export NO_PROXY="127.0.0.1,localhost${NO_PROXY:+,$NO_PROXY}" no_proxy="127.0.0.1,localhost${no_proxy:+,$no_proxy}"

install() {
  mkdir -p "$(dirname "$HR_HOME")"
  exec 9>"$HR_HOME.lock"
  flock 9  # the session hook and the MCP server may both get here first
  if [ ! -x "$HR_HOME/bin/headroom" ]; then
    echo "installing headroom-ai $VERSION (about a minute)..."
    python3 -m venv "$HR_HOME"
    "$HR_HOME/bin/pip" install -q --disable-pip-version-check "headroom-ai[proxy]==$VERSION"
  fi
  flock -u 9
}

healthy() { curl -s -m 2 --noproxy '*' "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; }

start_proxy() {
  healthy && return 0
  nohup "$HR_HOME/bin/headroom" proxy --host 127.0.0.1 --port "$PORT" >"$HR_HOME.proxy.log" 2>&1 &
  for _ in $(seq 1 60); do healthy && return 0; sleep 1; done
  echo "headroom proxy did not come up; see $HR_HOME.proxy.log" >&2
  return 1
}

case "${1:-}" in
  setup)
    install && start_proxy && echo "headroom ready on 127.0.0.1:$PORT" ;;
  mcp)
    # stdout belongs to the MCP protocol, so everything else goes to stderr.
    { install && start_proxy; } >&2
    exec "$HR_HOME/bin/headroom" mcp serve --proxy-url "http://127.0.0.1:$PORT" ;;
  status)
    if healthy; then echo "headroom proxy up on 127.0.0.1:$PORT"; else echo "headroom proxy down"; exit 1; fi ;;
  *)
    echo "usage: $0 setup|mcp|status" >&2; exit 2 ;;
esac
