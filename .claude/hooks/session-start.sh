#!/bin/bash
# SessionStart hook for Claude Code cloud sessions: install what the tests and linters need, then start Headroom.
# Local sessions skip it. Idempotent; pip reuses what the cached container already has.
set -euo pipefail
[ "${CLAUDE_CODE_REMOTE:-}" = true ] || exit 0
cd "$CLAUDE_PROJECT_DIR"

pip() { python3 -m pip install -q --disable-pip-version-check "$@"; }
pip -r requirements.txt pytest shellcheck-py   # bot + tests/ + CI's shellcheck step
pip -r apex/requirements.txt                    # APEX (bpy needs Python 3.13)

bash scripts/headroom.sh setup
