# Several named inputs: the join step, named table inputs (build spec, 2026-11-01)

**Status: agreed with the owner 11-01, frozen; J1 and J2 built 11-01, J3 and J4 built 11-03.** Issue [#2](https://github.com/BZP9/bitt/issues/2); scenarios D1, A8, D17, S1
(`scenarios.md`). Needed by the router story (`story_router.md`). Built in the phases of §6; each phase is one commit with its test,
replay assert and mutation (CLAUDE.md).

## 1. What the owner decided

- **A join is a step, not a recipe setting.** It is a run of the shipped `join` module; its output is a table you can open, read by
  any later step like any other run. Recipes and row modules never join: a module stays a plain function over columns.
- **A join is computed per table and recorded per row.** One index per lookup input per run (never a lookup per row); every output
  row links, in `__src`, its unit row and every lookup row it read.
- **The join keeps the units.** Entry *i* of a join's output belongs to unit *i* of its input (like a row module, unlike a table
  derive, whose rows are new units). Splits, the group-leak rule, contamination by units and per-unit counts (D15) see through it.
- **The units are the input with no key**: the run's `on`. Every other input is named (`read`) and looked up by key.
- **A key that is not unique in a lookup is refused** (it is almost always a data bug), naming the repeated keys.
- **A miss** (a unit with no matching row) is set per join recipe: `empty` (the default: the picked columns read as empty, one
  warning per run with the count), `drop` (the unit leaves the output, one warning), `fail` (a failed row).
- **One-to-many** (`many`: every matching row, as a list column) and **as-of** (`asof`: only rows before the unit's time) are part
  of #2: the as-of limit lives in bitt, not in the module, so a future row never reaches the module (no leak) and an old unit's
  read set never changes (it is always reused).
- **Excluded rows** (`data exclude`) read through a lookup warn, as anywhere else (A22).
- **A table module may take several named inputs** (`def union(rows: list, chat: list)`); its rows are new units (a merged, deduped
  ticket is a new thing); `bitt_from` names `[role, index]` pairs. bitt ships a `union` built-in.
- No per-row lookup inside a row module now (no scenario needs one; it would use the same index if one ever does).

## 2. The words

- **on**: what a run walks (its units' input). Unchanged: one input for every kind but a pipeline.
- **read**: the other inputs a run reads, by role: `{role: data}` (`--read profile=crm/profile@1.0`). Only a join, a table module
  and a pipeline take them (a pipeline hands them to its steps: `b.read["profile"]`, `b.run("join", …, read={…})`); any other kind
  is refused with `next: join it first`.
- **join**: the module kind bitt computes itself (no job: there is no code to run, only the settings), shipped as `lib/join`.
- **lookup**: a `read` input of a join: indexed by its key, each unit reads its one matching row (or, `many`, its rows).

## 3. The join step

```
bitt recipe join --cols tier=profile.tier region=profile.region --params key='{"profile": "customer_id"}' miss=empty
bitt run go join:5b7e… --on intake/tickets@1.0 --read profile=crm/profile@1.0
→ 1200 rows (31 with no profile row: read as empty)
bitt recipe route_features --cols text=text tier=tier region=region           # an ordinary recipe; text is read up the unit's chain
```

- **The module** `src/bitt/builtins/join.py`: `BITT = {"kind": "join"}`, `def join(on, *, key: dict, miss: str = "empty",
  many: list = [], asof: dict = {})`. Its keyword-only params are the join's settings (typed and defaulted by `recipe.fits` as for
  every module); its body is never run.
- **key** `{lookup role: column}` (the same column name on both sides) or `{lookup role: {lookup column: unit column}}` (several
  columns = a composite key). The unit side is read along the unit's chain like any bound column.
- **cols** `{output column: "<lookup role>.<column>"}`: what each unit gets. The output table's contract is exactly these columns,
  their types read from the lookup's table (a `many` role: `json`, a list in the lookup's order, or `asof` order).
  The unit's own columns are not copied: a later step reads them up the chain (the join keeps the units).
- **Identity and reuse**: a joined row's key is the recipe's work × the hash of the values it read (the unit's key values and every
  picked value), as for a row module (A12): a new lookup version re-makes only the units whose picked values changed; a change to a
  column nobody picked re-makes nothing.
