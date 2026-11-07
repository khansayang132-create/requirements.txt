#!/usr/bin/env bash
# PostgreSQL backup / restore / migration helpers for the docker compose stack.
#   scripts/db.sh backup [dir]        pg_dump (custom format) -> dir/promovent-<UTC timestamp>.dump
#   scripts/db.sh restore <file>      restore into the running database (drops existing objects first)
#   scripts/db.sh migrate             alembic upgrade head
#   scripts/db.sh rollback <revision> alembic downgrade to <revision> (take a backup first)
# Rollback strategy: every migration has a downgrade; before upgrading production, run `backup`,
# then `migrate`; if the release must be reverted, `rollback <previous revision>` or `restore` the dump.
set -euo pipefail
cd "$(dirname "$0")/.."
dc() { docker compose "$@"; }
case "${1:-}" in
  backup)
    dir="${2:-backups}"; mkdir -p "$dir"
    f="$dir/promovent-$(date -u +%Y%m%dT%H%M%SZ).dump"
    dc exec -T postgres pg_dump -U promovent -d promovent -Fc > "$f"
    [ -s "$f" ] || { echo "backup is empty" >&2; exit 1; }
    dc exec -T postgres pg_restore --list < "$f" > /dev/null   # verify the archive is readable
    echo "$f"
    ;;
  restore)
    f="${2:?usage: restore <file>}"; [ -s "$f" ] || { echo "no such backup: $f" >&2; exit 1; }
    dc exec -T postgres pg_restore -U promovent -d promovent --clean --if-exists --no-owner < "$f"
    echo "restored $f"
    ;;
  migrate)  dc run --rm --no-deps backend migrate ;;
  rollback) dc run --rm --no-deps --entrypoint alembic backend downgrade "${2:?usage: rollback <revision>}" ;;
  *) sed -n '2,9p' "$0"; exit 2 ;;
esac
