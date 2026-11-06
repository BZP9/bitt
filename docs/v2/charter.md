# bitt in one page (charter, agreed with the owner 2026-11-01)

Every feature is checked against this page. A change that does not serve it is parked, not built.

## What bitt is

**A memory and a referee for long-running work by one person and their agents.** Every dataset, model and result is versioned and
traced to what made it. Every task carries its own state (where it is, what is open, what is owed, why), so anyone, person or agent,
can pick it up cold. bitt runs the work itself, so nobody can skip a step or claim what did not happen.

## Who

One person and their agents per database. Someone else uses their own database on their own machine. A database is never co-managed;
the split that matters is **person vs agent**: an agent proposes and works, a person approves and versions.

## The layers, and why each exists

| layer | why | rule |
|---|---|---|
| **record** | traceable, versioned datasets, models and results | content-addressed, append-only; the base of everything |
| **run** | the workflow obeys bitt's logic: an agent cannot fake a run, because bitt did it | a module is only logic (a function); bitt reads the rows, runs it, versions and records it |
| **control** | people and agents lose the context of their tasks over time | **the main focus**: memory first (a task's state is read from its records), gate second (what a person must approve) |
| **panel** | see it all | **last**: it reads, never decides; nothing is built for it until the layers below are settled |

## The guarantees (each one checked mechanically)

1. Every made row traces to the raw rows it came from (`__src`) and to the run that made it.
2. A version never moves: it names content by hash. An alias may move; a version may not.
3. A run pins every version it used (module, artifacts, the data it walked and read); the same inputs are the same work, and a row
   is made once per what it read.
4. bitt runs the work; nothing writes but the kernel call path; the record is append-only.
5. Every record says why (its cycle, its because); a task's state is read from its records, never stored.
6. An agent proposes and works; a person approves and versions (a major version, an approval, trust).
7. **Lineage means one thing everywhere**: every walk of the record goes through one walker (`walk.md`), so a rule sees every
   input kind, including ones added later. The SQL walks (`bitt.lineage`, `bitt.downstream`) are tested equal to it on every node (W5).
8. No model is judged on what it saw: what it was trained on, or what was shown to it in a prompt. Checked by content, not only by row
   (#3), and for every artifact a run made from rows (few-shot examples, a rubric: W4); an artifact added by hand from a file saw
   nothing bitt knows of, so examples are made with a run. What a model saw is its units (the tickets it trained on), each down its
   own entry chain; a row a join looked up (a customer's profile) is a feature read again for each unit, never a sample (#6).
9. **bitt does only hard checks** (owner 11-06): a refusal or a warning is an exact fact of the record (equal content, an equal
   key on both sides, a missing step, a missing field). Anything that needs a score and a bar to call something suspicious (near
   copies, a column that "agrees with the label", outliers) is never a bitt rule: it is a module an agent runs as its own check,
   and its result is a hint the agent or a person reads. bitt computes exactly and does the bare minimum; judging is theirs.
   So bitt never cleans or vets data for anyone: no refusal says nothing about duplicates, leaks by meaning, outliers or labels;
   the skill tells agents to check those themselves and to report what they checked.

## Out of scope

- A database shared by several people (each has their own).
- What a remote model serves behind an endpoint (bitt pins the endpoint and its params; it cannot pin the weights behind them).
- The panel, until the layers below are settled.
- Migrations and back-compat until bitt ships (replace, then delete).

## How a new feature is judged

1. Does it make a dataset, model or result more traceable, or its version clearer? (guarantees 1–3, 7, 8)
2. Does it keep a person or an agent from losing context or skipping a step? (guarantees 4–6)

If neither, it is parked. If it adds a way to walk the record, it goes into the walker instead. If it would refuse or warn on a score above a bar, it is a module, never a rule (guarantee 9).

## Order of work (11-01)

1. The walker (`walk.md`): one way to walk the record; the rules rewritten on it. **Done 11-03** (W1–W5).
2. Artifacts made from data (examples, rubrics): made by a run, so guarantee 8 covers prompts. **Done 11-03** (W4).
3. Named table inputs and `union` (`inputs.md` J3). **Done 11-03** (J3, J4).
4. A walk of `scenarios.md` against this page (core / nice / park). **Done 11-03** (#9, the `charter` column).
5. v2.0 (#10: the Qwen round and its audit, the results page, the skill, a full sweep, the tag).
6. The panel.
