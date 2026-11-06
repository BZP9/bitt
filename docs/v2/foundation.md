# Foundation: control the workflow, control the four types, manage both (draft for the owner, 2026-10-29)

> Names here are as decided at the time; the current words are `words.md` (W17, 11-01: check → rule for kernel cards, guard → rule, …).

**Status: a proposal from first principles, written regardless of what is built (owner 10-29: "focus on 2 things: how to control the
workflow, how to control the 4 types; then how to manage both; then based on these, the db, the CLI and the rest").** the audit (`rethink.md`, at the tag `pre-foundation`)
is the audit of what is built; this page is what it should be. Nothing is agreed until `scenarios.md` has been walked against it.

## A. Controlling the workflow (the why)

The workflow is **why work happens and when it counts**. It holds intent, verdicts and freezes, never logic and never data.

| thing | what it is | rule |
|---|---|---|
| **task** | the top container: a name (its namespace) and who has authority | a task needs a person who can approve |
| **goal** | a problem inside a task (goals hold sub-goals) | a new major of a goal = the intent changed; what was framed under the old one is warned (drift) |
| **cycle** | one question being worked on: **explore** (free, promises nothing) or **working** (must end in a verdict) | every run, verdict and freeze happens inside a cycle (`in`) |
| **want** | "this cycle should produce X" (a placeholder with a contract) | a fill must meet the want's contract |
| **plan** | the arms to compare and the eval that judges them, named **before** the work | a working cycle cannot run work without a plan with an eval (D7) |
| **decision** | what an eval's rule concluded, with the exact numbers it read | made by a run of an eval module; a decision makes no data |
| **validation** | a verdict on something: pass / fail, or approve / reject by a person | person-only: approve, a major freeze, a promotion, a close (delegable by grant) |
| **finding** | what was learned, citing evidence | the `because` of a freeze or of the next cycle |
| **freeze (cut)** | a tag: "this version counts" (§C2) | made in a cycle, with its because and validation |
| **warning / debt / ack / waive** | allowed but noted; owed before close or freeze; a person's "I know" | never silent: each one is a record a person can read |

**The cycle's states are read from its records, never stored**: GOAL → FRAME (want, plan) → WORK (runs) → JUDGE (every arm measured)
→ ACT (a decision) → CLOSED; or PARKED / EARLYSTOPPED. Nothing in a cycle waits on a long run: a run that is still going (a train, a
person labelling for days) is shown as open; it blocks only what needs its result.

**Three rules of the workflow:** it records why (every work record points at its cycle); it decides only from numbers (a decision cites
what it read, and a person or a measured agreement says what is trusted); it never does work itself (a plan names modules; it holds no code).

## B. Controlling the four types (the what)

Each type has **one contract, one identity, one home, one way to change, and checks that follow from its contract.**

| | **data** | **module** | **artifact** | **param** |
|---|---|---|---|---|
| is | rows with lineage | code that does one thing | content used whole | a value given at use |
| contract | its columns and types | its **kind** (derive, check, generate, train, pipeline, loader, connector) + reads → writes + params + calls | needs → gives (optional: plain content has none) | its type and default, declared by its taker |
| identity | row hash (content); set hash (which rows, in order, with splits) | hash of code + contract | hash of content | none of its own: part of the recipe's hash |
| comes from | a loader (outside → SQL, once) or a run | an author: a file in git | an author (in git) or a run (a model file) | the person or agent, at use |
| tracked with it | its load or its run, and **does** (one line: a load's `--does`, required; a made dataset's: its module's, A24) | **origin** (the task + cycle it was added in) and **does** (one line, required: the module's docstring) | **origin** and **does** (one line, required: `"bitt": {"does": …}` in the file, or `--does` at add when the file has no place for it; a made one: its run) | — |
| home | `raw` (loaded) or its module's table (made) | the shelf (`lib`), any task uses it | the shelf (authored) or the task that made it (a model file) | inside the recipe |
| changes | a new load = a new raw version; a new run = new rows; a new selection = a new set | a new version on its line: **major** = contract changed, minor = code only | a new version on its line: major = needs / gives changed | a new value = a new recipe |
| checked | lineage, splits, leaks, sensitivity, contamination | the claim at add (a check calls no model, a pipeline has no `while`); the results against the claim after a run; committed in git | parses; committed in git, or made by a run (its lineage) | fits its taker (unknown or mistyped refused, required asked for, defaults filled); long text → make it an artifact |

**Two ways types combine, both outside any task:**
- **wrap**: a module with some params or artifacts fixed is a module (`qwen` = `openai_chat` + url, id, key file). It is reusable,
  versioned, and pins its inner versions.
- **model**: a model file (an artifact) + a model endpoint (a wrap of a connector). A trained model's endpoint is made when the train lands.

**Origin is kept, never used** (owner 10-29, F18): a module or artifact records where it came from and what it does, but any task
uses it the same way; a new version records its own origin. **The types never know about the workflow.** A module, an artifact or a wrap has no task, no cycle, no idea where it runs or on what data.

## C. Managing both: three joins, and nothing else

The workflow and the types meet in exactly three places.

### C1. The run: types make data, under a cycle

- A **recipe** is a use of a module: the module (or wrap) @v + artifacts @v by role + params + **every binding** (each column the module
  or an artifact needs → a data column). Its hash is **the same work** in every task. It is not versioned itself: it changes when a part
  changes. A reusable configured thing is a wrap.
- A **run** is a recipe over a set of rows, in a cycle, in an env, by an actor. The module's kind decides the mechanics (the ladder, gates,
  smoke-first, rows per job) and the guards that fire. A row already made by the same recipe on the same read values is never made again.
