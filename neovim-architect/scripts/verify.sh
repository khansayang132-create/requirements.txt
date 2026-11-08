#!/usr/bin/env bash
# Runs the 12 verification tests against the INSTALLED config and writes
# reports/verification-report.md. Every status comes from an actual run.
# Exit code: 0 if no FAIL, 1 otherwise.
# shellcheck source-path=SCRIPTDIR source=lib.sh
source "$(dirname "$0")/lib.sh"
case ":$PATH:" in *":$LOCAL_BIN:"*) ;; *) export PATH="$LOCAL_BIN:$PATH" ;; esac
detect_env

REPORT="${REPORT_OUT:-$ARCH_ROOT/reports/verification-report.md}"
mkdir -p "$LOG_DIR"
RAW="$LOG_DIR/verify-$(ts_now).log"
declare -a ROWS=()
FAILS=0

record() { # id name status detail
  ROWS+=("| $1 | $2 | **$3** | ${4//|//} |")
  [[ "$3" == "FAIL" ]] && FAILS=$((FAILS + 1))
  printf '%-12s %-10s %s\n' "$2" "$3" "$4" | tee -a "$RAW"
}

run_lua() { # id name -> parses RESULT line
  local out line
  out="$(cd "$ARCH_ROOT" && timeout 300 nvim --headless -c "lua TEST='$1'" -c "luafile tests/verify.lua" 2>&1 || true)"
  echo "$out" >> "$RAW"
  line="$(grep -o -m1 "RESULT|$1|.*" <<<"$out" || true)"
  if [[ -z "$line" ]]; then record "$3" "$2" FAIL "no result (see $RAW)"; return; fi
  IFS='|' read -r _ _ status detail <<<"$line"
  record "$3" "$2" "$status" "$detail"
}

info "verification (log: $RAW)"

# 1 executable
if have nvim && version_ge "$(nvim_version)" "$NVIM_MIN"; then
  record 1 executable PASS "$(command -v nvim): $(nvim --version | head -1)"
else record 1 executable FAIL "nvim missing or older than $NVIM_MIN"; fi

# 2-10 functional (inside Neovim)
run_lua config config 2
run_lua plugins plugins 3
run_lua health health 4
run_lua lsp lsp 5
run_lua completion completion 6
run_lua search search 7
run_lua git git 8
run_lua terminal terminal 9
run_lua treesitter treesitter 10
run_lua format format 10b

# 11 startup: real TTY via script(1), median of 5 runs. Neovim 0.12 logs two
# processes; the "Embedded" one (the editor itself, which loads the config) counts.
startup_median() { # extra nvim args...
  local times=() f t
  for _ in 1 2 3 4 5; do
    f="$(mktemp)"
    # timeout: a hit-enter prompt (e.g. startup error) must fail the test, not hang it
    TERM=xterm-256color timeout 30 script -qec "nvim $* --startuptime $f +qa" /dev/null >/dev/null 2>&1 || true
    t="$(awk '/process: Embedded/ {e=1} e && /NVIM STARTED/ {printf "%.1f", $1}' "$f")"; rm -f "$f"
    [[ -n "$t" ]] && times+=("$t")
  done
  (( ${#times[@]} )) || return 1
  printf '%s\n' "${times[@]}" | sort -n | awk '{a[NR]=$1} END {print a[int((NR+1)/2)]}'
}
if have script; then
  if cfg="$(startup_median)"; then
    base="$(startup_median --clean || echo '?')"
    record 11 startup PASS "median ${cfg} ms with config vs ${base} ms for nvim --clean (5 TTY runs each)"
  else record 11 startup FAIL "no NVIM STARTED in 30 s (hung or crashed)"; fi
else record 11 startup "NOT TESTED" "script(1) unavailable for a TTY measurement"; fi

# 12 rollback: backup exists, has manifest, rollback can list it
latest="$(ls -1d "$BACKUP_ROOT"/*/ 2>/dev/null | sort | tail -1 || true)"
if [[ -n "$latest" && -f "$latest/MANIFEST.txt" ]] && bash "$ARCH_ROOT/scripts/rollback.sh" --list >/dev/null; then
  record 12 rollback PASS "latest backup ${latest%/}; rollback.sh --list ok"
else record 12 rollback FAIL "no backup with MANIFEST.txt under $BACKUP_ROOT"; fi

{
  echo "# Verification Report"
  echo
  echo "- Generated: $(date -Iseconds) by \`scripts/verify.sh\` (raw log: \`logs/$(basename "$RAW")\`)"
  echo "- Host: $(uname -srm), os=$OS_KIND, pkg=${PKG:-none}"
  echo "- Neovim: $(nvim --version 2>/dev/null | head -1)"
  echo
  echo "| # | Test | Status | Evidence |"
  echo "|---|---|---|---|"
  printf '%s\n' "${ROWS[@]}"
  echo
  echo "Statuses come only from the run above. PARTIAL = works, but something optional is missing (see evidence)."
} > "$REPORT"
ok "report -> $REPORT"
(( FAILS == 0 )) || { warn "$FAILS test(s) failed"; exit 1; }
