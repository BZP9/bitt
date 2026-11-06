# bitt

A research-workflow kernel. Every write (a loaded file, a module, a run, a verdict, a version) goes through one call path that checks
it against cards, records it in an append-only, content-addressed record, and derives what is open, locked, or owed next.

Four types sit on a shelf every task uses: **modules** (a function whose signature is its contract), **wraps** (a module with fixed
params, e.g. an endpoint), **artifacts** (content used whole: a prompt, a rubric, a model file) and **loaded data**. A **recipe** joins a
module to its settings; **one run** does every kind of work (derive, check, generate, train, pipeline) and writes one table per output
contract. **Tags** say what a thing is (a version, an alias, a trust level) without changing it. Tasks, goals and cycles carry the intent.

| read | for |
|---|---|
| `docs/v2/charter.md` | bitt in one page: what it is, the guarantees, what is out of scope |
| `docs/v2/foundation.md` | the design: the four types, recipes, one run, tags, control (`rebuild.md`: how it was built) |
| `docs/v2/kernel.md` | the kernel mechanics: record, card grammar, call path, states, plug-in API |
| `docs/v2/words.md`, `names.md`, `db.md` | the words, names and versions, the database (`db-tour.md`: a real one, generated) |
| `docs/v2/scenarios.md` | every way the owner said they would use it, and its status |
| `docs/v2/inputs.md`, `walk.md` | several named inputs (the join step); the walker (one way to read the record) |
| `spec/cards/*.yaml` | the normative cards; `spec/kernel-contract-cards.md` is their generated table |
| `conformance/` | the suite that proves the rules (two replays, the mutation harness) |

## Layout
```
spec/cards/        the cards (base, record, control, states, module, artifact, data, recipe, run, tag, exec)
src/bitt/          the kernel: call path, control, names, sets, tables, Record backends (memory for tests, Postgres for every store), CLI
src/bitt/tools/    the tools: module, artifact, data, recipe, run (+ rules, pipeline, prompts), tag; envs + bitt_run (the job protocol)
src/bitt/builtins/ shipped modules: checks (nonempty, json_valid, length, contains, exact_match), aggregates (rate, mean, count,
                   agreement), connectors (openai_chat, echo, person), exclude, join, nb_train / nb_predict
conformance/       replays (vk, gw), mutate.py + mutant.py, fake_openai.py (an OpenAI-compatible endpoint for tests and evals)
tests/             pytest, on every backend
scripts/           pg_throwaway.sh (a test Postgres on :55432), conformance.sh (everything), v2_tour.py (docs/v2/db-tour.md),
                   viz_serve.py (`bitt serve` plus the eval and tour stores; the panel: docs/v2/panel.md),
                   viz_evals.py (each eval store's panel as files)
```

## Use
```
export BITT_DSN=postgresql://…/bitt                      # the store: a Postgres database of its own
bitt task new vk "route tickets to the right queue"      # a task (its root goal); bitt cycle new vk "first look"
bitt data load tickets.jsonl --line tickets --does "synthetic support tickets" --sensitivity internal   # raw/tickets (the table raw.tickets)
bitt module add clean.py                                  # its function is its contract: def clean(text: str) -> str
bitt recipe clean --cols text=title                       # the module, these settings: a recipe (label: clean:1d2b8a52)
bitt run go clean:1d2b8a52 --on raw/tickets               # smoke (1 row), then the sample (10): look; again for all (--full: straight on)
bitt data inspect raw/tickets                             # names, never hashes: name@1.0, task/name, raw/x@2
bitt module wrap openai_chat --name qwen --does "qwen on the box" --params url=http://host:8899/v1 model=qwen key_file=~/.config/…/key
bitt artifact add summarize.json --kind prompt            # needs → gives: {column} slots in, the fields it returns
bitt recipe qwen --fill prompt=summarize --cols text=clean --name summary && bitt run go summary --on <the clean run>
bitt run go nb_train:<hash> --on tickets_split --evals queue_acc --env box   # a train: in the background, smoke run first
bitt tag tickets_split --version --because <finding>      # 1.0; a major is a person's
bitt show <anything> · bitt log vk · bitt data tables --task vk          # psql: SELECT * FROM vk.clean (the task's own rows)
```

## Test
```
scripts/pg_throwaway.sh start         # the Postgres backend (tests never touch a live database)
scripts/conformance.sh                # lint · pytest · replays on memory and Postgres · mutations
```
