#!/usr/bin/env bash
# Keep the engineering agency's worker running in the background of a Claude Code session.
#
#   scripts/agency-live.sh start    start the worker unless one is already running, then print a summary
#   scripts/agency-live.sh status   is it running? latest missions and anything waiting for approval
#   scripts/agency-live.sh stop     stop it (SIGTERM; the worker finishes its current step and exits)
#
# The SessionStart hook runs `start` in every cloud session, so the worker runs the health playbook
# straight away and then every AGENCY_LIVE_EVERY seconds, and resumes missions you have approved. It never
# approves anything: work that needs approval waits for `python -m agency approve ...`.
#
# Environment (all optional):
#   AGENCY_LIVE_PLAYBOOK  scheduled playbook (default health; empty = only resume approved missions)
#   AGENCY_LIVE_EVERY     seconds between scheduled runs (default 3600)
#   AGENCY_LIVE_PYTHON    interpreter (default .venv/bin/python)
#   AGENCY_LIVE_DB        state database (default agency/out/agency.db); pid and log files sit next to it
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${AGENCY_LIVE_PYTHON:-$ROOT/.venv/bin/python}"
DB="${AGENCY_LIVE_DB:-$ROOT/agency/out/agency.db}"
DIR="$(dirname "$DB")"
PIDFILE="$DIR/worker.pid"
LOG="$DIR/worker.log"
PLAYBOOK="${AGENCY_LIVE_PLAYBOOK-health}"
EVERY="${AGENCY_LIVE_EVERY:-3600}"

running() { [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; }

summary() {
  if running; then
    echo "agency worker: running (pid $(cat "$PIDFILE"), playbook=${PLAYBOOK:-none}, every ${EVERY}s, log $LOG)"
  else
    echo "agency worker: not running (start: bash scripts/agency-live.sh start)"
  fi
  [ -f "$DB" ] || return 0
  local missions
  missions="$(cd "$ROOT" && "$PY" -m agency --db "$DB" missions 2>/dev/null || true)"
  [ -n "$missions" ] || return 0
  echo "latest missions:"
  echo "$missions" | tail -n 5 | sed 's/^/  /'
  if echo "$missions" | grep -q "NEEDS_APPROVAL"; then
    echo "waiting for approval (show ID, then approve TASK_ID / approve-plan ID, then resume ID):"
    echo "$missions" | grep "NEEDS_APPROVAL" | sed 's/^/  /'
  fi
}

case "${1:-status}" in
  start)
    [ -x "$PY" ] || { echo "agency worker: .venv missing; run bash scripts/agency-setup.sh" >&2; exit 1; }
    mkdir -p "$DIR"
    if ! running; then
      args=(-m agency --db "$DB" worker --every "$EVERY")
      [ -n "$PLAYBOOK" ] && args+=(--playbook "$PLAYBOOK")
      # setsid + closed stdio + disown: the worker outlives this script and the hook that started it.
      # No ( subshell ) here: a subshell waits for its background job, which would hang the hook.
      cd "$ROOT"
      setsid nohup "$PY" "${args[@]}" >>"$LOG" 2>&1 </dev/null &
      echo $! >"$PIDFILE"
      disown
      sleep 1
      running || { echo "agency worker: failed to start; see $LOG" >&2; tail -n 20 "$LOG" >&2; exit 1; }
    fi
    summary ;;
  status)
    summary
    running ;;
  stop)
    if running; then
      kill -TERM "$(cat "$PIDFILE")"
      for _ in $(seq 1 30); do running || break; sleep 1; done
    fi
    rm -f "$PIDFILE"
    echo "agency worker: stopped" ;;
  *)
    echo "usage: $0 [start|status|stop]" >&2; exit 2 ;;
esac