- **Refusals** (each with `next:`): a key column missing on either side; a lookup key that repeats (non-`many`); a `cols` entry whose
  role is not a lookup; a `read` input on a kind other than join or a table module; `many` / `asof` naming a role that is not a lookup;
  `asof` on a role not in `many`.
- **asof** `{lookup role: [lookup column, unit column]}`: the role's rows whose lookup column is strictly before the unit's.
- **A `many` role never misses**: a unit with no matching row reads `[]` (no history is an answer), so `miss` applies only to the
  other lookups; the run ends with one warning per such role and its count (owner 11-01).
- **No ladder**: a join calls nothing, so it runs in full every time (no rung, no warning).
- **Split first, then join**: a select over a join's output, where units share a stored row, is refused with that order in its
  `next:` (a dataset lists each row once; the join keeps the splits).
- **What `run go` says**: the usual counts; `made` counts stored rows (units that read the same values share one, as for a row module).

## 3b. Named table inputs and the union (J3, built 11-03)

- **A table derive names its inputs** in its signature: `def merge(rows: list, chat: list) -> list` (the first is `rows`, the units,
  `--on`; each later list is a `read` role). Only a table derive returning rows: a select or an aggregate reads one input. A missing
  or extra role is refused (`next: --read chat=<data>`). Each named input arrives as its rows' own columns (no `cols` binding).
  `bitt_from` is an index into `rows` or `[role, index]`; a row with no `bitt_from` is keyed by, and linked to, every input set.
- **The shipped `union`** (`BITT = {"kind": "union"}`, `def union(on, *, key: list = [])`) is computed by bitt, like a join: no job.
  Every row of `on`, then of each `read` role in name order; rows equal on `key` (default: every column) are one row, its values the
  first one read, linked to every source row it stands for. Its rows are new units. The contract is `on`'s data columns, typed from
  its table; an input without one of them is refused. `rows_total` − `made` − `reused` = the duplicates merged.

## 4. The run record

- `run.go` gets `read: {ref_map: [raw, set, dataset, evalset, run]}` (the kernel's existing role map: the payload keeps `{role: id}`,
  the links hold the ids). `on` stays the units.
- The run's payload records `reads: {role: set hash}` next to `input_set`, so a run says exactly which version of every input it read.
- Lineage, rules and tags follow every input: `run.sensitivity` and `run.input_fits` check each `read` input; `tag.upstream_tagged`
  and the contamination / leak walk go through `__src`, which already holds the lookup rows.

## 5. What changes in the code

| where | change |
|---|---|
| `spec/cards/run.yaml` | `read` on `run.go`; `join` in `open_in_by_kind`; `run.input_fits` covers `read` |
| `tools/header.py` | the `join` kind (`fn(on, *, params)`) |
| `tools/recipe.py` | a join's cols are `<role>.<column>` of its lookups (not the module's reads) |
| `tools/run.py` | `join()`: index per lookup, keys refused if repeated, miss / many / asof, rows keyed by values read, linked to every row read, entries aligned with the units; the one-input refusal points at `join` |
| `builtins/join.py`, `builtins/union.py` | the shipped modules |
| `cli.py` | `run go --read role=data …` |
| `docs/v2/*.md`, `SKILL.md` | words.md, foundation.md, scenarios.md (D1, A8, D17), the skill's join block |

## 6. Phases

| phase | builds | proves it (fails without it) |
|---|---|---|
| J1 | `read` on `run.go`; the `join` kind and `lib/join` (key, miss, refused repeated keys); units kept; cols typed from the lookup | a join's rows link both sides, a later row step reads a unit column up the chain and a looked-up column; a repeated key is refused; each miss mode; a new lookup version re-makes only changed units; replay vk asserts a join; mutations: units not kept, a repeated key accepted, a lookup row unlinked |
| J2 | `many`, `asof` | a list column in order; a future row never read; a new future row re-makes nothing |
| J3 | named inputs on a table module; `bitt_from` `[role, index]`; `union` | a deduped row links both sources |
| J4 | the map: one edge per input role, named (built 11-03: `on` and each `--read` role at the arrow's end; the panel 11-04) | tests/test_panel.py |
