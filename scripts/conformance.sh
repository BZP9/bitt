#!/usr/bin/env bash
# The whole suite on every backend: pytest, both replays, and the mutation harness (memory).
#   scripts/conformance.sh            memory + postgres (the throwaway cluster must be up: scripts/pg_throwaway.sh start)
set -uo pipefail
cd "$(dirname "$0")/.."
PG="$(scripts/pg_throwaway.sh dsn)"
psql "$PG" -Atc 'select 1' >/dev/null 2>&1 || { echo "the throwaway Postgres is not up: scripts/pg_throwaway.sh start"; exit 1; }
export BITT_PG_ADMIN_DSN="$PG"; BACKENDS="memory postgres"
fail=0
uv run -q bitt lint | tail -1 || fail=1
uv run -q pytest -q tests | tail -1 || fail=1
for b in $BACKENDS; do for r in vk gw; do
  [ -f conformance/replay_$r.py ] || { echo "$b $r: not rebuilt yet (docs/v2/rebuild.md)"; continue; }
  out=$(BITT_BACKEND=$b uv run -q python conformance/replay_$r.py 2>&1); rc=$?
  echo "$b $r: $(echo "$out" | grep "asserts passed" | tail -1)"; [ $rc -eq 0 ] || { fail=1; echo "$out" | grep "✗\|Error" | head -5; }
done; done
[ -f conformance/mutate.py ] || { echo "mutations: not rebuilt yet (docs/v2/rebuild.md)"; exit $fail; }
out=$(uv run -q python conformance/mutate.py 2>&1); rc=$?; echo "mutations: $(echo "$out" | tail -1)"; [ $rc -eq 0 ] || { fail=1; echo "$out" | grep "SURVIVED\|STALE\|NO TEST"; }
exit $fail
