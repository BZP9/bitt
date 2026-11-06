#!/usr/bin/env bash
# Your real bitt store (scenarios.md G14): a Postgres cluster of its own, outside the repo, for real work. Never the test cluster
# (scripts/pg_throwaway.sh, port 55432) and never the live work database. Trust auth on localhost only.
#   scripts/store.sh start | stop | status | dsn | backup
set -euo pipefail
HOME_="${BITT_HOME:-$HOME/.bitt}"; DATA="$HOME_/pg"; PORT="${BITT_STORE_PORT:-55433}"; DB=bitt
DSN="postgresql://bitt@localhost:$PORT/$DB"
case "${1:-}" in
  start)
    mkdir -p "$HOME_"
    if [ ! -d "$DATA" ]; then initdb -D "$DATA" -A trust -U bitt >/dev/null; fi
    if ! pg_ctl -D "$DATA" status >/dev/null 2>&1; then
      pg_ctl -D "$DATA" -o "-p $PORT -k /tmp -c listen_addresses=localhost" -l "$HOME_/pg.log" -w start >/dev/null
    fi
    psql -h localhost -p "$PORT" -U bitt -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$DB'" | grep -q 1 \
      || psql -h localhost -p "$PORT" -U bitt -d postgres -qc "CREATE DATABASE $DB" >/dev/null
    echo "$DSN" ;;
  stop)   pg_ctl -D "$DATA" -m fast -w stop >/dev/null && echo stopped ;;
  status) pg_ctl -D "$DATA" status >/dev/null 2>&1 && echo "running: $DSN" || echo "stopped ($DATA)" ;;
  dsn)    echo "$DSN" ;;
  backup)
    mkdir -p "$HOME_/backups"; f="$HOME_/backups/bitt-$(date +%Y%m%d-%H%M%S).dump"
    pg_dump -h localhost -p "$PORT" -U bitt -Fc "$DB" -f "$f" && echo "$f" ;;
  *) echo "usage: $0 start|stop|status|dsn|backup" >&2; exit 2 ;;
esac
