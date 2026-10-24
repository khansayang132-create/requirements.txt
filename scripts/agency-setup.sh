#!/usr/bin/env bash
# Prepare .venv so `python -m agency run health` works in a fresh Claude Code cloud session.
#
#   scripts/agency-setup.sh          create/refresh .venv (skipped when nothing changed)
#   scripts/agency-setup.sh status   is .venv ready?
#
# Installs the bot and APEX requirements plus the agency's check tools, pinned. A stamp of the
# requirement files is kept in .venv, so re-runs with unchanged requirements finish in under a second.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$ROOT/.venv"
TOOLS="pytest ruff==0.17.2 pip-audit==2.9.0 shellcheck-py==0.10.0.1 bandit==1.8.6"
PY="${AGENCY_PYTHON:-python3.13}"  # APEX's bpy wheels need 3.13

stamp() { cat "$ROOT/requirements.txt" "$ROOT/apex/requirements.txt" | sha256sum | cut -d' ' -f1; echo "$TOOLS"; }

ready() { [ -x "$VENV/bin/python" ] && [ "$(cat "$VENV/.agency-stamp" 2>/dev/null)" = "$(stamp)" ]; }

case "${1:-setup}" in
  setup)
    if ready; then echo "agency venv ready (.venv)"; exit 0; fi
    command -v "$PY" >/dev/null || { echo "agency setup: $PY not found; set AGENCY_PYTHON" >&2; exit 1; }
    exec 9>"$ROOT/.venv.lock"
    flock 9
    echo "agency setup: installing into .venv (a few minutes the first time)..."
    [ -x "$VENV/bin/python" ] || "$PY" -m venv "$VENV"
    # shellcheck disable=SC2086  # TOOLS is a list of pinned package specs
    "$VENV/bin/pip" install -q --disable-pip-version-check \
      -r "$ROOT/requirements.txt" -r "$ROOT/apex/requirements.txt" $TOOLS
    stamp > "$VENV/.agency-stamp"
    echo "agency venv ready (.venv): run .venv/bin/python -m agency run health" ;;
  status)
    if ready; then echo "agency venv ready"; else echo "agency venv missing or out of date"; exit 1; fi ;;
  *)
    echo "usage: $0 [setup|status]" >&2; exit 2 ;;
esac
