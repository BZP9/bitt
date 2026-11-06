# Rebuild: the foundation, built once (owner 10-29: "rebuild and drop em")

> Names here are as decided at the time; the current words are `words.md` (W17, 11-01: check → rule for kernel cards, guard → rule, …).

**Status: the build plan.** It replaces foundation.md §L's seven green in-between steps with one rebuild on the kept core. The old code
stays readable at the local tag `pre-foundation` (= `e6e1bdc`). Nothing uses this repo or its db (F19): no migrations, no aliases.

## 1. What is kept, what is rewritten

| kept (ported, trimmed) | rewritten |
|---|---|
| the record backends (memory, Postgres), append-only triggers, the direct-write guard | the cards of every type, join and tag act (`spec/cards/`) |
| hashing, blobs, `sets.py`, the table shapes (`raw` / `__src` / `__sets`), `tables.py` | the run machinery (`verbs.py`, the executors, `logic.py`) → `tools/run.py` |
| the kernel call path: proposal, refusal with `next:`, requires, marks, the `when:` grammar | recipes (unversioned uses), tags (one shape), artifacts, wraps |
| control: goals, cycles, wants, plans, validations, grants, authority, acks, waivers | tables per output contract, metrics, `data exclude` |
| the name resolver core, envs, the job protocol, git source, `inspect` | the CLI (three layers + reads), the skill, the tests, both replays, the mutations |

## 2. Build order (each phase: cards + code + tests that fail without it, the suite green on memory + Postgres, one commit)

| phase | builds |
|---|---|
| P1 core | the old tools, cards, tests, replays and mutations removed; the kernel without cuts, recipe lines, `logic.run` or model evals; the control cards and their tests on the kept core |
| P2 types | `module.define` (kind, header, `does`, origin, in git, the kind's claim), `module.wrap`, `artifact.add` (kind, needs → gives, `does`), `data.load` (raw lines); the shelf (`lib`) |
| P3 recipe | `recipe` (module@v + artifacts {role: @v} + params + cols; every version pinned; the work hash; the derived label; `--name`) |
| P4 run | one `run` card; the kind decides the mechanics (derive, check, generate, train, pipeline, load) and the guards (the kind × guard table, §3); one ladder, one job path, one lineage walker; one table per output contract, rows reused by what they read; the person connector |
| P5 tags | one `tag` card: version (major / minor against the previous tag), alias, trust (per task), verdict, problem + ack / waive, deprecated, demote; the authority table; the guards at tag time |
| P6 judge | sets (`as dataset / evalset`) and their guards, `data exclude`; metrics = check rows by recipe + input set; an eval pipeline's `win` → a decision; arms measured |
| P7 close | the CLI (types / joins / workflow / reads: `show`, `log`); the skill; replays vk + gw in the new words; the mutations per rule; docs in line; Qwen evals; tag `v2.0` |

## 3. Carry-over: every rule of the old contract (48 check cards), ported or dropped with a reason

| old check | new home | |
|---|---|---|
| control.* (approval, fills, no_open_debt, act_allowed, plan_wants, can_approve, has_authority, unique_task_name, same_task, policy_shape, grant_shape, plan_has_eval, agent_debt_free, human_actor, not_root, goal_drift, task_boundary) | control, unchanged | ported |
| control.policy (the guard) | `run.guard_runner`: the guard, a row check recipe, judges the call's inputs as one row in a scratch job; every bool verdict true or the call is refused (before: a mock only) | built |
| control.alias_free | `tag.once` (an alias is a name, never a version, not reserved) + `tag.alias_on_version` | ported |
| record.resolve | the kernel's `_check_in` | ported |
| module.header | `module.define` + every run (the code still hashes to its node) | ported |
| module.line_free | `module.define` (a new version names its parent) | ported |
| module.in_git | tag (a version or trust of a module) | ported |
| module.cols_bound | `recipe.cols_bound` (+ `run.input_fits`: the bound columns are in the input or above it) | ported |
| module.contract | the run refuses an output whose columns are not the contract's | ported |
| module.inputs_declared | `run.inputs_declared` (a warning; a connector's endpoint is its declared input) | ported |
| module.runner_fits | `recipe.fits` (every role filled with its artifact kind: a connector's prompt) | ported, reworded |
| module.verb_is | — | dropped: one run card, the kind decides |
| check.calls_no_model | `module.define` (the claim of kind check) | ported |
| check.leak, check.contamination | run, kind check (ack → result marked invalid) | ported |
| check.determinism | `tag.deterministic` (trust valid on a check) | ported |
| check.min_n | `run.min_n` (`invalid_if`) | ported |
| check.agreement_about | `tag.agreement_about` (trust valid): the agreement run read this exact module's or wrap's verdicts | ported, reworded |
| check.models_traced | — | dropped: only a check can be trusted valid (`tag.once`), and a check calls no model, so no model is upstream of a valid judge |
| derive.split_assigned, group_leak, unit_set, frozen_test_reuse | run producing a dataset / evalset (P6) | ported |
| derive.determinism | run (debt) and tag (version of a derive module) | ported |
| derive.idempotent | run, only for a module whose header claims it | ported |
| version.upstream_cut | `tag.upstream_tagged` (a version of anything: every dataset / evalset in its lineage is tagged) | ported, reworded |
| exec.endpoint_serves | `run.endpoint_serves` (a generate whose params name a url and a model) | ported |
| generate.person_run_open | `run.person_open` (label / close only an open person run) + `run.input_complete` (reading one warns: partial) | ported |
| logic.pipeline_shape | `module.define` (kind pipeline: no `while`, every step a `b.run`) | ported, reworded |
| logic.same_major, logic.win_warnings | the decision of an eval run | ported |
| logic.checks_cut | tag (version of an eval): every check module and evalset it names is tagged | ported, reworded |
| train.sensitivity | `run.sensitivity` (every run, every kind) | ported, widened |
| train.has_eval | `run.has_eval` | ported |

The hazard tests (`tests/test_hazards.py`) on the kept core are ported as they are. A hazard test of a removed act is rewritten against the act that replaces it, or listed here as dropped with the reason.

**Tag kinds (P5).** Built as `tag.make`: version, alias, trust, deprecated. A verdict stays a validation (`control.validate`: its
authority rules are the approvals' own), and the problem marks stay the guards' flags / warnings / debts with `control.ack` /
`control.waive` on them: one shape each already, read through the same `names.tags`-style queries. A demote is a trust tag of value hint.
