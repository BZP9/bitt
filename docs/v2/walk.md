# The walker: one way to walk the record (build spec, 2026-11-01)

**Status: agreed with the owner 11-01, frozen; W1, W2 and W3 (its walks) built 11-01; W4 and W5 built 11-03: done.** Charter guarantee 7 (`charter.md`). Every later read of the record (rules, tags,
inspect, the panel, the SQL functions) goes through it, so the logic stays the same everywhere and a new kind of work or input is
covered by declaring its links once.

## 1. Why

The record holds two graphs and a bridge: the **node graph** (records and their links), the **row graph** (made rows linked to the
rows they were made from, `__src`) and the **bridge** (a run, set or dataset and its rows, in unit order). Before the walker, at least
six places walked them, each its own way (`eng.lineage`, `rules.generate_runs` / `trained_on` / `rows_down` (then `tools/guards.py`), `run.chain` / `along`,
the viz (now `src/bitt/panel/data.py`, through the walker), the SQL `bitt.lineage` / `upstream` / `downstream`). When J1 added a new input (`read`), several went blind:
- `read` was listed as a context role, because a decision's link of the row it judged was also called `read`: `eng.lineage` skipped a
  join's lookups, so a later step did not inherit the lookup's sensitivity and `tag.upstream_tagged` did not see a lookup's dataset;
- `generate_runs` followed `on` only: a model's outputs read through a join were invisible to the leak and contamination rules.

## 2. The role registry (in the cards)

- **Every link role has exactly one meaning, everywhere.** `base.yaml: roles` lists each role under one class; lint refuses a role in
  two classes, and a ref field or impl role a card can write that is in none.

| class | means | roles (the full list is base.yaml) |
|---|---|---|
| **units** | what a run walked | `on` |
| **inputs** | the other inputs it read, by role | `read` |
| **made_with** | the code, settings and content it was made with | `recipe`, `module`, `inner`, `artifacts`, `wraps`, `endpoint`, … |
| **made_by** | the run that produced it | `run`, `steps`, `event` |
| **made_from** | the rows it was built on, not by a run's walk | `parent` (a version's parent), `set` (what an exclude acts on) |
| **story** | why, where, judged by: never what it was made from | `in`, `origin`, `because`, `evidence`, `fills`, `subject`, `judged`, … |

- Lineage (made from) = units + inputs + made_with + made_by + made_from. Story is never lineage. The old `unsorted` class was sorted in the
  scenario walk (#9, owner 11-03): `parent` and `set` are made_from; about, agreement, arms, cycle, dataset, decision, fill, goal, pipeline,
  policy, prev, want, ref and rule are story.
- A decision's link of the row it judged is renamed `judged` (story); `read` is only a run's inputs. No alias: replaced.
- `context_roles` goes (the registry replaces it); `impl_roles` stays (it says which roles an impl may add, another question).

## 3. The walker (`src/bitt/walk.py`, read only)

| call | answers |
|---|---|
| `up(x)` / `down(x)` | the made-from closure of a node (down: what was made from it), with filters: `.runs(kind=…)`, `.models()`, `.data()`, `.raw()`, `.of(kind)` |
| `inputs(run)` | `{role: ref}` of a run, uniformly: `on`, every `read` role, its recipe's artifacts, its model |
| `rows(x)` | the bridge: a run (the rows it made or reused), a set, dataset, evalset or raw import → `[(table, row, split, unit)]` in order |
| `rows_up(t, row)` / `rows_down(t, row)` | the row graph through `__src` |
| `story(x)` | the why-chain: its cycle, because, evidence, the decisions and tags about it (the control layer's memory) |
| `up(x, via=DATA_PATH)` | the data path: only the units and reads classes (what a row's data came through), so a model's training lineage is not mistaken for the rows it scored |
| `links(x, role)` | the nodes x links in one role (a set's `run`, a version's `parent`): the one accessor, so no caller reads `links` |
| `set_rows(sh, skip_test)` | a set's rows by its hash, in order |
| `seen(artifact)` | the rows an artifact was made from: a model its train run's input set, train side (W2), as its units; an examples artifact the rows picked (W4) |
| `units_in(x, rows)`, `unit_row(x, i)` | the raw unit each entry stands on, down its own entry chain (a run's `src`; a select's row, found in the input it walked): exact where `rows_up` fans out (a shared row, such as a customer's joined profile, links every unit that ever made it; a row a join looked up is a feature of its unit, never a unit: #6, 11-06) |

- One memo per walker; the walker reads through the Record API, so it is the same on memory and Postgres. A Postgres-side query may
  sit behind the same calls later, never a second meaning.
- It never writes.

## 4. Enforced

- **No direct walking**: `tools/rules.py` reads no link, `__src` or set membership (a test, W2); since W3 no file under `src/` but the walker and the storage layer (`record/`, `sets.py`, `tables.py`) walks the row graph, reads set membership or follows a run's inputs (`on`, `read`) (a test). The run tool keeps one walker per call (an open person run's answers so far come in through `Walk(open_run=…)`). **Settled (owner 11-01): every *walk* goes through the walker**; reading one named link of a node (a recipe's `module`, a cycle's `in`) and the kernel's reverse index for control state (`kids`) stay where they are: they cannot go blind to a new input kind. Before W3 the wording was: any file other than `walk.py` and the record internals reads link roles to
  traverse (`links["on"]`, `links.get("run")`, …) or `__src`. (The run tool's per-unit execution, `chain` / `along`, moves onto
  `walk.inputs` / `walk.rows` in W3; until then it is the listed exception.)
- **SQL parity** (W5): `postgres_nav.sql` takes its role classes from the registry; a test compares the Python and SQL walks on the
  replay stores.

## 5. Phases

| phase | builds | proves it (fails without it) |
|---|---|---|
| W1 | the registry in `base.yaml` (+ lint); `walk.py` (`up`, `down`, `inputs`, `rows`, `rows_up`, `rows_down`, `story`); `eng.lineage` answers through `walk.up`; a decision's `read` → `judged` | a later step inherits a join lookup's sensitivity; `tag.upstream_tagged` refuses an untagged dataset read through a join; lint refuses a role in two classes; `walk.up` equals the old lineage on the replay stores except through `read` |
| W2 | the rules on the walker (`generate_runs`, `trained_on`, `input_rows`, `rows_down`, `set_rows` go) | a model's outputs read through a join are seen by the leak rule; no direct walking in the rules |
| W3 | the run tool's inputs, tag, sensitivity, CLI inspect on the walker (`scripts/v2_tour.py` stays the by-hand SQL view of the db, on purpose: it shows the tables; its node lineage is `bitt.lineage`, equal to the walker by W5) | the suite unchanged; no direct walking anywhere in `src/` |
| W4 | `seen` + artifacts made from data (a run that makes an `examples` / `rubric` artifact) | examples picked from an evalset, then judged on it: refused (built 11-03: `run go <select> --as artifact --artifact-kind examples`; the content is the picked rows; `seen` = those rows, any split; contamination checks every artifact a run made) |
| W5 | SQL parity from the registry | Python and SQL walks equal on the replay stores (built 11-03: a link's `lineage` flag is the registry's class when written; `bitt.downstream` now follows lineage only, `bitt.upstream` is every link; tests/test_walk.py, replay vk on Postgres: all 529 nodes) |
| later | the panel on the walker | — |
