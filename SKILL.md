# bitt skills

One `## skill:` block per tool; every `bitt` command (and `scripts/sync_skills.py`) writes each to `~/.claude/skills/<name>/SKILL.md`,
and removes an installed `bitt-*` skill that has no block here any more. Edit here, never there.
Each block stands alone (an agent loads one), so the setup lines repeat.

## skill: bitt
**Trigger**: running a model over a bitt dataset, scoring / evaluating, training, or any other use of the `bitt` CLI (the workflow kernel at $WORK_ROOT/bitt). Loading files, derives, datasets and inspecting: the bitt-data skill.

### Setup (every command)
- Run from anywhere: `uv run --project $WORK_ROOT/bitt bitt <command>` (below: `bitt`).
- **This skill has every command you need: do not open bitt's docs or code** (they are for the people building bitt);
  `bitt <command> -h` shows a command's flags.
- The store: `BITT_DSN`, a database of bitt's own (`scripts/install.sh` sets one up: `bitt-store start`). Ask the user if none is
  set. Never another system's database (company / production data).
- You are an agent: always pass `--as agent:<your name>` (or `export BITT_ACTOR=agent:<name>`). Never `--as usr`.
- A refusal prints `refused: <reason>` with a `next:` step and exits 2: do the `next:` step, do not retry the same command.
- **Never write the store directly** (psql, a script with BITT_DSN): the database refuses it. Everything goes through a `bitt`
  command or `bitt call <card> k=v …`.
