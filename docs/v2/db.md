# bitt — the database

What a bitt store holds and how to read it in SQL. The tables are built from shapes (`src/bitt/tables.py`), never hand-written; the
graph DDL is `src/bitt/sql/postgres.sql`, the functions and views `src/bitt/sql/postgres_nav.sql`. A live one, generated:
`db-tour.md` (`uv run python scripts/v2_tour.py > docs/v2/db-tour.md`, on the throwaway cluster). Every store is Postgres; the memory
record is the same contract for tests and replays.

## 1. The one distinction: shape vs select

Most "datasets derived from datasets" make no new rows: they pick rows. Picking needs a membership list, not a table.

| a run that | examples | output |
|---|---|---|
| **shapes**: makes new rows | clean, generate, a row check's verdicts, an aggregate's one row (`rate`) | rows in its contract's **table** |
| **selects**: picks existing rows (`writes: selection`) | split, sample, dedup, the test side, `exclude` | a **set** over an existing table: no new table |

Imports, datasets, evalsets, ladder rungs and every run's input and output are **sets**.

## 2. Layout

| schema | holds |
|---|---|
| `raw` | one table per raw line (`raw.<line>`): loaded rows, each once, keyed by its content |
| `made` | **one table per output contract** (a module's writes, a prompt's gives), shared by every task: `made.<name>`, named after the first writer (`bitt.writer`) |
| `<task>` | views only: `<task>.<name>` per made table = the rows that task's runs made or reused (A23; `bitt data tables --task T` reads the same) |
| `bitt` | the graph, the registry, the fixed tables below |

Each data table has up to three physical tables:

| table | key | holds |
|---|---|---|
| `<t>` | `bitt_row_hash` | the rows: bitt columns (`bitt_in_hash`, `bitt_recipe_hash`, `bitt_run_hash`, sample, part, timing, tokens, `bitt_extra`) + data columns |
| `<t>__src` | `(bitt_in_hash, role, bitt_src_hash)` | where each made row came from (§3) |
| `<t>__sets` | `(bitt_set_hash, ord)` | memberships over this table: `bitt_row_hash` (FK `<t>`), `split`, `src` (a run's entry: the input entry it came from) |

The `bitt` schema, 11 tables:

| table | holds |
|---|---|
| `node`, `link` | the graph (kernel.md §2): every node, every child → parent link with its role and whether it is lineage |
| `refusal_log`, `direct_write` | refusals that had no `in`; writes made around bitt on purpose (§6) |
| `table`, `column` | the registry: every data table (schema, name, shape, creating node, sources) and its columns |
| `writer` | which table holds an output contract's rows (contract hash → `made.<name>`) |
| `run`, `run_end`, `run_error` | one shape for every run: its recipe's work hash, kind, task, input set, its unit set (`units`), rung, env, traced; at its end: counts (rows, made, reused, failed, calls), status, its output set; failed rows with their error |
| `set` | `(bitt_set_hash, tbl, kind: import / selection / dataset / evalset / run_out, node, n, parent, k, test_hash)` |

There is no metric table: a number across rows (a rate with its interval, a mean, a count, an agreement) is the one row an
**aggregate** module writes into its own made table (`made.rate`), keyed by the input set it read. A train's reported numbers are rows of
`made.<module>_report` (`step` + what its `BITT["reports"]` declares, keyed by run and step): what the script says, never a check.
A join's rows (`inputs.md`) are `made.join_<lookup roles>` (the picked columns, typed from the lookup's table): one per unit, keyed by
the values it read, each linked in `__src` to its unit row and every lookup row it read.

A recipe is a node (`kind = recipe`, `spec_h` = the work); versions, aliases and trust are `tag` nodes; names are `name` nodes (`names.md`).

**Columns nobody declared** (A11): a made row's `bitt_extra` (json, NULL when there are none) holds what its module returned beyond its
declared columns (`{name: value}`; a generate: the reply's fields beyond the prompt's `gives`). The run that kept any writes one warning
naming them; a declared column missing still fails its row. A recipe never binds a `bitt_*` column, so an undeclared column never
silently feeds the next step.

## 3. Lineage: one link shape

`<t>__src (bitt_in_hash, role, bitt_src_hash)`: a made row's `bitt_in_hash` (the hash of what it read) is linked to the source rows, one
row per source and role. Identical inputs share one output row (keyed reuse: the same work on the same read values is never made again).
A made row also links every row a bound column was read from (role = that row's table): a row whose values came from four tickets links
all four. A table module's rows link to its input set (`role = set`): lineage rules then see every possible ancestor (they may over-flag,
never miss). A run reads columns up its lineage (`--cols b=tickets.queue`): along its own unit's chain (§4).