- A run records: recipe, input set, cycle (why), env (where), actor (who), the rows it made / reused / failed.

### C2. The tag (freeze): the workflow says a version counts

- **One tag kind over every versioned thing**: a data line (a dataset, an evalset), a module, a wrap, an artifact. A tag points at the
  thing, unchanged (its hash stays), with a version, a because (a finding) and a validation.
- **major or minor** is computed against the previous tag on the line (contract compared); a major needs a person.
- **The guards at tag time follow the thing's kind**: a derive is deterministic, a dataset's upstream is tagged, the code is committed in
  git, a model was scored on rows it never saw.
- **An alias** (`@live`) is a movable tag; a version tag never moves.
- **Trust** (class: builtin / hint / valid) is a tag of its own kind on a check module or wrap: a person or a measured agreement promotes it.

### C3. The decision: the workflow reads data

- An **eval** is a pipeline module. A run of it runs its steps (each step a run: a check's per-row verdicts, then an aggregate module
  over them that writes one row, per unit) and applies its one declared rule to a column of that row → a **decision** (control) that
  keeps the row it read (D15, `d15.md`).
- A person validates the decision; a tag or a close follows.

**One-way arrows:** control → points at types, runs and data; types never point at control; data points back to the run that made it.
**Defined things are global** (types, wraps, recipes by hash: the shelf). **Done things are local** (runs, made data, decisions, tags:
the task, inside a cycle).

## D. What follows for the implementation

### D1. Database

| holds | where |
|---|---|
| every type version, wrap, recipe, run, control record, tag | one graph (`node`, `link`), content-addressed, append-only; `kind` says which |
| names | one registry: `raw` (loaded data), `lib` (the shelf), `<task>` (what the task made, and its own names for shared things); one name = one kind |
| loaded rows | `raw.<line>` (+ its sets) |
| made rows | **one table per module contract (major)**, shared by every recipe and task that uses it, each row keyed by what it read and carrying its recipe; a task sees its own rows through views |
| sets (imports, datasets, evalsets, ladder rungs) | one membership shape per table |
| runs | one shape for every kind (+ the kind as a column) |
| metrics | rows of an aggregate module (`rate`, `mean`, …) over a check's run, per unit, in its own made table (D15: no metric table) |
| code and content | git + blobs, never in the database; the graph keeps the hash and the commit |

### D2. CLI (three layers, one verb each where possible)

| layer | commands |
|---|---|
| the types | `bitt data load / list / inspect / tables / diff` · `bitt module add / wrap / new / list` · `bitt artifact add / new / list` |
| the joins | `bitt recipe <module> --cols … --fill … --params …` · `bitt run go <recipe> --on <data>` · `bitt run status` |
| the workflow | `bitt task / goal / cycle` · `want` · `plan` · `note` · `validate` · `tag` (cut) · `promote` · `close / park / …` · `grant` |
| reads | `bitt show <anything>` (a type, a run, a decision, a cycle) · `bitt log` (what happened, in order) |