- Names, never hashes: `name`, `name@1.0` (a version), `name@best` (an alias), `task/name` (another task's), `raw/line`, `last`.
- Another task's data: read its **version** (`--on intake/tickets@1.0`): pinned, and nothing is made in that task. Anything else of
  another task (a run, a selection, an unversioned dataset) warns `not a version`, and what you make from it cannot be versioned
  until that task versions it.

### The words
- **On the shelf** (every task uses them): a **module** (a Python file: `BITT = {"kind": …}` and one function whose signature is
  its contract; its docstring's first line says what it does), a **wrap** (a module with params fixed: an endpoint), an
  **artifact** (content used whole: a prompt, a rubric, a model file). Kinds of module: load, derive, check, generate, train, pipeline.
- A **recipe** = a module + which columns fill its roles (`--cols text=title`) + its artifacts (`--fill prompt=summarize`) + params
  (`--params k=v`). It is named for you: its label is the prompt's name (else the module's), then its hash (`summarize:1d2b8a52`).
  **Copy the label from `bitt recipe`'s output**: the name alone is refused (the refusal lists the labels). `--name <alias>` adds a
  fixed name of your own beside it.
- A **run** = a recipe over data on a **ladder bitt climbs by itself**: one call runs the smoke rung (1 row: is it wired right?) and,
  when that is clean, the sample (10 rows, or the recipe's `--sample-rows N`), then stops so the outputs are looked at; the same command
  again runs all the rest. `--full` runs the smoke rung, then all (a warning if the sample was never looked at): use it only for a
  person's recipe (it asks every row) or a step whose sample you already looked at; a model's step climbs. A failed rung stops
  the climb. Rows already made are never made again, so a stopped or failed run resumes with the same command.

### Where work goes
- `bitt tasks`; `bitt task new <name> "<problem>"` (a person's); `bitt cycle new <task|goal> "<question>" [--level working]` (a new
  cycle is your current one); `bitt cycle use <task>#N`, `bitt cycle list`. `--in <cycle | task>` works elsewhere for one call.

### Run a prompt on a model
1. **An endpoint** (ask the user for the URL, the model id it serves and where the key file is; never put a key on the command
   line, in a file you write, or in your report):
   `bitt module add openai_chat` (the shipped connector, once), then
   `bitt module wrap openai_chat --name qwen --does "qwen on the box" --params url=http://<host>:<port>/v1 model=<served id> key_file=<path>`.
   A prompt fixed in too makes a router that needs only the row's columns: `bitt module wrap qwen --name router --does "…" --fill prompt=<prompt>`.
   A stub for a dry run: the shipped `echo` (`bitt module add echo`; it replies with the prompt).
2. **A prompt** is a JSON artifact: `{column}` slots are what it needs, `gives` the fields it returns. With `gives` the model must
   reply with a JSON object holding them (a plain-text reply fails its row: say so in the prompt); for one plain answer leave `gives`
   out (one text column, named after the prompt):
   ```json
   {"bitt": {"does": "Summarize a question as a title."}, "gives": {"title": "text"},
    "messages": [{"role": "system", "content": "Reply in JSON with a title."}, {"role": "user", "content": "Summarize: {q}"}]}
   ```
   `bitt artifact add summarize.json --kind prompt`.
   **Examples picked from rows** (few-shot, a rubric's worked cases) are never a file you write by hand: make them with a run, so bitt
   knows which rows they came from: `bitt run go <select recipe> --on <data> --as artifact --artifact-kind examples --line shots`,
   then fill a role with it (`--fill shots=shots`). Scoring on rows the examples came from is refused (`run.contamination`).
3. `bitt recipe qwen --fill prompt=summarize --cols q=question` → the recipe `summarize:<hash>`; `bitt run go summarize:<hash> --on raw/<line>`
   (again to climb). A model the endpoint does not serve is refused before anything runs.
   **Several asks per row**: `bitt recipe qwen --fill prompt=summarize --cols q=question --samples 3` → `summarize:<hash>x3`; `bitt run go summarize:<hash>x3 --on <data>` (again for the rest) asks 3 times per row (the samples are the recipe's: the same recipe always asks the same number of times); a check and
   `rate` over that run count every ask (`n` = rows × 3). Running `go` again never asks again (the same rows are reused).
4. **Prompts in a row**: `bitt run go polish:<hash> --on <the first run>`; or a pipeline module that runs both (below).
5. **Look**: `bitt data inspect <run>` (rows), `bitt run status [<run>]`, `bitt show <anything>`.
- A reply (or a module's output) with fields nobody declared: kept in the row's `bitt_extra` and warned (`kept columns the module does
  not declare`); declare them (the prompt's `gives`, the module's return type) to use them downstream: `bitt_*` columns are never bound.

### Score
- **bitt does not clean or vet your data.** It refuses only exact facts: a model scored on rows it trained on (equal content),
  a group on both sides of a split, a missing step or field. No refusal means nothing about anything else in the data: that is
  yours to check. Say in your report what you checked.
- A **check** module never calls a model: `def short(text: str, *, max: int = 50) -> bool`. Shipped (add one by its name first:
  `bitt module add exact_match`): `nonempty`, `json_valid`, `length`, `contains`, `exact_match` (a, b).
- `bitt recipe exact_match --cols a=pred b=tickets.queue` (`table.column` reads a column of a table above: each ticket's own),
  `bitt run go exact_match:<hash> --on <run>` → per-row verdicts, and nothing else.
- **Across rows is a module of its own** (an aggregate: one row of what it declares). Shipped: `rate` (x: a bool column → `rate, lo,
  hi, n`, a 95% interval), `mean` (x: a number column → `mean, lo, hi, n`), `count` (→ `n`), `agreement` (a, b → `agreement, kappa, n`).
  `bitt recipe rate --cols x=exact_match`, `bitt run go rate:<hash> --on <the check's run>` → `row: rate = 0.81, lo = 0.72, hi = 0.87, n = 100`.
  `n` counts units (the rows of the data you started from, every sample), even where equal inputs share one stored row. Your own:
  `BITT = {"kind": "check", "scope": "table", "reads": ["x"]}`, `def longest(rows: list) -> Longest` (a TypedDict of its columns).
- **A setting fixed for good** is a wrap, not a default in your own module (a recipe can change a default): `bitt module wrap
  length --name short12 --does "at most 12 words" --params max=12 unit=words`.
- **An LLM judge** is a prompt (a generate step), then a check over its verdicts: an LLM is never a check.
- Scoring a model on rows it trained on is refused (contamination), and so is a judge model trained on what it judges (leak).
- A check of your own is a **hint** in its task until a person trusts it. You make the agreement run (it against a person's labels;
  it must give the same verdicts twice) and ask; the person runs `bitt tag <check> --trust trusted --agreement <run> --because <finding>`, never you.

### People label
`bitt recipe person --fill prompt=<ask> --cols reply=<column>`, `bitt run go person:<hash> --on <run> --full`: the run stays open (it blocks
nothing). The person's answers: `bitt run answer <run> --file answers.jsonl` (`{"row": <hash>, "answer": "…"}` per line), then
`bitt run close <run>` (unanswered rows are counted, never invented).

### Train
bitt does not train: your module does, in the background, here or on an env (`envs.yaml`: ask the user which).
1. A train module: `BITT = {"kind": "train", "reads": ["text", "label"], "reports": {"acc": "number"}}`, `def train(job, *, alpha:
   float = 1)`: `job.input` (`{split: [rows]}`), `job.seed`, `job.output` (write the model files there), `job.report(step=1, acc=…)`:
   rows of `made.<module>_report`, kept as reported, never a score; a name it does not declare in `reports` fails the landing.
   Shipped (`bitt module add nb_train`, `bitt module add nb_predict`): a CPU text classifier and the module that predicts with its model.
2. `bitt recipe nb_train --cols text=title label=queue`; name the eval first (a check recipe): `bitt run go nb_train:<hash> --on <dataset>
   --evals <check recipe> --endpoint nb_predict [--env <name>]`. **The first call is a smoke run**; the same command again trains in
   full. `bitt run sync` lands finished jobs: the model is an artifact, its endpoint `<name>_endpoint` a wrap you run like any model.

### Pipelines and evals
A pipeline module orders runs; an eval is a pipeline with one `win` rule over a column of the one row its function's run made (an
aggregate's: return the `rate` run, never the check's):
```python
"""Grade replies: the judge says OK for most of them."""
BITT = {"kind": "pipeline", "win": "lo >= 0.5"}


def grade(b, on, *, model: str = "qwen"):
    j = b.run("judge_reply", on=on, with_=model, cols={"reply": "polish"})
    v = b.run("says_ok", on=j, cols={"verdict": "judge_reply"})
    return b.run("rate", on=v, cols={"x": "says_ok"})
```
`b.run(name, on=…, with_=<endpoint>, cols=…, params=…)` runs a module, or a prompt on an endpoint; every name is pinned when the
pipeline's recipe is made. `bitt run go grade:<hash> --on <run>` → a decision keeping the row it read. To be sure beyond noise, compare the
interval's bound (`lo >= …`), not the rate itself.
A step that joins a second input: run the pipeline with `--read profile=<data>`; inside, `b.run("join", on=on,
read={"profile": b.read["profile"]}, cols={"tier": "profile.tier"}, params={"key": {"profile": "customer_id"}})`, then the next step
runs `on=` that join.

### A working cycle (a person opens it; you fill it)
1. `bitt want <dataset|evalset|artifact|recipe|run> --name <name>` → a want.
2. `bitt plan --arms <want or ref> … --win "<rule>" --eval <eval pipeline>` (or `--judged-by person`). **Your plan is a
   proposal**: its eval does not run and nothing is measured until a person approves it (`bitt validate <plan> approve`); their
   approve runs the eval on every arm you already filled.
3. Fill each arm with a run; once the plan is approved, the plan's eval runs on it by itself. An arm that is a want: `bitt run go … --fills <want>`. An arm
   that is a ref (a recipe you named in `--arms`): run it as it is (`bitt run go <recipe> --on … --full`), no `--fills`. Never
   re-plan to change an arm into a want, and never judge an arm by hand (a check you run yourself in a working cycle is warned:
   its verdicts are a hint, never the cycle's result). An eval that pins its evalset (a wrap: `bitt module wrap <eval> --name <n> --does … --pin on=<evalset>@<v>`)
   judges every arm on exactly that: `--on` it; for other data use or make another wrap. An arm an eval judges runs on a version (`--on <line>@<version>`): on
   a raw import it is refused. `--eval` names the eval pipeline module, not a recipe of it.
4. When every arm is measured: `bitt note "<what the evidence says>" --evidence <decision or run> --conclusion`. Then **stop and report**.
- **A person's acts** (refused for you: say so and stop): approve / reject, a major version (a dataset's or an evalset's first
  version is a major, so it needs a person's approve on it first; a module's or an artifact's first version is yours), a protected alias (`live`), any trust tag,
  closing a working cycle (unless granted: `bitt grant agent:<you> close --on <cycle> --reason "…"`), opening goals, policies.
- `bitt ack <ref> --rule <id> --reason "…"` goes on past a warning that allows it; `bitt cycle park|resume|abandon|earlystop|close`.
- When the owner drops an option, write it down: `bitt note "dropped: <the option>: <why>"`. Before you propose anything, read the
  task's notes (`bitt log <task>`); never bring a dropped option back without saying why it should return.

### When bitt is wrong
A bug, a refusal or message that makes no sense, a `next:` that does not work, a command you needed and could not find, or a step of
this skill that is wrong: finish or stop your task as usual, then report it once, so bitt gets fixed.
- Search first: `gh issue list -R BZP9/bitt-private --search "<two or three words>"`; on a match, add a comment (`gh issue comment`) instead.
- Else: `gh issue create -R BZP9/bitt-private --title "[agent] <one line>" --body "<what you ran, what it printed (any refused: line verbatim),
  what you expected, and bitt's commit: git -C $WORK_ROOT/bitt rev-parse --short HEAD>"`.
- Synthetic names only: never data rows, file contents, keys, URLs, hostnames or company names. One issue per problem.
- **Keep your logs for the owner** (on this machine, never in the issue: they hold data): make `~/.bitt/agent-logs/<YYYY-MM-DD>-<issue
  number>/` and put there (1) your session log: Claude Code → copy the newest `.jsonl` in `~/.claude/projects/<your working dir, / as
  ->/`; opencode → `opencode export <your session id> > session.json`; another harness → its transcript, or say you have none; and
  (2) bitt's own record: `bitt log <task> --all > bitt_log.txt` (every act, refusal and warning, in order, timed). Name the folder in the issue (`logs: ~/.bitt/agent-logs/…`).
- No `gh`, or `BITT_ISSUES=off` is set (evals set it): put the same text under **bitt issues** in your report instead (an eval
  keeps your log itself: skip the copy).

### Report back
What you ran and what it printed: the names you made, each run's line (rung, made / reused / failed, status, any warning), each
aggregate's row (a rate with its interval and n), any `refused:` line verbatim, and any bitt issue you filed (its URL). Never the key.

## skill: bitt-data
**Trigger**: loading a file (xlsx, csv, jsonl, json) into bitt, writing or registering a module (a script with a BITT header) that cleans / reshapes / splits / filters data, deriving over loaded rows, building a dataset or evalset, finding data you were not given the name of ("there should be a dataset about …"), or looking at what bitt holds (list, inspect, tables), with the `bitt` CLI (the workflow kernel at $WORK_ROOT/bitt).

### Setup (every command)
- Run from anywhere: `uv run --project $WORK_ROOT/bitt bitt <command>` (below: `bitt`).
- The store: `BITT_DSN`, a database of bitt's own (`scripts/install.sh` sets one up: `bitt-store start`). Ask the user if none is
  set. Never another system's database (company / production data).
- You are an agent: always pass `--as agent:<your name>` (or `export BITT_ACTOR=agent:<name>`). Never `--as usr`.
- Work happens in a cycle: commands without `--in` work in your current cycle (`bitt cycle use <task>#N`; `bitt cycle list`);
  `--in <task>#N` works elsewhere for one call. Several open and none current → refused, listing them: pick one, never guess.
- Names, never hashes: `qs_split`, `qs_split@1.0` (a version: digits only, never `@v1`), `raw/qs` (raw is always written `raw/…`;
  `raw/qs@2` = its 2nd import), `other_task/name`, `last`. A name is `[a-z][a-z0-9_]*` and never ends in a version.
- A refusal prints `refused: <reason>` and exits 2: do what its `next:` says, do not retry the same command.

### 1. Load a file
`bitt data load <file> --line <name> --does "<what the data is, one sentence>" --sensitivity <public|internal|company|personal>` →
`raw/<name>` (the table `raw.<name>`, distinct rows) + an import. `--does` is how the data is found later: say what the rows are and
where they came from ("questions clients sent to the help desk, 2025 export"), not the file name. Ask the user for the sensitivity;
never guess it. The same line again = another import over the same
table (rows already there are not stored again). `--sheet` for an xlsx sheet; a format bitt does not read: a load module
(`BITT = {"kind": "load"}`, `def read(data: bytes) -> list`) and `--with <it>`.

### 2. Write a module: only the logic
A row module is one annotated function: its positional arguments are the columns it reads (each a role a recipe binds), its
keyword-only arguments (after `*`) its params, its return type what it writes (one column named after the function):
```python
"""Strip and lower-case a question."""
BITT = {"kind": "derive"}                # or "check" (a row verdict: return bool or a number)


def question_clean(question: str, *, lower: bool = True) -> str:
    q = question.strip()
    return q.lower() if lower else q
```
- Types: `str` (text), `int`, `float` (number), `bool`, `dict` / `list` (json). Several outputs: return a `TypedDict`. A key you
  return but did not declare is kept in the row's `bitt_extra` with a warning (`kept columns the module does not declare`), and no
  recipe can bind it: declare it to use it downstream.
- A **select** (a split, a filter, a sample, the test side) makes a set, never a table:
  ```python
  """Every third question id is test."""
  BITT = {"kind": "derive", "writes": "selection", "reads": ["qid"]}


  def split(rows: list) -> list:              # every input row (the `reads` columns), in order
      return [(i, "test" if int(r["qid"][1:]) % 3 == 0 else "train") for i, r in enumerate(rows)]
  ```
  Return `(index, split)` for each row kept (`train` / `val` / `test`); leave a row out to drop it.
- The module never opens files, the network or the database: it gets its rows and returns its output (an import of `socket`,
  `requests`, `subprocess` … is recorded as untraced, with a warning).
- `bitt module add <file.py>` puts it **on the shelf** (every task uses it by its short name; the same name again = its next
  version; recipes keep the version they used). Commit it in git: a version tag needs committed code.
- Name a module after what it does (`split_by_qid`), never after the dataset it makes (`tickets_split`): a name is one kind.

### 3. A recipe, then a run
- `bitt recipe <module> --cols <role>=<column> …`: bind every column the module reads (`--cols question=body`; `qa.question` reads
  a column of a table above). An unbound role is refused. Params: `--params lower=false`. It prints the recipe's label
  (`clean:1d2b8a52`): use that label (or a `--name` you gave it) in `run go`; the module's name alone is refused.
- `bitt run go <recipe> --on raw/<line>` (or `--on <dataset>` / `--on <run>`): bitt climbs by itself, the smoke rung (1 row) then
  the sample (10, or the recipe's `--sample-rows`), and stops; look at the sample, then the same command runs the rest; `--full`
  goes from the smoke rung to all. A failed row fails the run: fix the module, `module add` it, a new recipe.
- A run counts **per row of the data you started from** (a unit): rows with equal values share one stored row, but a run over a run
  keeps one entry per unit, and `--cols b=tickets.label` reads each unit's own ticket.
- Two tables (tickets and a customer profile, outputs and an answer sheet): **join first, as its own step**, never inside a module:
  `bitt module add join`, then `bitt recipe join --cols tier=profile.tier --params key='{"profile": "customer_id"}'` (each picked
  column ← `<role>.<column>`; `key` names the column both sides share, or `{"profile": {"cust_id": "customer_id"}}`), then
  `bitt run go join:<hash> --on raw/tickets --read profile=raw/profile`. It keeps your units (one row per ticket, the same splits):
  later steps run `--on <the join run>` and read `tier` and the ticket's own columns. **Split first, then join**: make the dataset on the tickets, then join onto it (the join keeps the splits); a dataset made over a join's rows is refused when tickets share a stored row. A key that repeats in the lookup is refused
  (dedup it first). A ticket with no profile row reads empty (a warning with the count); `--params miss=drop` leaves it out,
  `miss=fail` fails it. A second input on any other step is refused with this same `next:`.
- The same kind of rows from two places (tickets by email and by chat): **union** them, a step of its own: `bitt module add union`,
  `bitt recipe union --params key='["ticket_id"]'` (no key: rows equal in every column are one), then
  `bitt run go union:<hash> --on raw/email --read chat=raw/chat`. Each ticket comes out once and links every source row; every
  input needs the columns of `--on` (derive them to the same columns first). Your own merge: a table module that names its
  inputs, `def merge(rows: list, chat: list) -> list` (`--read chat=<data>`), each row's `bitt_from` an index into rows or
  `["chat", i]`.
- Every matching row, as a list (a customer's ticket history): `--params many='["hist"]'`. Only what happened before each ticket
  (never the future, so nothing leaks): `asof='{"hist": ["closed_at", "created_at"]}'` (the history's time, the ticket's time).
- A select: `bitt run go split:<hash> --on raw/<line> --as dataset --line <name>` (a dataset: every row has a split, train / test),
  or `--as evalset` (rows you only score, e.g. the test side of a dataset), or `--fills <want>` in a working cycle. Rows split by group (a thread, a customer) must not land on both sides: refused, with which groups leak.
- Rows found bad in a versioned dataset: `bitt data exclude <dataset> --rows <file of row hashes> --because "…"` makes a new set
  without them (the old version keeps its rows); a later set that still holds them is warned.
- A version (a dataset, a module, an artifact: anything on a line): `bitt tag <it> --version --because <finding>` (a finding:
  `bitt note "…" --evidence <a run or a validation>`); `--version`, `--trust` and `--deprecated` always need `--because`; a dataset's
  major (the first version, or test rows changed) needs a person's approval first (`bitt validate <dataset> approve`, a person's act:
  if it is refused for you, say so and stop).
- **Evidence stands on versions.** A version or a trust (of a module, a model, data) cites evidence measured on a dataset or evalset
  *version*, never on a raw import or a scratch selection: version the evalset first, measure on `<line>@<version>`, then cite that.

### 4. Look
- **bitt does not clean or vet your data.** It refuses only exact facts: a model scored on rows it trained on (equal content),
  a group on both sides of a split, a missing step or field. No refusal means nothing about anything else in the data: that is
  yours to check. Say in your report what you checked.
- **Finding data by what it is** ("iirc there is a dataset about client questions"): `bitt data list <words>` (every named raw
  line, dataset and evalset that mentions any word, in its name, what it is for, its columns or its source; most matches first;
  a dataset says the module that made it and from what); `bitt data list` alone shows every line. Then read the candidate:
  `bitt data inspect <ref> -n 5`, and say which line you picked and why. Finding data writes nothing.
- `bitt data inspect <data> [-n 20] [--task T]`: its rows in order with their split (one per unit; `--task`: only that task's own
  rows, `N of M rows are task T's` first); `bitt data tables [--task T]`
  (every table; `--task`: that task's own rows); `bitt show <anything>`; `bitt log [task]` (what happened, in order; `--all`: every refusal and warning too, with the time).
- In SQL (read only): `SELECT * FROM <task>.<name>` (the task's rows of a made table), `bitt.v_run`, `bitt.resolve('<name>')`.

### When bitt is wrong
A bug, a refusal or message that makes no sense, a `next:` that does not work, a command you needed and could not find, or a step of
this skill that is wrong: finish or stop your task as usual, then report it once, so bitt gets fixed.
- Search first: `gh issue list -R BZP9/bitt-private --search "<two or three words>"`; on a match, add a comment (`gh issue comment`) instead.
- Else: `gh issue create -R BZP9/bitt-private --title "[agent] <one line>" --body "<what you ran, what it printed (any refused: line verbatim),
  what you expected, and bitt's commit: git -C $WORK_ROOT/bitt rev-parse --short HEAD>"`.
- Synthetic names only: never data rows, file contents, keys, URLs, hostnames or company names. One issue per problem.
- **Keep your logs for the owner** (on this machine, never in the issue: they hold data): make `~/.bitt/agent-logs/<YYYY-MM-DD>-<issue
  number>/` and put there (1) your session log: Claude Code → copy the newest `.jsonl` in `~/.claude/projects/<your working dir, / as
  ->/`; opencode → `opencode export <your session id> > session.json`; another harness → its transcript, or say you have none; and
  (2) bitt's own record: `bitt log <task> --all > bitt_log.txt` (every act, refusal and warning, in order, timed). Name the folder in the issue (`logs: ~/.bitt/agent-logs/…`).
- No `gh`, or `BITT_ISSUES=off` is set (evals set it): put the same text under **bitt issues** in your report instead (an eval
  keeps your log itself: skip the copy).

### Report back
The names you made (`raw/…`, the module, the dataset, with versions), each run's line (rung, made / reused / failed, status),
any `refused:` line verbatim, and any bitt issue you filed (its URL).
