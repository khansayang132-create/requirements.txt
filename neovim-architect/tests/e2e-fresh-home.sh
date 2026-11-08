#!/usr/bin/env bash
# End-to-end test in a throwaway HOME that already has a "user" Neovim config:
#   install (fresh downloads, lockfile restore) -> foreign config backed up and
#   moved aside -> rollback restores it byte-for-byte -> re-install -> verify.
# Uses system packages already present; touches nothing in the real HOME.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export HOME; HOME="$(mktemp -d /tmp/nva-e2e.XXXXXX)"
# Drop the real ~/.local/bin and ~/.cargo/bin so Neovim & tools are installed fresh
PATH="$(tr ':' '\n' <<<"$PATH" | grep -vE '^/root/(\.local|\.cargo)/bin$' | paste -sd:)"
export PATH
unset XDG_CONFIG_HOME XDG_DATA_HOME XDG_STATE_HOME
echo "e2e HOME=$HOME"

mkdir -p "$HOME/.config/nvim"
printf '" USER-ORIGINAL-CONFIG %s\nset number\n' "$$" > "$HOME/.config/nvim/init.vim"
# shellcheck disable=SC2034  # used inside check strings (eval)
orig_sum="$(sha256sum "$HOME/.config/nvim/init.vim" | cut -d' ' -f1)"

step() { printf '\n### %s\n' "$*"; }
check() { if eval "$2"; then echo "CHECK PASS: $1"; else echo "CHECK FAIL: $1"; FAILED=1; fi; }
FAILED=0
mismatch=""

step "1. install into fresh HOME"
bash "$ROOT/scripts/install.sh" --no-learning --no-verify

export PATH="$HOME/.local/bin:$PATH"   # what install.sh adds to ~/.bashrc
check "nvim installed into fresh HOME" '[[ "$(command -v nvim)" == "$HOME/.local/bin/nvim" ]]'
check "foreign config backed up" 'ls "$HOME"/Developer/Neovim-Backups/*/.config_nvim/init.vim >/dev/null'
check "foreign config moved aside, not deleted" 'ls "$HOME"/.config/nvim.pre-architect-*/init.vim >/dev/null'
check "Architect config installed with marker" '[[ -f "$HOME/.config/nvim/.neovim-architect" ]]'
lock_mismatch() { # prints plugins whose checkout differs from lazy-lock.json
  python3 - "$ROOT/config/nvim/lazy-lock.json" "$HOME/.local/share/nvim/lazy" <<'PY'
import json, subprocess, sys
lock = json.load(open(sys.argv[1]))
for name, v in lock.items():
    head = subprocess.run(["git", "-C", f"{sys.argv[2]}/{name}", "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    if head != v["commit"]:
        print(f"{name}: {head or 'missing'} != {v['commit']}")
PY
}
mismatch="$(lock_mismatch)"
check "every plugin at its lazy-lock.json commit ($(jq -r 'keys|length' "$ROOT/config/nvim/lazy-lock.json" 2>/dev/null || echo all))" '[[ -z "$mismatch" ]]'
[[ -n "$mismatch" ]] && echo "$mismatch"

step "2. rollback to the original user config"
oldest="$(ls -1d "$HOME"/Developer/Neovim-Backups/*/ | sort | head -1)"
bash "$ROOT/scripts/rollback.sh" "${oldest%/}"
check "original init.vim restored byte-for-byte" '[[ "$(sha256sum "$HOME/.config/nvim/init.vim" | cut -d" " -f1)" == "$orig_sum" ]]'
check "Architect config kept as rolled-back copy" 'ls "$HOME"/.config/nvim.rolled-back-*/init.lua >/dev/null'

step "3. re-install (idempotent) and verify"
bash "$ROOT/scripts/install.sh" --no-packages --no-learning --no-verify
check "Architect config back in place" '[[ -f "$HOME/.config/nvim/init.lua" ]]'
REPORT_OUT="$HOME/verification-report.md" bash "$ROOT/scripts/verify.sh" || FAILED=1

echo; [[ $FAILED == 0 ]] && echo "E2E RESULT: PASS ($HOME)" || echo "E2E RESULT: FAIL ($HOME)"
exit $FAILED
