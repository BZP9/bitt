# bitt — names (2026-10-27, decided with the owner; rebuilt 10-29/30)

People and agents agree on a name for the things worth talking about (a preprocessing step, a dataset, a model, a treatment), then
use it everywhere instead of a hash: `bitt data inspect support_dataset`, `--on raw/survey_answers@2`. This page is
the one rule set for every name, enforced the same way by the kernel, the database and every command.

## 1. Hash first, then names

- A node's body holds only facts about the node itself, including its version number (`1.0`), and never a name. Its id is still the
  hash of that body.
- A **line** (the versions of one thing) is identified by the hash of its first node (its root); every later member links `line` → the
  root (a context link: never part of what a node is). `src/bitt/names.py` is the one place lines and names are read and written.
- A **name** is a binding in the name registry: `<namespace>/<name> → <line root hash>`. `qa@1.0` is computed when read: the line's
  name + the node's version.
- A name, once given, names that line for good (there is no rename: nothing uses a store before bitt ships, so a wrong name is a new
  line). Versions and aliases are not names: they are tags on the unchanged thing (`foundation.md` §C2, W14).
- Every link holds hashes. A call made by name records the hash plus the name it was given (`via`), so a record says what was typed
  without depending on it.

## 2. Namespaces

| namespace | holds | owned by |
|---|---|---|
| `''` (the task names) | every task's name (`vk`): a task's name is also the schema of its views | the person who opens it |
| `lib` | **the shelf**: every module, wrap and artifact (types), task-independent (W8, F18: each keeps its origin) | no task: added from any task, every task uses it by its short name |
| `raw` | every loaded line (`data.load`) | no task: anyone loads, anyone reads |
| `<task>` | what the task made: its data lines (datasets, evalsets, sets) and its recipes' labels | the task |

- Inside a task its own names are short: `clean_q`, and so are the shelf's (`length`: the task's name first, then `lib`; where both
  exist, the kind wanted decides: `length` is the task's recipe line and the shelf's module). Anything else is written in full:
  another task's `gw/qa_test@1`, any raw line `raw/survey_answers`, `lib/length`. A short name never resolves to another
  task's names, and never to raw.
- A short name means one thing: a task's data line may not take a shelf name, and the shelf never takes a name a task already has.
- With no task to read from (a bare `bitt data inspect`, SQL without a task) a short name resolves when exactly one task has it;
  two tasks having it is refused, naming both full forms.
- Cross-task use carries the full name: vk testing on gw's dataset calls `--on gw/qa_test@1`; vk's run links the hash, records
  `via: gw/qa_test@1`, and its lineage prints the full name.

## 2a. When a name is required (names never block work)

| when | a name | |
|---|---|---|
| opening a task | **required** (`bitt task new <name>`, enforced by the card); unique, not reserved | it is the namespace and its views' schema |
| loading raw | **required** (`--line`) | a raw line is its name |
| adding a module or an artifact | automatic: the file's stem; `--name` overrides | the shelf is found by name |
| a recipe | derived: its label, always `<base>:<hash8>` (`recipe.label`: the artifact in its main role @v, else the module @v, then the first 8 hex of the work: `summarize:1d2b8a52`), so it never changes when another recipe appears; the base alone never resolves (refused, listing the full labels); `--name` adds a fixed alias beside it | rerun by label or alias |
| a run | none | reached by hash, `last`, or what it made |
| a dataset / evalset | **required** (`--line`, or the name of the want it fills) | a version tag needs a named line |

## 3. Grammar

```
ref      := [namespace "/"] name [ "@" (version | pointer) ]
name     := [a-z][a-z0-9_]*           not ending in v<digits> (a version is always written with @)
version  := N | N.M                   digits only; `@v1` is refused
pointer  := [a-z][a-z0-9_]*           letters first: @live, @best
```

