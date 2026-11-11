# The kernel (contract 2.0)

The mechanics every bitt write keeps, whatever tool makes it: the record, the call path, the cards, the states. What the tools do (load,
define, wrap, recipe, run, tag) is `foundation.md`; the words are `words.md`; the tables are `db.md`. The normative card text is
`spec/cards/*.yaml`; its generated table is `spec/kernel-contract-cards.md` (`uv run python scripts/gen_appendix.py`). Where this page and
a card differ, one of them has a bug; the conformance suite (§10) decides. (It replaces `spec/kernel-contract.md`, v1.0; that history is at
the tag `pre-foundation`.)

## 1. Layers
| layer | is | depends on |
|---|---|---|
| **kernel** (`src/bitt/kernel.py`, `control.py`, `record/`, `names.py`) | the record, the one call path, Control (tasks, goals, cycles, plans, approvals, grants, policies), the shared checks, the plug-in API | nothing |
| **tools** (`src/bitt/tools/`) | module · artifact · data · recipe · run · tag · exec: each a `Package` of cards plus their impls, checks, finish handlers, listeners | the kernel |
| **backends** | where a job runs (`envs.yaml`: local, ssh), what a connector calls (an OpenAI-compatible endpoint) | nothing of ours |
| **surface** (`src/bitt/cli.py`, `SKILL.md`) | the `bitt` CLI over `kernel.call` and the record's reads | the kernel and the tools |

- Dependencies point one way. The kernel never imports a tool; a tool joins through `Package` (§8).
- A write runs **only** through `kernel.call`, so recording cannot be bypassed. The code inside an impl or a module stays free.
- Nested calls follow the tool DAG (`base.yaml: dag`): `control → tag → run → recipe → data → artifact → module → exec → record`; a tool calls
  only tools to its right.

## 2. The record
- **One Postgres** holds the graph (`bitt.node`, `bitt.link`, owned by the kernel) and the data tables (`raw.*`, `made.*`, the fixed `bitt.*`
  tables: `db.md`). A node and its rows commit in one transaction. The memory record (`record/memory.py`) is the same contract for tests.
- **Append-only.** Triggers refuse UPDATE / DELETE / TRUNCATE on every table; only the kernel's own session (`bitt.writer = 'kernel'`) inserts.
  Something learned later is a new node pointing at its subject: an outcome, a validation, a tag, an ack, a flag, a warning.
- **The record enforces the tables' shapes**, whatever tool writes them: a table exists only as one of the shapes (raw, output, src, sets,
  fixed), made with its creating node; an unregistered column is refused; every foreign key resolves; a row whose key exists is not written
  again (dedup). No column is dropped, renamed or retyped.
- **One writer per database.** A kernel assigns `seq` from its own journal; a commit the store refuses raises `Failed` and leaves the kernel
  usable (the refusal record is then kept in memory only, marked `unrecorded`).

### 2.1 Nodes
- A node is `{id, kind, payload, links, stamp}`; `id = h("node", canonical({kind, payload, links, stamp}))`. **Links are part of the
  identity.** `stamp = {tool, card, contract, actor, at}`. `seq` (commit order) is stored beside the node, never hashed.
- **One value space on every backend:** an integral float becomes an int, text is NFC with `\n` line ends, and NaN, ±infinity and NUL are
  refused (`Failed`). So an id re-verifies after any round trip.
- Rows, files and weights are referenced by content hash (blobs: `BITT_BLOBS`). **One node per batch, never one per row.**

### 2.2 Links and roles
- Links point child → parent only and hold hashes. Downstream is a computed reverse index.
- **A link's role is the name of the input field it came from.** An impl may add only `base.yaml: impl_roles`.
- **Every role has one class** (`base.yaml: roles`, `walk.md` §2): units (`on`), inputs (`read`), made_with, made_by, refs, and
  **story** (`in, origin, because, evidence, fills, subject, judged, …`: why / where / judged by). Every class but story is **lineage**
  (what it was made from). A role means one thing everywhere; lint refuses a role in two classes and a role a card or impl can write
  that is in none. Every walk of the record goes through the walker (`src/bitt/walk.py`); the work hash (`spec_h`) leaves story out.

### 2.3 Proposals and refusals
- A call builds a **proposal** in memory; it commits only when every requirement passes, so nothing is ever rolled back.
- The refused *attempt* becomes one `refusal` node linked only by `in`, or a row of `bitt.refusal_log` when `in` cannot be resolved. Its
  args are sanitized (refs and short values).
- A nested call that is refused is dropped **even when the impl catches the refusal**: its part of the proposal and its queued events go.

### 2.4 Names
`names.md` is the full grammar. A name is a `name` node bound to a line's root: namespace `''` (a task), `lib` (the shelf: modules and
artifacts, every task's), `raw` (a raw line, always written `raw/x`) or a task (its data lines and recipes). Versions and aliases are `tag`
nodes on the unchanged thing (W14): `x@1.0`, `x@1` (the newest 1.x), `x@best`. A ref may also be an id or a unique ≥ 8-hex prefix. The SQL
`bitt.resolve()` reads names the same way (`tests/test_tag.py` pins the two to agree).

