# Agent memo — working on bitt

The contract: the cards (spec/cards/*.yaml) + docs/v2/ (foundation.md the design, kernel.md the kernel mechanics, words.md the words,
db.md the tables). Nothing uses this repo or its db until bitt ships: replace, then delete (no migrations, no aliases).
Problems agents hit while using bitt are GitHub issues titled `[agent] …` (`gh issue list -R BZP9/bitt-private`): read them before
feature work; a fix closes its issue with the commit.

## Changing a rule (a state, a gate, a refusal)
- [ ] The card (spec/cards/*.yaml): MIN in/out, open_in, requires
- [ ] The implementation: a kernel rule in src/bitt/control.py (kernel.KERNEL_RULES), or a tool's rule in src/bitt/tools/<tool>.py
      (its `package()`; the rules on lineage and results in tools/rules.py)
- [ ] docs/v2/*.md: the sentence that states it; regenerate the card table (`uv run python scripts/gen_appendix.py > spec/kernel-contract-cards.md`)
- [ ] A replay assert that fails without it (conformance/replay_vk.py or replay_gw.py), or a test in tests/test_rule_pins.py when no
      replay reaches it; `uv run python conformance/mutate.py --only <rule id>` must say `caught` (every rule is switched off
      automatically; a rule that is not a check gets a `SRC` patch there)
- [ ] `scripts/conformance.sh` green on memory and postgres

## Changing storage
- [ ] Graph DDL: src/bitt/sql/postgres.sql; functions and views (navigation, names, `<task>.<name>` views): src/bitt/sql/postgres_nav.sql
- [ ] Data tables: a new shape or column rule goes in src/bitt/tables.py (`shape_spec`, `FIXED`, `ddl`), never hand-written DDL; the
      Record's `make_table / add_column / insert` stay the only write path (registry, FK, dedup checks live there); sets in src/bitt/sets.py
- [ ] Append-only triggers cover every table that holds truth
- [ ] A test on both backends (`opener` fixture; `hasattr(k.rec, "db")` for a Postgres-only assert) + a `SRC` patch in conformance/mutate.py
- [ ] docs/v2/db.md updated in the same commit; regenerate docs/v2/db-tour.md (`uv run python scripts/v2_tour.py > docs/v2/db-tour.md`)

## Changing the store's shape (owner 11-06: a store holds real work from v2.0.1 on; a format change ships a migration, never a wipe)
- [ ] tests/test_storeformat.py fails when the shape changed (a bitt.* column, constraint, or what `shape_spec` gives a data table)
- [ ] Write src/bitt/sql/migrations/<n>.sql: it carries a format n-1 store to format n (ALTER / CREATE / backfill; never DROP truth)
- [ ] sql/format.json → format n with the new hashes (the failing test prints them); format_1.json never changes (adopting old stores)
- [ ] A test that builds a format n-1 store (the last tag's code: `git worktree add` + its DDL), runs `bitt migrate`, and finds the
      shape of a fresh format n store with every row kept
- [ ] The release notes (the tag's commit) say "store format n: run `bitt migrate` after `pg_dump`"

## Building a tool
- [ ] The impls and checks in src/bitt/tools/<tool>.py (`package()`, listed in tools/__init__.py); a card no tool implements is
      refused by the kernel, never faked
- [ ] Modules run through the one job protocol (tools/envs.py `write_module_job` + tools/bitt_run.py), never inside bitt; a module's
      contract is read from its one function (tools/header.py)
- [ ] Anything that orders steps (prompts in a row, a judge then a check, an eval's decision) is a pipeline module (`BITT = {"kind":
      "pipeline"}`, `b.run(...)` steps: tools/pipeline.py), never a loop in a tool. What one `run go` does (one ladder rung, its rules,
      retrying failed rows) stays in the run
- [ ] CLI in src/bitt/cli.py: short output, one `next:` line, mistakes exit 2 with what to do; tests drive `cli.main([...])` (tests/test_cli.py)
- [ ] SKILL.md blocks (`## skill: bitt`, `## skill: bitt-data`): standalone setup, the basics, report back. Skills live only there: a release's
      `bitt` syncs its own copy on every command; a dev tree never does (`uv run python scripts/sync_skills.py` on purpose; the eval
      runner does it for a run). src/bitt/skills.py; never edit the installed copies
- [ ] evals/haiku/<name>_basics.py: setup + a mechanical check, run with Qwen through opencode (`evals/run_agent_eval.py <eval>`)

## Anything that carries a name (docs/v2/names.md)
- [ ] The impl places the node on its line through `names.place` / `names.line_link` / `names.settle` (src/bitt/names.py), never a
      `line` field; display and lookup go through `names.label` / `names.ref_of` / `eng.resolve`, never a payload string
- [ ] Versions and aliases are tags (tools/tag.py), read with `names.version_of` / `names.tags`
- [ ] The SQL resolver (postgres_nav.sql `bitt.resolve`) reads names the same way: tests/test_tag.py pins them together

## A connector, a model or an endpoint (foundation.md §C3)
- [ ] An endpoint is a `module.wrap` of a connector (builtins/openai_chat.py); its key is read at run time from `key_file` into the job's
      process environment (`BITT_KEY`): never job.json, a node, a log, stdout or a fixture file in the repo
- [ ] Tests and replays use conformance/fake_openai.py, never a real endpoint (replay_gw asserts the key is in no node and no job file)

## A scenario or a design change (docs/v2/scenarios.md, words.md)
- [ ] The owner described how they would use bitt (a dataset, a run, an eval, a cycle): add a row to scenarios.md (date, what they
      said, what bitt must do, home doc, status) before acting on it, synthetic names only
- [ ] Before proposing or agreeing a design change: list the scenario rows it touches and say for each whether it still fits; a
      row it breaks is marked **conflict** until the owner settles it
- [ ] When a row's status changes (agreed → built), update it in the same commit as the code or doc
- [ ] A new or changed word: its line in words.md, in the same commit

## A hazard found (review, probe, incident)
- [ ] A test that fails before the fix (run it first), in the test file of the act it guards
- [ ] A `SRC` patch in conformance/mutate.py that switches the fix off, caught by that test
- [ ] The fix, and the doc sentence it makes true, in the same commit

## Hygiene
- [ ] Node ids are hashes of the body: never put DB-local values (seq, now()) in payload / links / stamp except `stamp.at`
- [ ] `bytes`-typed inputs are stored by hash, never inline
- [ ] Tests and replays never touch the user's stores: conftest / backend.py pin BITT_BLOBS, BITT_JOBS, BITT_ENVS, BITT_CURRENT, BITT_DSN
- [ ] git add by file, not -A, when unrelated scratch exists
