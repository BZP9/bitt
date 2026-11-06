# bitt

Read AGENTS.md before any change. What bitt is: `docs/v2/charter.md` (judge every feature by it). The contract: the cards (`spec/cards/`, normative) + `docs/v2/` (`docs/v2/kernel.md` = the
kernel mechanics). **Building:** the rebuild is `docs/v2/rebuild.md` (P1–P7, on the kept core; the
old code is at the local tag `pre-foundation`). The old `v1.0` tag is history. Work state: `_output/STATE.md` (gitignored).
Tests: `scripts/pg_throwaway.sh start`, then `scripts/conformance.sh` (memory + Postgres; every store is Postgres).

## Rules every session needs
- Never point tests or the conformance suite at a live database: Postgres tests use the throwaway cluster only (`backend.py` refuses the
  work DSN).
- **bitt does only hard checks** (charter guarantee 9): a rule refuses or warns only on an exact fact of the record; a score
  against a bar (similarity, agreement, outliers) is a module an agent runs, its result a hint, never a bitt rule.
- No company or private data in this repo (it is published as a public snapshot): synthetic names in scenarios and docs.
- Every scenario the owner describes (how they will use the db, a verb or a cycle) is saved in `docs/v2/scenarios.md` the same
  session; a design change is agreed only after walking that list (AGENTS.md "A scenario or a design change").
- **Stores hold real work from v2.0.1 on** (owner 11-06): a change to the store's shape ships a migration (AGENTS.md "Changing the
  store's shape"); no aliases or back-compat in the code itself: replace, then delete. Release = `bitt` (a tag, your store);
  dev = `uv run bitt` / `bitt-dev` here (the dev store on the throwaway cluster, .envrc): never the personal store (README "Release and dev").
- A rule change = card + kernel + spec + a replay assert + a mutation in `conformance/mutate.py`, in one commit; every change ships a
  test that fails without it. Tools are built in
  src/bitt/tools/ (AGENTS.md "Building a tool"); a card no tool implements is refused, never faked. Skills live only in SKILL.md: a release
  syncs its own; a dev tree never does (scripts/sync_skills.py on purpose).