Reserved names (refused at bind): `tables`, `runs`, `versions`, `refusals`, `catalog`, `all`, `last`, the namespaces `raw`, `lib`, and the
schemas `bitt`, `made`, `data`, `dataset`, `public`, `information_schema` (a task name is a schema; `pg_*` is refused). Also refused:
8+ hex characters (those are ids), `__` and a trailing `_` (bitt's table suffixes), more than 40 characters. The `v<digits>` rule is
strict on purpose: `datasetv1` and `dev2` look the same to a rule, so both are refused (`dev_2`, `qa2` are fine).

| you type | means | moves? |
|---|---|---|
| `qa_test` | the line's newest member, unversioned ones included | yes |
| `qa_test@1` | the newest 1.x (the same contract) | only within 1.x |
| `qa_test@1.2` | exactly that version | never |
| `qa_test@live` | the newest alias tag `live` on the line (a protected alias is a person's) | when a tag moves it |
| `raw/x` | the newest import of the raw line `x` | yes |
| `raw/x@2` | its second import (imports are counted in load order, never stored) | never |
| `raw/x@all` | the whole raw table: every distinct row any import brought | grows |
| `last` | the node your previous command made (the CLI) | — |
| `demo#3` | task demo's third cycle (§7) | never |
| `demo#g1` | task demo's first goal or sub-goal (§7) | never |

A pointer hangs on a line (`qa_test@live`), never alone, and is never a reserved word or a version. Inside a pipeline module names are
written plainly (`b.run("draft", with_="qwen")`) and pinned when its recipe is made (C11).

Versions are tags (`tag.make --version`, set once): the major bumps on a contract change (a module's header, a dataset's test rows), the
minor on new code or rows with the same contract; a major is a person's. The first version is 1.0: anyone's on a module or an
artifact, a major (a person's) on a dataset or an evalset. An alias is a tag that moves (`tag.make --alias`).

## 4. One name, one kind

- **A name is one kind** (`names.join` refuses a second): `clean` the module never also names a dataset. Types (modules, artifacts) are
  written and live on the shelf; data (raw, datasets, evalsets) is made or loaded and lives in raw or its task.
- A line has members: the versions of one thing. `tickets_split` is every version of the dataset; `tickets_split@1.0` one of them.
- A dataset made from another task's version starts this task's line (`names.place`).

## 5. The registry and its checks

The registry is `name` nodes in the record (payload: ns, name, class, kind; link: `target` → the line root), written only through
`names.bind`; append-only like every node:

- binding a name checks the grammar, the reserved words, the namespace and the shelf rule, and that the name is free;
- the database holds the same rules: a unique index on (ns, name) over name nodes, a CHECK on the pattern;
- every reader resolves through one function: the kernel's `resolve` (the CLI's `tools/refs.py` only calls it), and in Postgres
  `bitt.resolve('<ref>', <task id>)`, so plain SQL gets the same answer (NULL where the kernel refuses), with `bitt.v_name`,
  `bitt.name_of(id)`, `bitt.version_of(id)`, `bitt.line_of(id)`, `bitt.members(root)`. `tests/test_tag.py` pins the two to agree.

## 6. Tables and views follow the contracts, not the names

- Made rows live in `made`, one table per output contract (a module's writes, a prompt's gives), shared by every task and named after
  its first writer (`bitt.writer`): two tasks running the same work reuse its rows (0 calls).
- Each task gets a schema of its name holding views: `<task>.<name>` = the rows its runs made or reused (A23).
- Raw stays in `raw`: `raw.<line>`.

## 7. Cycles

Cycles and goals are not named: they are numbered in the order opened. `<task>#3` = the task's third cycle; `<task>#g1` = its first
goal or sub-goal (2026-10-28). **Your current cycle** (scenarios.md F11) is a local pointer per store, never a node:
`bitt cycle new <task|goal>` makes the new cycle current, `bitt cycle use <cycle>` switches, `bitt cycle list` marks it. Then:
- no `--in`: your current cycle (else, with one task, its only open cycle);
- `--in <task>` or `--in <task>#g1`: your current cycle if it is under it, else its only open cycle; several open and none current →
  refused, listing them (it never picks the newest silently);
- `--in <task>#3` / an id: exactly that cycle, for this call only.
Every command that works in a cycle prints first where the work goes: `→ support / support#g1 'short summaries' · support#1 (current)
'…' [explore, EXPLORE]`. The pointer file is `$BITT_CURRENT` (default `~/.config/bitt/current.json`).

## 8. Built

`src/bitt/names.py` (grammar, registry, resolver, placing a node on a line); versions and aliases in `src/bitt/tools/tag.py`; recipe
labels in `src/bitt/tools/recipe.py`; `src/bitt/tools/refs.py` (the CLI: names, `last`, an echo of every resolution); the SQL above.
Not built: tab completion of names.
