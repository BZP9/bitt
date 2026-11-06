# Design history

The decision trail (workflow design, mock replays, four read-back reviews and their fix maps) lives outside this repo, because it cites
company data and infrastructure.

This repo carries only the results:
- `spec/cards/`: the cards (v2 since 2026-10-22; v1's cards, `tools/*/cards.yaml` and `docs/db-design.md` are in the `v1.0` tag)
- `docs/v2/`: the design (foundation.md), the kernel mechanics (kernel.md, which replaced spec/kernel-contract.md on 2026-10-30), the
  words, names and the database, worked on here from 2026-10-22
- `conformance/`: the suite that proves them

2026-10-22, the switch (v2 slice 0 closed): the v2 cards became the default; the v1 tool cards, tools, CLI commands, replays, mocks,
bundles, views, data layer, skills and evals were deleted (the v1 tools could not run without their cards). Kernel rules the v1 replays
pinned were ported to pytest tests and their mutations kept in conformance/mutate.py.

2026-10-29/30, the rebuild (docs/v2/rebuild.md, P1–P7): the design was redone from first principles (foundation.md) and rebuilt on the
kept core (kernel, control, record, names); the code before it is the local tag `pre-foundation`. Gone with it: the six verbs and the JSON
pipeline language (one `run.go`; pipelines are Python modules), cuts and drafts (versions and aliases are tags), per-task tables (one
table per output contract in `made`, with `<task>.<name>` views), `bitt.recipe` / `bitt.variable` (recipes are nodes, metrics are
`bitt.metric`), debts and waivers (nothing could create the first debt), the read cards no tool implemented, and the old docs' slices.
