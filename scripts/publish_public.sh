#!/usr/bin/env bash
# Publish a clean, single-commit snapshot of `main` to the public mirror repo (the same pattern as trawler's and boat's).
#
# Only ever touches the LOCAL `public` branch in this (private) repo: never `main`, never another branch, never pushes `public` to
# this repo's own origin. `public` is disposable: deleted and recreated as an orphan on every run, so it carries no history.
#
# A snapshot, not real history: the private history may hold things (old notes, wrong turns) that were never meant to be public;
# one fresh commit means only today's tracked files are published, and those are checked first:
#   - the tree is clean and on `main`;
#   - tests/test_lint.py::test_no_private_data_in_tracked_files passes (home paths, private IPs, emails, keys, and the owner's
#     private words in ~/.config/bitt/private_words.txt, which is never in the repo);
#   - the target is not this repo's own origin (a force-push there would replace the private history with one commit).
#
# Usage: scripts/publish_public.sh [public-repo-url]
#   Default target: https://github.com/BZP9/bitt.git (the private working repo is BZP9/bitt-private)
#   Override always: export BITT_PUBLIC_REMOTE=...
#   BITT_PUBLISH_REF=<tag>: snapshot that tag instead of main, and push the same tag to the public repo (CI does this on every
#   pushed v* tag: .github/workflows/publish.yml)
set -euo pipefail

ROOT="${BITT_PUBLISH_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
if [ -z "${BITT_PUBLISH_ROOT:-}" ]; then          # run from a copy: checking out the tag below rewrites this file under bash
  copy="$(mktemp)"; cp "$0" "$copy"; BITT_PUBLISH_ROOT="$ROOT" exec bash "$copy" "$@"
fi
cd "$ROOT"

PUBLIC_REMOTE="${1:-${BITT_PUBLIC_REMOTE:-https://github.com/BZP9/bitt.git}}"
ORIG_BRANCH="$(git branch --show-current)"
ORIG_HEAD="$(git rev-parse HEAD)"
REF="${BITT_PUBLISH_REF:-main}"
TAG=""
if [ "$REF" != "main" ]; then
  git rev-parse -q --verify "refs/tags/$REF" >/dev/null || { echo "refusing: $REF is not a tag here" >&2; exit 1; }
  git merge-base --is-ancestor "$REF" origin/main 2>/dev/null || git merge-base --is-ancestor "$REF" main || {
    echo "refusing: tag $REF is not on main" >&2; exit 1; }
  TAG="$REF"
fi
norm() { echo "$1" | sed -E 's#^git@github.com:#https://github.com/#; s#\.git$##; s#/$##' | tr 'A-Z' 'a-z'; }

[ -z "$(git status --porcelain)" ] || { echo "working tree has uncommitted changes: commit before publishing" >&2; exit 1; }
[ "$(norm "$PUBLIC_REMOTE")" != "$(norm "$(git remote get-url origin)")" ] || {
  echo "refusing: $PUBLIC_REMOTE is this repo's own origin (rename the private repo first, e.g. to bitt-private)" >&2; exit 1; }
[ -f "${BITT_PRIVATE_WORDS:-$HOME/.config/bitt/private_words.txt}" ] || {
  echo "refusing: no private word list (~/.config/bitt/private_words.txt); the private-data check would be generic only" >&2; exit 1; }

git checkout -q --detach "$REF"                                       # check the tree that will be published
echo "[publish] checking tracked files for private data ($REF)"
BITT_NO_SKILL_SYNC=1 uv run -q pytest -q tests/test_lint.py -k private_data || { echo "refusing: private data found (above)" >&2; exit 1; }

echo "[publish] snapshotting $REF -> local 'public' branch (reset each run)"
git branch -D public >/dev/null 2>&1 || true
git checkout -q --orphan public
git commit -q -m "bitt${TAG:+ $TAG}: an honest record of ML work

Data, modules, prompts, runs, verdicts and versions in one append-only, content-addressed record; every write checked against
cards (the rules), so agents do the work and nothing fools you. One page: docs/v2/charter.md."

echo "[publish] public -> $PUBLIC_REMOTE (main, force${TAG:+, tag $TAG})"
git push --force "$PUBLIC_REMOTE" public:main
[ -z "$TAG" ] || git push --force "$PUBLIC_REMOTE" "public:refs/tags/$TAG"

echo "[publish] back to ${ORIG_BRANCH:-$ORIG_HEAD}; 'public' left in place for inspection, never pushed to origin"
git checkout -q "${ORIG_BRANCH:-$ORIG_HEAD}"