## 3. Roots, actors, authority
- **Roots** (`base.yaml: roots`) write with no `in`: `control.goal.open_root` (a task), `data.load`, `module.define`, `module.wrap`,
  `artifact.add` (the types and the loaded data are global), and `exec.job.sync`. Every other maneuver needs `in` → an open goal or cycle.
- **Actors:** `usr[:name]` · `agent:<name>` · `system` · `pipeline:<run>` · `policy:<id>`; anything else is refused. A nested call carries its
  caller's actor (`exec.job.finish` is always `system`); the kernel takes the actor and the DAG caller from its own stack, never from what an
  impl passes. Authenticating the actor is the surface's job; actors compare as exact strings.
- **Authority:** a task's `authority` is a list of usr actors (default: the opener, when a usr). Goals, policies, approvals (`approve` /
  `reject`), a major version, a protected alias and any trust tag are a person's in authority. Agents never approve; `pass` / `fail`
  validations are open to all. A person may **grant** an agent `close`, `earlystop` or `validate_pass` over a cycle, goal or task, and revoke
  it; a revoke stops the grant from then on.
- **Judgments are task-local** (`control.same_task`): a validation or an ack concerns only its own task's nodes or an arm its cycle adopted;
  an approval opens only the gate of the task it was written in, and the latest one counts (a later `reject` revokes it).

## 4. Cards
```yaml
- id: run.go
  kind: maneuver            # maneuver | check | internal | base
  extends: base.write       # inherits in / out / requires
  open_in: [GOAL, WORK, JUDGE, EXPLORE]   # the state lock; absent = base.yaml default_open_in
  kind_of: recipe           # optional: the module kind of this input is `kind` in `when:` (and in `open_in_by_kind`)
  in:  {min: {...}, opt: {...}}
  out: {min: {...}, opt: {...}}
  requires: [{rule: run.group_leak, subject: set, when: "as == dataset", on_fail: refuse}]
  calls: [exec.job.submit]  # nested calls, along the DAG
  emits: [run.done]
  cache: never              # checks: `subject` (default) or `never`
  reads: before             # checks: judged before the impl
```
- A requirement is `{check, subject, on_fail, when?, if_acked?, on_unknown?, kind?, deferred?}`; lint refuses any other key.
- **Field forms:** `{ref: [kinds], state, many}` (an upstream node), `{type: …}` (a value: `pattern`, `values`, `nullable`, …), `{ref_out:
  kind}` (a node this card makes), `required_when: <when>`. MIN in missing → refused; MIN out missing → `Failed`; an input not in the card,
  or a list for a single ref, is refused; `_`-inputs are reserved.
- **`when:`** (no code is ever evaluated): `FIELD given` · `FIELD == WORD` · `FIELD in [A, B]` · `FIELD in SETNAME` (`base.yaml:
  named_sets`), joined by ` and `.
- **Subjects:** `every ref` (record.resolve), `every ref input` (control.task_boundary), `every input` (lineage inputs: control.goal_drift),
  a path `FIELD(.ROLE)*[sel]`, a pair `a × b`, or a tuple `a, b`.
- **Never duplicate:** a property is judged by exactly one check; every card that needs it cites it (lint: a card taking `fills` cites
  `control.fills`).

## 5. The call path (every write, in this order)
1. the card is callable (a maneuver, or an internal card called by a card that lists it in `calls`); the actor's kind is valid
2. **policies:** every policy on this card under the call's goal runs its rule (a check recipe) on the call's inputs (`run.policy_runner`); a false
   verdict refuses the call
3. **inputs:** MIN present, nothing unknown, refs resolve, kinds match, each ref's `state:` holds
4. **state lock:** the `in` node's derived state (§7) is in `open_in` (never CLOSED or EARLYSTOPPED); the refusal names the state, what
   moves it on, and the open verbs
