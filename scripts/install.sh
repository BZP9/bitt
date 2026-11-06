#!/usr/bin/env bash
# Set bitt up on this machine for real use (scenarios.md G14): your store, the `bitt` command in every terminal, its settings.
#   1. a bitt Postgres in ~/.bitt/pg on port 55433 (scripts/store.sh), its schema (bitt init)
#   2. `bitt` on your PATH (uv tool install --editable: it always runs this checkout)
#   3. ~/.config/bitt/env.zsh with BITT_DSN, BITT_BLOBS, BITT_JOBS, BITT_ENVS (rewritten by every install)
#   4. one line in ~/.zshrc that sources it (added once; nothing else in ~/.zshrc is touched)
# Run again any time: every step is idempotent. Undo: delete the line in ~/.zshrc, `uv tool uninstall bitt`, scripts/store.sh stop.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; CONF="$HOME/.config/bitt"; ENVF="$CONF/env.zsh"
DSN="$("$ROOT/scripts/store.sh" start)"
echo "store: $DSN"
uv tool install --editable "$ROOT" --force >/dev/null 2>&1 && echo "bitt on PATH: $(command -v bitt || echo "$HOME/.local/bin/bitt")"
mkdir -p "$CONF" "$HOME/.bitt/blobs" "$HOME/.bitt/jobs"
cat > "$ENVF" <<ENV
# bitt (written by $ROOT/scripts/install.sh; rerun it rather than editing)
export BITT_DSN="$DSN"
export BITT_BLOBS="\$HOME/.bitt/blobs"
export BITT_JOBS="\$HOME/.bitt/jobs"
export BITT_ENVS="\$HOME/.config/bitt/envs.yaml"
bitt-store() { "$ROOT/scripts/store.sh" "\$@"; }     # bitt-store start | stop | status | backup
ENV
echo "settings: $ENVF"
LINE="[ -f \"$ENVF\" ] && source \"$ENVF\"   # bitt"
if ! grep -qF "$ENVF" "$HOME/.zshrc" 2>/dev/null; then
  printf '\n%s\n' "$LINE" >> "$HOME/.zshrc"; echo "~/.zshrc: added one line that sources it"
else
  echo "~/.zshrc: already sources it"
fi
BITT_DSN="$DSN" uv run --project "$ROOT" bitt --as usr init
echo "done: open a new terminal (or: source $ENVF), then: bitt task new <name> \"<problem>\""
