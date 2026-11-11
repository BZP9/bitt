#!/usr/bin/env bash
# A throwaway Postgres cluster for tests: data in .pg/ (gitignored), port 55432, trust auth on localhost only.
#   scripts/pg_throwaway.sh start | stop | dsn
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; DATA="$ROOT/.pg/data"; PORT="${BITT_PG_PORT:-55432}"
case "${1:-}" in
  start)
    if [ ! -d "$DATA" ]; then initdb -D "$DATA" -A trust -U bitt >/dev/null; fi
    pg_ctl -D "$DATA" -o "-p $PORT -k /tmp -c listen_addresses=localhost" -l "$ROOT/.pg/log" -w start >/dev/null
    echo "postgresql://bitt@localhost:$PORT/postgres" ;;
  stop) pg_ctl -D "$DATA" -m fast -w stop >/dev/null && echo stopped ;;
  dsn)  echo "postgresql://bitt@localhost:$PORT/postgres" ;;
  *) echo "usage: $0 start|stop|dsn" >&2; exit 2 ;;
esac
