# Hand-off, 2026-10-30 (evening): what is left before v2.0

> **11-01:** what is left before v2.0 is tracked in issue #10 (the list below, updated); the open design work in #2, #3, #4, #6, #7 (the walker), #8 (artifacts made from data), #9 (the scenario walk), #5 (the panel, last).

The 10-30 hand-off (H1 D15, H2 hashed labels, H3 `bitt_extra`, H4 `inspect --task`, H5 nb_train, H6 the three Qwen evals, H7 docs,
H8 the viz) is built, reviewed on Postgres and merged (main `82cb90b` and after; the brief is in git history). Every decision is
the owner's and is in `scenarios.md`; do not reopen them. Work state: `_output/STATE.md` (gitignored, on the owner's machine).

## Where it stands (main, 10-30 evening)

- **Suite:** `scripts/conformance.sh` (memory + Postgres): lint 0/0, pytest all passed, replays vk 58/58 and gw 24/24 on both backends,
  `conformance/mutate.py`: the last full sweep caught 130/130; the 4 mutations added since (first versions, two
  refusal hints) were each caught alone; run a full sweep before the tag.
- **Decided 10-30 after the hand-off:** a module's or an artifact's first version is the agent's (C12); a dataset's / evalset's
  first version, a protected alias and trust stay a person's. Reading bitt's own docs and code is a proper way for an agent to learn
  it: the eval runner allows reads of the repo and notes them per run.
- **Evals:** all eight (`evals/haiku/<eval>_basics.py`) have a `reference <dir>` that passes its own grader on the throwaway Postgres
  (data 8/8, run 12/12, measure 8/8, train 11/11, cycle 11/11, versions 8/8, compose 10/10, e2e 11/11). Prove a grader on its
  reference before an agent tries it.
- **Qwen audit of the first round:** `_report/md/qwen_audit_2026-10-30.md` (each miss blamed on tool, skill, model or eval; fixed).
- **Panel** (docs/v2/panel.md; live: `bitt serve` → http://127.0.0.1:8765; with the eval stores: `scripts/viz_serve.py`): home =
  every task, then a task, then a cycle; each open page redraws itself when its store moves. `scripts/viz_evals.py` writes each eval
  store's panel as files; the results page links them.

## Left, in order

1. **The ordered Qwen round** (running on the owner's machine since 15:46, `_output/qwen/round2.log`): easiest → most abstract (data,
   run, measure, train, cycle, versions, compose, e2e in steps mode, then versions, compose, e2e in goal mode), 3 passes, 33 runs; one
   row per run in `evals/haiku/results.jsonl`. Pass 1 steps: data 1/8 (opencode auto-rejected a read outside the folder and the run
   ended: harness, fixed in `4fbbf4d`), run 11/12, measure 8/8, train 11/11, cycle 11/11, versions 8/8, compose 9/10, e2e 11/11.
2. **Audit the round** the same way as the first (`_report/md/`): every miss is the tool, the skill, the model or the eval; fix the
   first three kinds with a test (and a mutation for a rule), the eval kind against its reference.
3. **Results page:** `scripts/build_reports.py` (the agent-eval table, regraded scores beside the originals, a viz link per run).
4. **SKILL.md** from what goal mode shows (each changed command walked on a scratch store).
5. ~~**Re-initialise the personal store**~~ (done 11-01, #10; wiped again 11-04) (`postgresql://bitt@localhost:55433/bitt`: 0 nodes, an older schema: drop and rebuild,
   never migrate, until release), regenerate `docs/v2/db-tour.md` if the schema moved (`bitt_tour` is dropped and rebuilt each run).
6. **Tag v2.0.**

## Rules that still hold

- Live Postgres (the work DSNs) is read-only and never a test target; tests and evals use the throwaway cluster only.
- Synthetic names only; no other tool's name in this repo. Secrets never in tracked files, on a command line or printed.
- A rule change = card + kernel + spec + a replay assert or test + a mutation, in one commit; every change ships a test that fails
  without it. `git add <file>`; never chain a commit after a filtered test command.
- Until release: no migrations, no back-compat, no aliases; replace, then delete.
- A sandboxed agent (no Postgres, no model endpoint) works on the memory backend only, with `BITT_NO_SKILL_SYNC=1`, and never runs
  `pg_throwaway.sh`, `run_agent_eval.py` or an eval's setup / check / reference: those are the owner's side.
