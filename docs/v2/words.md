# bitt v2 — words (the glossary, ELI5)

Part of the design (`foundation.md`; the kernel: `kernel.md`). One line per word, in plain language, so the owner, the docs, the
skills and the code say the same thing. Rewritten 2026-10-29 around the foundation's four words (W13); since the rebuild (10-30) the code
says these words too: the last column is where each one lives in it.

## 1. Four words sort everything (W13)

| word | answers | values |
|---|---|---|
| **type** | what is it? every thing is exactly one | data · module · artifact · param |
| **kind** | which sort, within its type; the thing declares it, bitt checks it | see §2 |
| **role** | which slot it fills in a recipe | a column a module reads (`text`); an artifact slot (`prompt`, `file`, `rubric`) |
| **tag** | what has been said about a version | see §5; tags are not exclusive (W14) |

## 2. The types and their kinds

| type | ELI5 | kinds | in the code |
|---|---|---|---|
| **data** | rows with lineage: loaded once from outside, or made by a run | **raw** (a loaded file, never edited), **table** (rows a module made), **set** (which rows, in order, with splits: a list, not a copy), of three kinds: **selection** (a set with no name), **dataset** (a set to train or test on: every row has a split), **evalset** (a set to score on). A number across rows is a column of an aggregate's row (`made.rate`: `rate = 0.81, lo = 0.72, hi = 0.87, n = 100`), not a kind of data | `raw.<line>`, `made.<name>` (`bitt.table` kind raw / output); `bitt.set` kind import / selection / dataset / evalset / run_out |
| **module** | code that does one thing, task-independent, on the shelf, in git; holds only its logic; bitt **runs** it | **load** (outside → raw), **derive** (deterministic code, no model: reshape, split, compute), **join** (bitt looks named inputs up onto the units by key: a step, `lib/join`, no code of its own: `inputs.md`), **check** (measures rows mechanically, never calls a model), **generate** (one call to a model per row: an endpoint such as `qwen`), **train** (makes a model), **pipeline** (orders runs of other modules; an eval is a pipeline with one declared win) | `BITT = {"kind": …}` in the module, its function the contract (tools/header.py); `module.define` |
| **artifact** | content used whole (needs → gives), on the shelf and in git, or made by a run; bitt **fills** it | **prompt** (chat messages with `{slots}`), **model** (weights a train made, or loaded), **rubric**, **examples**, **config**, … (an open list) | `artifact.add --kind`; a trained model: an artifact a train run made (`artifact_kind: model`) |
| **param** | a value given at use, typed by what takes it | its value's type: int, number, str, bool, json | recipe `params` (keyword-only args with defaults) |

- **A verb is a module kind**: load, derive, check, generate, train, pipeline. The trace reads "derive clean → check faithful"; the
  verb is not a command or a card family of its own (W10, W11).
- **An endpoint** (`qwen`) is a generate module: a wrap of a connector with its url, id, key file and effort fixed. "The qwen model"
  in speech = that endpoint. A trained model = a model artifact + an endpoint made when the train lands (W12).
- **A wrap**: a module with some params or artifacts fixed; still a module, versioned, pinning its inner versions (W12).
- Every module and artifact keeps its **origin** (the task and cycle it was added in) and **does** (one line, required) (F18).
- **Built-in**: a module bitt ships (`length`, `exact_match`, `agreement`, `nb_train`, `openai_chat`): `src/bitt/builtins/`.

## 3. Joining types: recipe, run

| word | ELI5 | in the code |
|---|---|---|
| **recipe** | this module, with these settings, on these columns: task + module@v + artifacts `{role: @v}` + params + cols; its hash = the same work; no version of its own; every version it names is pinned when it is made | `recipe.make`; a `recipe` node, `spec_h` = the work |
| **binding** | which column fills each role a module or an artifact needs (`--cols text=body`); every one is bound | recipe `cols`; `recipe.cols_bound` |
| **label** | a recipe's derived handle, always `<base>:<hash8>`: the artifact in its module's main role @v, else the module @v, then the first 8 hex of its work (`summarize@2:1d2b8a52`); it never changes, and the base alone is not a label | `recipe.label` (`summarize:1d2b8a52`); `--name` adds an alias |
| **run** | the walk over a whole set: a recipe over rows, in a cycle, in an env, by an actor, one rung at a time; makes or reuses rows; the module's kind decides the mechanics | `run.go`; `bitt.run`, `bitt.run_end` |
| **extra columns** | what a module returned beyond what it declares: kept in the row's `bitt_extra` with a warning naming them, never refused and never bound by a recipe (A11) |
| **output table** | where a run's rows go: one table per output contract (a module's writes, a prompt's gives), shared by every task; a task sees its own rows by its runs | `made.<name>`, `bitt.writer`; `<task>.<name>` views (A23) |

