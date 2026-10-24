#!/usr/bin/env bash
# jac-shadcn MCP server (component library, theming, project scaffolding for
# Jac UIs) for Claude Code sessions on this repo.
#
#   scripts/jac-shadcn-mcp.sh setup   install it if missing
#   scripts/jac-shadcn-mcp.sh mcp     same, then serve its MCP tools over stdio
#   scripts/jac-shadcn-mcp.sh status  is it installed, and is its API reachable?
#
# Source: github.com/SahanUday/jac_shadcn_mcp (not on PyPI), pinned to one
# reviewed commit. It makes read-only GET requests to JAC_SHADCN_BASE_URL
# (default https://jac-shadcn.jaseci.org) and writes no files.
# mcp is pinned below 2: the 2.x SDK removed the Server.list_resources
# decorator this server uses.
set -euo pipefail

JS_HOME="${JAC_SHADCN_VENV:-$HOME/.cache/lskhan-jac-shadcn}"
REPO="https://github.com/SahanUday/jac_shadcn_mcp"
COMMIT="7e61a9b27d11b3896d6e029fe60278880562ce81"
SRC="$JS_HOME/src/jac_shadcn_mcp"  # dir name matters: its pyproject finds packages in ".."
DEPS=("jaclang==0.16.7" "mcp==1.30.0")
API="${JAC_SHADCN_BASE_URL:-https://jac-shadcn.jaseci.org}"

install() {
  mkdir -p "$(dirname "$JS_HOME")"
  exec 9>"$JS_HOME.lock"
  flock 9  # the session hook and the MCP server may both get here first
  if [ ! -x "$JS_HOME/bin/jac" ] || [ "$(git -C "$SRC" rev-parse HEAD 2>/dev/null)" != "$COMMIT" ]; then
    echo "installing jac-shadcn MCP @ ${COMMIT:0:7} (about a minute)..."
    rm -rf "$JS_HOME"
    python3 -m venv "$JS_HOME"
    git clone -q "$REPO" "$SRC"
    git -C "$SRC" -c advice.detachedHead=false checkout -q "$COMMIT"
    "$JS_HOME/bin/pip" install -q --disable-pip-version-check "${DEPS[@]}"
    "$JS_HOME/bin/pip" install -q --disable-pip-version-check --no-deps -e "$SRC"
  fi
  flock -u 9
}

case "${1:-}" in
  setup)
    install && echo "jac-shadcn MCP ready ($JS_HOME)" ;;
  mcp)
    # stdout belongs to the MCP protocol, so everything else goes to stderr.
    install >&2
    exec "$JS_HOME/bin/jac" shadcn-mcp ;;
  status)
    if [ -x "$JS_HOME/bin/jac" ]; then echo "installed: $JS_HOME"; else echo "not installed"; exit 1; fi
    if curl -s -m 5 -o /dev/null "$API/registry"; then echo "API reachable: $API"
    else echo "API unreachable: $API (guides still work; component lookups will fail)"; fi ;;
  *)
    echo "usage: $0 setup|mcp|status" >&2; exit 2 ;;
esac