### D3. The rest

- **Cards**: one per act (define per type, wrap, recipe, run, tag, each control act) + the guards in one kind × guard table.
- **The skill** follows the same three layers (write and shelve; recipe and run; plan, judge and tag).
- **Tests** per layer, the replays per scenario.

## E. Open (to settle with the scenario walk)

1. Recipes as **unversioned uses** (C1) is new: today `clean@1.1` is a recipe line. Is a named, versioned configured thing always a wrap?
2. **Tables per module contract** (D1) reverses "tables stay in the task" (6a item 2); access by sensitivity moves to rows.
3. Does a **set** (dataset, evalset) get tagged like the types (C2), with the frozen test hash checked at tag time?
4. Does **trust** stay a separate tag kind (C2), or a field of a version tag?

## F. Names, tables, tags (discussion, owner 10-29)

- **Names** label lines, never single records: `[ns/]name[@version | @alias]`. Named: tasks / goals / cycles; data lines (raw lines,
  datasets, evalsets, a model file); modules, wraps, artifacts (in `lib`). A recipe gets a task-local name (default: its module's
  name; `--name` to keep two settings of one module apart). Runs, rows and sets are reached by hash or by what made them (`last`, `<recipe>`).
- **Tables follow the output contract, not the run.** A run never makes a table: it adds rows to the table of what it writes. One table
  per writer contract: a module's `writes` (its major), or for a generate, the prompt artifact's `gives` (its major). A new source, a
  new input set, new params or a new model = a new run (and maybe a new recipe), rows into the same table; rows already made for the
  same read values are reused. Only a contract change (a new major: other columns) makes a new table. "This run's output" = a view.
- **Tags** (owner: datasets are tagged too; builtin / valid are tags). Every mark a person, an agreement or a guard puts on a thing, as one
  shape: {target, tag kind, value, because, by, in}; append-only (a later tag supersedes an earlier one). The audit of what exists is §G.

## G. Audit: every tag-like mark today, and what is missing