## 4. The workflow (why the work happens)

| word | ELI5 |
|---|---|
| **task** | the top container with a name (`support`): its namespace and who has authority |
| **goal / sub-goal** | a problem inside a task |
| **cycle** | one question being worked on: **explore** (free, promises nothing) or **working** (must end in a conclusion) |
| **state** | where a cycle is: GOAL / FRAME / WORK / JUDGE / ACT / EXPLORE / PARKED / CLOSED / EARLYSTOPPED (read from its records, never stored) |
| **want** | "this cycle should produce X": a placeholder with a contract; a **fill** is what meets it |
| **plan / arm** | the things to compare (arms) and the eval that judges them, named before the work |
| **decision** | what an eval's rule concluded, with the exact numbers it read |
| **win** | the rule a decision applies, over a column of the one row an aggregate made: `lo >= 0.7` |
| **unit** | a row of the import, set, dataset or evalset the work started from: every run counts per unit (a rate's `n`), whatever rows storage shares (`d15.md`) |
| **aggregate** | a module across rows (`rate`, `mean`, `count`, `agreement`, or yours): it writes one row of whatever columns it declares into its own table; bitt never adds rows up by itself |
| **validation** | a verdict on something: pass / fail, or approve / reject by a person |
| **finding** | what was learned, citing evidence; the because of a tag or of the next cycle |
| **grant** | a person lets an agent do a person's act (close, earlystop) |

## 5. Tags (what has been said about a version)

| tag | ELI5 | in the code |
|---|---|---|
| **version** | `@1.0`, never moves; major = the contract changed (needs a person), minor = only the content | `tag.make --version`: a `tag` node (tag version) |
| **alias** | `@live`, `@best`: a name that moves | a `tag` node (tag alias) |
| **trust** | builtin (bitt ships it, everywhere) / hint (the default) / trusted (promoted in one task, by a person or a measured agreement); can be demoted | a `tag` node (tag trust); `builtin` on a shipped module |
| **verdict** | pass / fail / approve / reject | `validation` |
| **flag** | invalid, untraced, contaminated, frozen test reused, goal drift; answered by **ack** (go on anyway) | flag / warning nodes; `control.ack` |
| **deprecated** | do not use for new work; old records stay readable | a `tag` node (tag deprecated); `recipe.not_deprecated` warns |
| **unversioned** | not a tag: no version tag yet (shown `name, unversioned 3`) | `names.version_of` is None |

## 6. Running safely

| word | ELI5 |
|---|---|
| **ladder / rung** | smoke (1 row: is it wired right? bitt judges) → the sample (10, or the recipe's `sample_rows`: are the outputs as predicted? a person or the plan's eval looks) → all; one call climbs from the smoke rung to the sample by itself and stops; a failed rung stops the climb |
| **full** | from the smoke rung straight to all rows (`--full`; a warning if the sample was never looked at) |
| **smoke run** | a train's first run on a recipe × dataset × env: 1 row per split |
| **reuse** | a row already made by the same recipe on the same read values is never made again |
| **job / env** | work running in the background / a named machine to run on (`local`, an ssh host) |
| **provenance** | how a value reached bitt: computed by a module bitt ran (an aggregate's row), **reported** (the script says so: a row of the train's `made.<module>_report`), *untraced* (the module reached outside: `bitt.run.traced`) |

## 7. When something is off

| word | ELI5 |
|---|---|
| **refusal** | bitt said no; it ends with `next:` (how to put it right) |
| **warning** | allowed, but noted on the cycle |
| **contamination / leak** | scoring a model on rows it trained on / a judge judging its own training data: refused |
| **direct write** | writing to bitt's tables without bitt: refused by the database unless `SET bitt.direct_write = reason` (recorded in `bitt.direct_write`) |

## 8. Names

| word | ELI5 |
|---|---|
| **name** | a handle for a line you come back to: a task, a raw line, a dataset, a module, a wrap, an artifact; one name = one type |
| **namespace** | where a name lives: `raw` (loaded data), `lib` (the shelf), a task (what it made) |
| **`@`** | a version or an alias: `tickets_split@1.0`, `@live`; a bare name = the newest |
| unnamed | runs, rows, sets, params, decisions: reached by hash, `last`, or what made them |

## 9. Retired words (W13, W17)

| old | now |
|---|---|
| `verb` (header), "the five verbs" | a module **kind** |
| `form` (script / prompt / pipeline) | the **type** (module or artifact) and its **kind** |
| name `class` step / product | the **type**: modules and artifacts are written, data is made |
| trust `class` | a **trust tag** |
| table `kind`, set `kind` | **data kinds** |
| runner, connector | a **generate** module (an endpoint) |
| variable, score, metric | a column of an aggregate's row (the one a win reads) |
| bundle | an eval (a pipeline) |
| check (a kernel card), guard | a **rule**; its recorded result a **ruling** (W17); a **check** is only the module kind |
| a person's decision (`control.log.decision`) | a **finding** (a **decision** is only what an eval's win rule concluded) |
| label (a person's act) | **answer** |
| skeleton | a **want** |
| set (the plain node) | a **selection** |
| valid (trust) | **trusted** |
| problem (marks) | a **flag** |
| verdict (a finding kind) | a **conclusion** |
| freeze, cut | a **version** |
| draft | **unversioned** |
| level (of a value) | **provenance** |
| debt, waive | gone (a rule refuses, warns or flags; a person acks) |

## 10. Decisions (settled 2026-10-28/29; all built in the rebuild, 10-29/30)

| # | what | proposal |
|---|---|---|
| W1 | "generate takes a table, walks each row and produces new columns" | **agreed 10-28**: yes, with: the new columns land in a **new table** whose rows point back, and the answerer may be a model, a script or a person |
| W2 | "a check is mechanical and deterministic" | **built 10-28** (`check.determinism`, required by `control.promote`; a judge, a generate recipe, is promoted on its agreement run instead): a rule: a check is mechanical (already: no model calls) **and deterministic** (new: the same `derive.determinism` test, required when a check is promoted to valid) |
| W3 | "variable" or "score"? | **agreed 10-28: metric** (what is measured) with a value per run; CLI and docs say metrics; `variable` stays internal |
| W4 | class `check` shares the verb's name | **built 10-28**: renamed the class to **`builtin`**: `builtin` / `hint` / `valid` |
| W5 | eval / bundle / pipeline | **agreed 10-28**: eval = a pipeline that measures; bundle dropped |
| W6 | task vs goal | **settled 10-28, no change**: task = the named top goal (its namespace); goals and sub-goals inside it; cycles inside goals |
| W7 | "LLM check" | **agreed 10-28**: not a word: it is generate (judge) + check; say "LLM judge" for the generate step |
| W8 | "module" | **agreed 10-29** (owner): a module is any script that runs without being tied to a task: check, generate, eval, a model connector. It holds only its logic; bitt wires the rest (which columns, the rows, the record, the ladder). The task / cycle only picks modules and gives them data and params. **Forms agreed 10-29** (to walk scenarios.md before building): an eval is a module; its steps are Python (making is free flow), its verdict (`win`, `select`) one declared rule bitt checks and records; the JSON step language goes. Module = does (code), prompt = the words a generate module sends, model = a connector module + its params, params = the knobs of one use, recipe = module@v + prompt@v + model@v + params, its hash = the same work |
| W9 | what bitt is, for scripts | **agreed 10-29** (owner): **bitt is the data pipeline when it comes to scripts.** The author writes only the logic; bitt reaches the tables, the models, the splits, the rows and the records. Everything else grows with the workflow / cycle |
| W10 | one call vs the whole table | **agreed 10-29** (owner): **generate** (the verb, like check or derive) is what happens to one row: one call to a model, through its connector. **run** is the walk over the whole table, for every kind: bitt iterates, batches and climbs the ladder; a module only ever sees a row (or the table, for table scope) |
| W11 | the five things | **agreed 10-29** (owner): everything bitt holds is one of five, each with one contract and one handler: **data** (rows with lineage; runs read and make it; raw lines, sets), **module** (code: reads → writes + params; bitt *runs* it; shelf + git), **artifact** (content used whole: needs → gives; bitt *fills* it; shelf + git), **model** (who answers: a connector + its params, or trained weights; the connector *calls* it), **param** (a value given at use, typed by its taker, inside the recipe). Joined by the **recipe** (module@v + artifacts@v + model@v + params + every binding; its hash = the same work) and the **run** (a recipe over data, rung by rung, making data); controlled by the **cycle**. A new need is placed by asking which of the five it is. Outside on purpose: envs (recorded on the run), keys (never stored), actors (on every record) |
| W12 | model, wrap | **agreed 10-29** (owner), built in 6b: **a module with some params or artifacts fixed is still a module** (a *wrap*, on the shelf, its identity = inner module@v + what it fixed). Wraps nest and pin the inner versions (a new inner version moves nothing until wrapped again). Fixed is fixed; what stays open stays open. Inputs only shrink, or are swapped for the needs of an artifact filled in (fixing a prompt: `messages` → its `{q}`); outputs stay the same, or are refined by the filled artifact's gives (the reply read as the prompt's `writes`); a wrap never adds an output its inner module can't produce; a wrap containing itself is refused. **Model** splits: a **model file** is an artifact (loaded, or made by a train run with its lineage); a **model endpoint** is a wrapped connector (`qwen` = `openai_chat` + url, id, key file, effort; a trained model's endpoint = its runner + `file → clf@1.0`, made when the train lands). A recipe = a module (wrapped or not) + its column bindings + per-use params, applied by a run. Kinds stay four: data, module, artifact, param |
| W13 | one word per level | **agreed 10-29** (owner): **type** (data, module, artifact, param) · **kind** (the sort within a type, declared and checked) · **role** (the slot in a recipe) · **tag** (what has been said about a version). A verb is a module kind; prompt and model are artifact kinds; an endpoint is a generate module; `form`, name / trust `class`, table / set `kind`, runner, connector retired (§9). `level` stays (it describes a value) |
| W14 | tags together | **agreed 10-29** (owner): tags are not exclusive: one version can be `@1.0`, `@live`, valid in `support`, approved and deprecated at once. Within one tag kind: a version tag is set once; an alias points at one thing at a time; trust has one current value per task; a later verdict or problem answer supersedes an earlier one |
| W15 | on, read, join, lookup | **agreed 11-01** (owner, `inputs.md`): **on** = what a run walks (its units); **read** = the other inputs it reads, by role (`--read profile=crm/profile@1.0`), taken only by a join and a table module; **join** = the step that looks each unit's row up in a `read` input by key (a **lookup**), keeps the units and links every row read; a repeated key is refused |
| W16 | walker, lineage, story, seen | **agreed 11-01** (owner, `walk.md`): **lineage** = what a thing was made from (the roles of class units, inputs, made_with, made_by); **story** = why it exists (cycle, because, evidence, what judged it), never lineage; the **walker** is the one way to read either; **seen** = the rows an artifact was made from (a model's train split, an examples artifact's picked rows) |
| W17 | the names overview (owner 11-01: "rename those that are confusing or not exact, remove those easy to conflict; don't make confusing wording") | **agreed 11-01, renamed in groups**: (1) a kernel card that judges an act is a **rule** (card kind `rule`, its recorded result a **ruling**, the link to it `ruling`, a policy's link to its recipe `rule`; `tools/guards.py` → `rules.py`; a policy's `guard` → `rule`); a **check** is only the module kind (measures rows); (2) `control.log.decision` removed (a **decision** is only what an eval's win rule concluded); (3) a person's act on an open person run is **answer** (`run.answer`, node `answer`); a recipe's **label** stays; (4) a decision's payload `read` → `row` (**read** is only a run's lookups); (5) how a value reached bitt is its **provenance** (computed / reported / untraced); a cycle keeps its **level**; (6) the plain set node is a **selection** (`--as selection`, BITT `"writes": "selection"`); **set** is only the general word; (7) the node kind `skeleton` → **want**; (8) trust classes builtin / hint / **trusted**; (9) problem marks → **flag**; (10) the finding kind verdict → **conclusion**; (11) role classes `inputs` → **reads**, `refs` → **unsorted**; (12) freeze / cut → **version**, draft → **unversioned**; `nb_runner` → **nb_predict**; (13) removed from the docs: debt, waive, metric as a data kind, bundle. Kept on purpose: **in / on / read** (where / the units / the lookups: 673 + 296 + 65 uses, distinct, no collision), eval / evalset, record (docs) vs node (code), line, the cycle levels explore / working |