## 4. Sets

- `bitt_set_hash = h("set", canonical([[member hash, split], …] in order))`: the same rows, order and splits = the same set, stored once.
- **One row per member** in `<t>__sets` (plain SQL, FK to the rows).
- **Prefix sets:** `(parent, k)`, the first k members, no member rows of their own: the ladder's rungs (smoke 1, the sample) and train smoke runs.
- **A set is over its unit table** (the raw rows, or a table with one row per unit), never over a content-keyed output table where two
  units may share a row; a unit's outputs are reached downward through `__src`.
- **Runs count per unit** (`d15.md`). A run's **unit set** (`bitt.run.units`) is the set its work started from: an import, a set, a
  dataset or an evalset, or (a run over a run) that run's unit set; a table derive or an aggregate starts a new one (its rows are the
  units downstream). A run's output set (kind `run_out`) is aligned with its units: unit i's entries are its samples 0..S-1, each with
  its parts, and each entry names the input entry it came from (`src`). So a run's output set may list one stored row many times
  (units that read the same values share it), and a row module reads a column of a table above along **its own unit's chain** (the
  unit row and that unit's entry of each run between), never "the first hit" among rows a shared row came from. Ladder rungs and smoke
  runs are prefix sets of the first k units with all their entries.
- A dataset's `test_hash` is the frozen test hash over its sorted test members (`run.frozen_test`).
- A dataset version is a set + a node + a version tag; `data exclude` makes a new set without the rows, never edits the old one (A22).

## 5. Reading it

| need | how |
|---|---|
| anything by name | `bitt show <ref>` (an aggregate's run: its row); `bitt data inspect <data>` (rows, splits); SQL `bitt.resolve('<ref>')`, `bitt.name_of(id)`, `bitt.version_of(id)` |
| data by what it is for | `bitt data list [words …] [--task T]`: every named raw line, dataset and evalset, with what it is for (a load's `does`; a dataset: the module that made it), rows, source and columns; words find a line by any of these (A24); SQL `SELECT payload->>'does' FROM bitt.node WHERE kind = 'raw'` |
| every table | `bitt data tables [--task T]`; `SELECT * FROM bitt.table` |
| a task's own rows | `SELECT * FROM <task>.<name>`; `bitt data inspect <data> --task T` (first line: `N of M rows are task T's`) |
| runs | `SELECT * FROM bitt.v_run` (work, kind, task, out table, rung, status, counts, errors) |
| names, tags, refusals | `bitt.v_name`, `bitt.v_tag`, `bitt.v_refusal`, `bitt.v_task`, `bitt.v_node`, `bitt.v_edge`, `bitt.v_import` |
| lineage | `bitt.lineage(ref)` (what X was made from) and `bitt.downstream(ref)` (what was made from X): the same walks as the walker (W5, tested on every node); `bitt.upstream(ref)` follows every link, story included (not lineage); a row by hash prefix: `bitt.row('<8+ hex>')` |
| the graph as a branch tree | `SELECT line FROM bitt.tree('<ref>' [, 'up'])`: every node once, under the data it was made from first; `also` = its other parents; bookkeeping kinds hidden. HTML: `uv run python scripts/node_tree.py` → `_report/tree/node_tree.html` |
| every task, a task, a cycle | `bitt serve` → http://127.0.0.1:8765, live and read only (docs/v2/panel.md): home = every task as a lane of cycle tiles; a task = what needs you, its open cycles as parallel lanes, its whole map; a cycle = its track, arms side by side, runs, what it made and the box of any other cycle or task it feeds or reads |
| the record as of commit N | `bitt.at(N)` |

## 6. Nothing is written around bitt

Every bitt table has three triggers: `no_change` (UPDATE / DELETE refused), `no_truncate`, and `no_direct`: an INSERT that is not bitt's
own is refused with its `next:`. The kernel marks each of its transactions (`SET LOCAL bitt.writer = 'kernel'`). A direct write on
purpose sets `bitt.direct_write = '<reason>'` first: it goes through and is recorded in `bitt.direct_write` (when, who, table, op, reason).

## 7. A failed rung is a failed run

The ladder is a mechanical rule on run size. A rung with a failed row ends the run with `run_end.status = failed` and its reason; the
rows that passed stay recorded. A transient failure is retried by running the same recipe again: only the missing rows are made (3 tries
per row at most, then the row is skipped). `--full` follows the same rules (the smoke rung first); all without the sample looked at is a warning.