| tag kind | today | proposal |
|---|---|---|
| **version** (immutable `@1.0`, major / minor) | `version.cut`: a copy node with `state=cut` (datasets, evalsets, modules, recipes, models, pipelines); a loaded base model is born cut | a tag on the unchanged thing; a major needs a person |
| **alias** (movable `@live`, `@best`) | `control.alias.move`; no CLI | a movable tag; a CLI |
| **name** (a label for a line) | `name` nodes, `control.rename` | a movable tag in the name registry |
| **trust** (builtin / hint / valid) | builtin = a payload flag at add; hint = the default (no record); valid = a `recipe_class` node by `control.promote` | one trust tag: builtin at ship, valid by promote (a person or a measured agreement); on the module or wrap (today on a recipe) |
| **verdict** (pass / fail / approve / reject) | `control.validate` (a `validation` node) | keep as a tag kind |
| **problem marks** (invalid, untraced, contaminated, frozen test reused, goal drift) | `flag` / `warning` / `debt` nodes from guards, `test_flag` in a set's payload | one problem tag kind, set by guards |
| **answers to a problem** | `control.ack` (go on anyway), `control.waive` (a debt accepted) | tags on the problem tag |
| **fills** (this fills that want) | a `fills` link on the work node | a tag on the work, pointing at the want |
| **committed** (the code is in git at commit c) | `module_source` node | a tag (or the version's own field) |
| **draft** | `state=draft` in a payload | not a tag: the absence of a version tag |
| **missing: demote** (valid → hint) | none | a trust tag with value hint, by a person, with a because |
| **missing: deprecated / retired** (do not use for new work; old records stay readable) | none (only `control.policy_retire` for policies; "deprecated" JSON pipelines have no mark) | a lifecycle tag: new recipes over it warned or refused, old ones readable |
| **missing: superseded by** (this version replaced by that one) | implicit (a newer version on the line) | a tag when the replacement is on another line |
| **missing: excluded rows** (these rows of a dataset are bad) | none (a new select makes a new set) | open: a tag on rows, or always a new set |
| **missing: who may set which tag** | spread over checks (`control.can_approve`, `human_actor`, grants) | one authority table: tag kind × who (person, agent with grant, guard) |

## H. Agreed 10-29 (owner)

- **A recipe = this module, with these settings, on these columns.** No version of its own (§E1 settled); identified by its hash, named per
  task (default: its module's name). Versions belong to modules, wraps, artifacts and data lines.
- Datasets and evalsets are tagged like the rest (§E3); trust (builtin / valid) is a tag (§E4).
- **Excluded rows = always a new set** (§G, option A): `bitt data exclude <dataset> --rows <file> --because …` makes the select; the rows also get an informational mark (shown in inspect, warned when a new set still includes them) that never changes a set. A version always means the same rows.

## I. The scenario walk (10-29, every row of `scenarios.md`, A1–G16)

**Fit unchanged (82 of 99):** A1–A8, A10–A22, B1, B3, B6, B7, C3, C4, C6–C9, D1–D3, D5–D10, D12, D14, D15, E1–E11, F1, F3–F18,
G1–G4, G7, G9–G11, G14–G16. The ones the foundation strengthens:
- G2: a prompt slot with no column is refused at recipe (every need bound), not at run.
- F14 / F16 / F18: the shelf, artifacts, origin + does.
- E11 / A21 / A22: the model's lineage, the loader, excluded rows.
- D15 / G11: metrics = check rows + an aggregator.

**Fit with a wording change (8):** A9 ("one table per line" → per output contract); B4 (a combination is a pipeline module or a wrap);
B5 / B8 (names settle "at cut" → at the version tag); C2 ("each step its own line and table" → its own output contract's table);
C5 (rows keyed by recipe hash, which now covers the artifact versions); G5 / G6 (output columns = the prompt's gives; `next:` by kind).

**Already superseded (4):** B2, D4, D11, D13 (slice 6 decisions).

**Superseded by this foundation (1), agreed by the owner 10-29:** **F2** "minimal verbs: generate, derive, check, logic, train" → verbs become
module kinds (loader, derive, check, generate, train, pipeline, connector); one act, run (W10, W11).

**Conflicts to settle (4):**
1. **G12 / G13 / C1: naming a generate's recipe and picking rows by prompt version.** Recipes have no versions now, so `--on summarize@2`
   cannot mean recipe v2. Proposal: a generate recipe's default name is its **prompt's** name; `summarize@2` on `--on` / `inspect` means
   "the rows made with prompt `summarize@2`" (the version is the artifact's).
2. **G8: `--why` on a params change.** It was required because a new recipe was a new version. Proposal: a recipe takes an optional
   `why`; the required because moves to where it matters: a version tag, a plan, a decision.
3. **Trust on what (§G).** An agreement is measured for one configuration (module + params). Proposal: trust tags a module version when
   it has no params, else a **wrap** (the configuration fixed); `check.agreement_about` checks the agreement was measured with that wrap.
4. **Tables per output contract** (§E2, not yet answered): it reverses 6a item 2 ("tables stay in the task"); sensitivity moves to rows.

## J. Settled 10-29 (owner), from §I's conflicts

1. **A recipe's default name follows what makes it distinct: its prompt if it has one, else its model, else its module** (`--name`
   overrides). `<name>@v` on `--on` / `inspect` means the rows made with that prompt / model / module version; `--model`, `--prompt`
   narrow it. Two recipes in one task that would take the same default name (one prompt, two models) → the second is refused with
   `next: --name <prompt>_<model>`.
2. **`why` is optional on a recipe**; the required because stays on version tags, plans and decisions.
3. **Trust is per task**: `valid` is a tag in the task that measured the agreement; in another task the same module or wrap is a hint
   until that task promotes it (it may see "valid in <task>" as information). `builtin` (bitt ships it) holds everywhere.
4. **Tables per output contract, retrievable by task**: a task's rows are those its runs made or reused (a run's input set × its
   recipe), so a row shared by two tasks belongs to both; `<task>.<recipe name>` views, `bitt data tables --task <t>`, `inspect --task`.

## K. Two prompts in a row (C2) under the foundation (proposal, 10-29)

**By hand: two recipes, two runs.** `bitt recipe summarize --with qwen --cols text=clean.text`, `bitt run go summarize --on tickets`;
`bitt recipe beautify --with qwen --cols draft=summarize.summary`, `bitt run go beautify --on summarize`. Two tables (each prompt's
`gives`), beautify's rows linked to summarize's rows (`__src`), each prompt versioned as an artifact.

**Bundled: a pipeline module** (making, so no `win`; an eval is the pipeline that declares one):
```python
"""Summarize a ticket, then polish the summary's format."""
BITT = {"kind": "pipeline"}

def polish(b, on, *, model: str = "qwen"):
    s = b.run("summarize", on=on, with_=model, cols={"text": "text"})
    return b.run("beautify", on=s, with_=model, cols={"draft": "summarize.summary"})
```
- Each `b.run` is a kernel run of its own recipe: its own table, rows, lineage, reuse. The pipeline writes no table; its run records
  its step runs (and returns a reference to the last).
- **Its recipe pins every version its steps name**, resolved at recipe time (like a lock file), so one recipe hash is always the same work:
  a new `beautify` version = a new pipeline recipe; step 1's rows are reused, only step 2 is made.
- **The ladder goes through the steps**: a `run go polish` climbs step 1 (smoke, then its sample; the next call all); step 2 runs over
  the rows step 1 made (11-04: smoke → sample → all, C6); a failed rung in either step ends the run.
- A model fixed in = a wrap (`polish_qwen`); default name = the module's (no prompt or model of its own).
- **Settled 10-29 (owner): a newer step version changes nothing until you make a new recipe** (pinned at recipe time).

## L. Rebuild plan from §D (proposal, 10-29; replaced the old design hub's last slices)

Each step: cards + kernel + spec + a replay assert + a mutation per rule, tests that fail without it, the suite green on memory +
Postgres, and the code it replaces deleted in the same step (no concept lives twice).

| # | step | builds | deletes |
|---|---|---|---|
| R1 | **one run** | header `kind` (old `verb` read with a warning); one `run` card and node kind (+ `bitt.run.kind`); one job path, one ladder, one run skeleton, one lineage walker; the kind × guard table (sensitivity on every env run); `bitt run go` for every kind | `derive.run`, `generate.run`, `check.run`, `train.run`, `logic.run`, `module.verb_is`, the 3 job paths, 4 ladders, the old run commands |
| R2 | **tags** | one tag node kind (version, alias, trust per task, verdict, problem marks + ack / waive, deprecated, demote); a tag on the unchanged thing; draft = untagged; the authority table; `bitt tag` | the copy-node cut, `recipe_class`, `alias_binding` as separate kinds |
| R3 | **recipes as uses** | `bitt recipe` (one command); unversioned, hash = the work; names prompt > model > module; `why` optional; every version pinned at recipe time | recipe lines and versions, the three recipe commands |
| R4 | **artifacts and wraps** | `artifact add` (needs → gives, fill); prompts as artifacts; origin + `does` on every module and artifact (F18); `module wrap`; a model = a file artifact + an endpoint wrap; one connector contract; the `person` connector (C9) | `form=prompt` modules, `model:base` / `endpoint` nodes, runners as a word, `module.runner_fits` |
| R5 | **tables per output contract** | one table per writer contract (a module's writes, a prompt's gives), `<task>.<name>` views and `--task` reads (A23); metrics = an aggregate over check rows by recipe + input set; `data exclude` (A22) | tables per task × recipe line; `bitt.variable` as a store (kept as a cache / view) |
| R6 | **loader and pipeline modules** | the loader kind (`data load --with parse.py`); pipeline modules in Python (`b.run`, no `while`, a call budget, an eval's one `win`) | the JSON step language |
| R7 | **reads, docs, close** | `bitt show`, `bitt log` (F13); `module new` / `artifact new` templates; db cleanup (dead columns, `bitt.state`, the `data` schema) and db.md / every v2 doc in line; the skill rewrite; every agent eval on Qwen; tag v2.0 | `spec/kernel-contract.md` (folded into docs/v2) |

**Nothing uses this repo or its db until bitt ships** (owner 10-29, F19): the personal store (`localhost:55433`) holds 0 records; it is re-initialised after the rebuild. No migrations, no back-compat: an old command or form is deleted in the step that replaces it, never kept as an alias or a deprecation.

## M. A recipe's columns and its label (agreed 10-29, owner; replaces §J item 1's naming; the label revised 10-30, C10: always `<base>:<hash8>`)

There is no "prompt" type and no "model" type: a prompt is an **artifact** (in the role `prompt`), a model endpoint is a **module** (a
wrap of a connector), a model file is an **artifact** (in the role `file` of its endpoint wrap). So a recipe holds only:

| column | holds | e.g. |
|---|---|---|
| task | where it is used | `support` |
| module | the module or wrap @v that runs | `clean@3`; a generate: `qwen@1`; a trained model: `clf_endpoint@1` |
| artifacts | `{role: artifact@v}` it fills | `{prompt: summarize@2}`, `{prompt: …, rubric: rubric@1}` |
| params | per-use values | `{temperature: 0}` |
| cols | every binding | `{text: clean.text}` |

**No stored name.** The **label** is derived: the artifact in the module's main role (a connector's is `prompt`) @v, else the module @v,
in its task (`support/summarize@2`, `support/clean@3`); when two recipes share it, the label adds the next part that differs (the module,
then a short params hash). An ambiguous reference is refused with the candidates and a `next:`. `--name` stays an optional alias (plan
arms). "prompt" and "model" remain words for roles and for the CLI (`--with qwen`, `--fill prompt=summarize`), never types.

## N. One word per level (proposal, 10-29; owner: "unify the names of those kinds / types / cats")

Today eight words sort things: header `verb`, module `form` (script / prompt / pipeline), node `kind` (`run:derive`, `model:base`), name
`class` (step / product / task), trust `class` (builtin / hint / valid), table `kind` (raw / output / src / sets), set `kind` (import /
dataset / evalset / input), value `level` (logged / traced / reported). Proposal: **four words, one per level**.

| word | answers | values |
|---|---|---|
| **type** | what is it? (every thing is exactly one) | data · module · artifact · param |
| **kind** | which sort, within its type (declared by the thing, checked by bitt) | data: raw, table, set, dataset, evalset, metric · module: load, derive, check, generate, train, pipeline · artifact: prompt, model, rubric, examples, config (open list) · param: its value's type (int, str, …) |
| **role** | which slot it fills in a recipe | a column the module reads (`text`), an artifact slot (`prompt`, `file`, `rubric`) |
| **tag** | what has been said about a version | version, alias, trust (builtin / hint / valid, per task), verdict, problem, deprecated |

- **A verb is a module kind**: load, derive, check, generate, train, pipeline. The word stays (the trace reads "derive clean → check
  faithful"); it is no longer a command or a card family.
- **Prompt and model stay, as artifact kinds**: a prompt is an artifact of kind `prompt`; a model (weights) is an artifact of kind `model`.
  An endpoint (`qwen`) is a module of kind `generate` (a wrapped connector): the thing that answers. "The qwen model" in speech = that
  endpoint.
- **Retired words**: `form` (= kind), name `class` step / product (= the type: modules and artifacts are what you write, data is what is
  made), trust `class` (= a trust tag), table / set `kind` (= data kinds), `verb` in the header (= `kind`), `runner` and `connector` as
  separate words (= a generate module). `level` (how a value reached bitt) stays: it describes a value, not a thing.
- **Agreed 10-29 (owner)**, written into `words.md` (W13). **Tags are not exclusive** (W14): one version may carry many at once; within one
  tag kind, a version is set once, an alias points at one thing at a time, trust has one current value per task, and a later verdict
  supersedes an earlier one.

## O. Several named inputs (agreed 11-01, owner; issue #2)

A run walks one input (`on`, its units) and may read others by role (`read`). Joining is a step: the shipped `join` module, which bitt computes per table and records per row, keeping the units; recipes and row modules never join. A table module may take named inputs (a union makes new units). The build spec: `inputs.md`.

## P. The charter and the walker (agreed 11-01, owner)

`charter.md` is bitt in one page: what it is, for whom, the layers and why, the guarantees, what is out of scope; every feature is judged against it. `walk.md`: one role registry and one walker for every read of the record.