5. the `reads: before` checks (judged on the state before the call)
6. the **proposal:** the event, then the impl's outputs; nested calls join it
7. every other non-`deferred` requirement, judged on the proposal, in card order
8. MIN out present
9. the marks: flags point at the main output, warnings at the subject that warned (and reach the caller's `warnings`)
10. **commit**, append to the journal
11. drain the emitted events to the listeners (a plan's eval measures its arm: `tools/pipeline.py`); each is its own call, recorded and
    never raised to the caller of the committed one

A refusal at 1–9 drops the proposal and records the attempt (§2.3). **Any other exception an impl raises is `Failed`**, dropped and
recorded the same way; the kernel is left ready for the next call.

## 6. The requirement ladder
| `on_fail` | effect |
|---|---|
| `refuse` | nothing is written beyond the refusal record |
| `refuse` + `if_acked: mark_invalid` | refused unless an ack covers it; after the ack: written, plus a flag with `acked: true` |
| `mark_invalid` | written, plus a flag (`acked: false`); never a win |
| `warn` | written, plus a warning; shown in the call's output. Never an obligation |
| `skip` | not checked |
| `deferred: true` | judged when the job lands (`exec.job.finish`): a train's fill is judged on its model |

- `unknown` verdicts take `on_unknown` (default: `on_fail`).
- **Acks:** `control.ack subject=<node> check=<id> [against=<other>]` covers that check on that subject; an ack with no `check` acks goal drift.
- A **check** returns `pass | fail | unknown` and writes a `check` node cached by its subject (computed once, cited forever); `cache: never`
  means it reads later state (approvals, states, other tasks), and an uncached pass writes no node.
- A rule that needs compute (`tag.deterministic` runs a check module twice; a policy's rule runs a check recipe) runs scratch jobs with no
  records; its verdict is a function of their output.

## 7. Goals, cycles, states (derived; nothing stored)
- A **task** is a root goal; goals and sub-goals are a person's (`control.goal.open`; a changed `contract` is a goal major, and inputs built
  under the old goal warn: `control.goal_drift`). The root task is never superseded (`control.not_root`).
- A **cycle** lives under a goal: `working` (the machine below) or `explore` (state EXPLORE: anything goes, nothing is versioned there; a
  working cycle adopts what it found). One cycle starts another with `because`, never as its `in`.

```
cstate(n):                                                      (kernel.cstate; the first match wins)
  an outcome close / abandon on n, or on any goal above it  → CLOSED
  an outcome earlystop                                      → EARLYSTOPPED
  n is a goal                                               → GOAL
  the last of park / resume is park                         → PARKED
  n is explore                                              → EXPLORE
  no plan since the last iterate                            → FRAME
  an arm of the plan not measured                           → WORK
  a conclusion (a finding of kind conclusion) newer than the plan and every measurement → ACT
  else                                                      → JUDGE
```
- **Arms** (`kernel.arm_measure`): a want (`control.want`, wanted until a run `fills` it) or an existing node. Nothing is measured under
  a plan no person confirmed, and its eval does not run there: a person's approve (`validated`) runs it on every arm already filled.
  A running job → `running`; no fill → `failed` (its last job failed) or `wanted`; with the plan's eval, a fill
  is measured by that eval's decision on it (or on a run of it); otherwise by the latest validation on it in the plan's task.
- A working cycle makes only what its plan wants (`control.plan_wants`: a dataset needs a dataset / evalset arm, a train a model arm).
- **Acts** (`control.act_allowed`): close (ACT, EXPLORE), iterate / spawn (ACT), park / resume, abandon, earlystop. Closing or earlystopping a
  working cycle is a person's, or a granted agent's.

## 8. The plug-in API (`Package`, kernel.py)
A tool ships `cards`, `impls`, `rules`, `finish` handlers, `listeners`, and optionally `ack_scope`, `resolver`, `policy_runner`.
- **Lint at load:** no errors, no gaps; valid `open_in` / `on_fail`; `fills` cites `control.fills`; the DAG respected; `when:` and
  subjects in the grammars; every check a card names is implemented (a card no tool implements is refused, never faked).
- **Impls:** `impl(kernel, card, ctx, refs) -> outputs`. `ctx` = every input resolved plus `_event`, `_stamp`, `_via`, `_emit`; `refs` =
  the ref inputs (they become the outputs' links). Every `ref_out` MIN output must be a node this call made, of its kind.
  `kernel.make(kind, ctx, refs, **payload)` creates a node (links = event + refs + `_links` from `impl_roles` only). Impls are stateless and
  never write the database directly; heavy compute is an exec job.
- **Checks:** `check(kernel, subject, scope) -> (verdict, detail)`; `scope` = ctx + outputs + `_main` + `_req`.
- **Finish handlers:** `finish(kernel, ctx, caller_event)` when a job lands (`exec.job.sync` reads the job folder; `exec.job.finish` records).
- **Listeners:** `listen(kernel, event, outputs)` after a commit (§5 step 11).

## 9. Invariants
1. Every node traces back to a root event; there are no orphans.
2. Every link points at an older node.
3. Journal = stored nodes: nothing uncommitted after a call, nothing ever deleted.
4. A refusal record links only `in`; a refused call writes nothing else (asserted at every refusal the replays make).
5. No node uses another task's intent (`control.task_boundary`): pin its outputs or cite its findings instead.

## 10. The conformance suite (`scripts/conformance.sh`)
| artifact | what it proves |
|---|---|
| `bitt lint` | the cards: grammars, the DAG, every named check implemented |
| `tests/` (pytest, memory + Postgres) | each rule on both backends; `tests/test_rule_pins.py` = rules the replays do not reach |
| `tests/test_units.py` | every run counts per unit (D15, `d15.md`): a stored row shared by units, reads along a unit's own chain, samples and rungs per unit, no default aggregate, a win reads one row, a train's report rows |
| `conformance/replay_vk.py`, `replay_gw.py` | two stories told as kernel calls, an assert per rule they show, both backends |
| `conformance/mutate.py` | every check switched off (`BITT_MUTATE_OFF`) and every source patch (`SRC`) must make an assert or a test fail; a crash proves nothing |
