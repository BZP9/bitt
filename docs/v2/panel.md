# The panel: the visual guide

The panel is bitt's read-only picture of a store (scenario F15; owner 11-04). This page fixes what each shape, line and colour means,
so a change keeps the language and a new session does not lose it. Start it: `bitt serve` (your store: `--dsn` or `$BITT_DSN`),
then open http://127.0.0.1:8765. Code: `src/bitt/panel/` — `data.py` (what is read, through the walker) → `view.py` (how it is drawn) →
`serve.py` (live); `scripts/viz_serve.py` adds the eval and tour stores, `scripts/viz_evals.py` writes a store's panel as files.
Tests: `tests/test_panel.py`.

## The rule

**Layout first, words last.** Position, spacing, lines, shape and colour carry the meaning; words only confirm or supplement it.
- No legends, no explainer paragraphs, no captions that restate a picture (`tests/test_panel.py` checks the visible text).
- Fine as words: a name, a count, a version, a question, a refusal line verbatim, a command to run.
- One visual sign means one thing. A sign that means two things is a bug in the language (see "Open" below).

## Three levels, one entry

| level | URL (live) | what it shows |
|---|---|---|
| home | `/` (`bitt serve`: your store) · `/s/<store>/` | every task as a lane: its name, its cycle tiles in order, how much needs you, 14 days of activity, its last act |
| task | `/s/<store>/t/<task>` | what needs you (a stack); open cycles as parallel lanes with aligned tracks, closed ones as small tiles below; the **Map** (the whole task's graph, folded); what exists (shelf); what happened (rail) |
| cycle | `/s/<store>/t/<task>/c/<n>` | its question and track; a plan waiting on you (banner); training (bar); arms side by side; runs (stacked cards); **Made** (what it made, folded); what happened |

Live: every page is drawn from the store when it is asked for. An open page asks `/s/<store>/seq` every 3 s; when the store's newest seq
moved, it redraws in place (scroll, open folds and the graph's pan and zoom kept) and pulses what is newer. Nothing is ever rebuilt by
hand. Every store opens in a read-only session (`default_transaction_read_only`, no schema setup); the server answers GET only.

- **The pulse:** what is newer than the last redraw (a row, a lane, a tile) flashes a violet ring three times, then stops. The ring hugs
  the thing's own edge and spreads a fixed 6 px; it never scales, so a full-width row grows as little as a tile. A cycle whose plan
  waits on you keeps breathing (`.nag`) until you act.
- **The last check:** a served page has a small badge in the bottom right corner: a green dot that blinks on each check and "checked
  N s ago". The dot turns red ("store not answering") when the check fails. A static snapshot (`viz_evals.py`) checks nothing, so it
  has no badge.
- An empty store's home still draws one lane ("no task yet"), never a blank page.

**The eval list** (`scripts/viz_serve.py`, `/` and `/stores`): every agent eval on this machine as a lane, drawn like the home. Each
lane's tiles are its reference (round) and then each agent run, oldest to newest, with the passed count inside: green edge = full
marks, red edge = a miss, striped teal = running now, dashed = stopped and never graded, faint = made by an older bitt (cannot be
opened). A tile links to that store's home; its tooltip gives the full grade line. A finished store is read once and cached; a
running one is read on every check. The list redraws itself through `/stores/seq`. Your own store (`--dsn` or `$BITT_DSN`) is the
top lane, at `/s/mine/`.

## Inspect

Any rail line, graph box, run card or shelf item on a served page opens its node in a drawer on the right (scenario F21, owner
11-06); the thing picked gets a violet outline. The drawer: what it is (kind, task, actor, card, time, seq, the full id), a run's
result and its first errors, **links** (what it links, with the role: `on`, `recipe`, `in`, …) and **linked by** (every node that
links it, oldest first: its history), its payload, and **sql**: the queries that read the same in DBeaver, a copy button each
(the node, its record, its tree up and down through `bitt.tree`, what links it, a run's `bitt.v_run` row and errors, a set's rows).
A link in the drawer opens that node in turn (`‹` goes back); Esc or `×` closes it; the URL keeps `#n=<id>`, so a reload reopens
it. A drag of the graph is not a pick. Route: `/s/<store>/n/<id or ≥8-char prefix>`; read only. A static snapshot has no server to
ask, so nothing on it is a pick. Every query the drawer offers is run on Postgres for every node kind (`tests/test_panel.py`).

## The vocabulary

### A cycle (tile, track)

| sign | means |
|---|---|
| a square tile with its number | a cycle; tiles in a lane are in the order the cycles opened |
| filled teal | frame or work: being made and measured |
| filled amber | judge or act: every arm measured, a verdict to write or act on |
| outlined green with a tick | closed |
| dashed teal outline | explore: free, no plan |
| faint outline | parked |
| a ring around the tile (it keeps breathing) | a plan waits on a person |
| a red corner | a run in it failed |
| moving stripes | a train is running in it |
| the track: four stations (frame, work, judge, act), filled up to where it is, a ring on the station it is at | how far the cycle is; a dashed track = explore |

### Home and task

| sign | means |
|---|---|
| a lane's left edge: pink · teal · none | something needs you · cycles are open · nothing open |
| a pink number | acts only a person may do, and problems (failed runs) |
| an amber number | things still going: a train, rows waiting on a person's answers |
| a green tick | nothing open, nothing waiting |
| bars, 14 days | acts per day; the last two days darker |
| needs-you stack, left edge: pink dot · red triangle · amber spinner | a person's act · a problem · still going; the line under it is the command |

### The graph (Made, Map)

Read left to right: a box's column is its longest way from a source; each column is ordered by where its sources sit.

| sign | means |
|---|---|
| square box, thick double edge | a raw import |
| square box | a dataset, evalset or selection (its text: kind, name, rows and sides) |
| rounded box, teal edge | a step (a run): what ran, with which module, prompt and params, what came of it |
| boxes stacked behind a step | the same step run more than once (smoke, rungs): one box |
| filled violet box | a model or another artifact (few-shot examples, a prompt) |
| violet edge with a diamond | a decision (won / lost) |
| dashed box, a link | another cycle (`#3`) or another task (`gw#1`): an arrow to it = something made here is used there; from it = made there, read here |
| a small dark tile on a box's corner | (Map only) the cycle that made it |
| an amber folded corner | a note or a trust tag cites it as evidence |
| a word on an arrow | the columns that input fed the step; with several inputs, the role first (`on: title`, `chat: …`) |
| a box no arrow leaves | nothing used it (a test product stays: owner 11-04) |

The frame scrolls both ways and drags; `−` `fit` `+` zoom (or ctrl / cmd + wheel). Folded, a graph shows a miniature row of its boxes.

### Arms and runs

| sign | means |
|---|---|
| arms table: a row per arm, a column per data it was judged on | the arms side by side |
| a cell: a dot on a 0–1 line, its interval behind it, green won / red lost, then rate and n | one decision |
| a red left edge on an arm's row | its decisions disagree across data |
| an arm's dot: open · teal ring · green · spinning | not made · made · measured · running |
| a run card: name and made/total, kind and input under it | one step's runs |
| layers behind a card | earlier runs of it (smoke, rungs), up to 4 |
| a red dashed layer behind a card | it ran without its smoke run (`skip_smoke`) |
| the card's foot | the latest run: green made, red failed, striped running; a red border = it failed |

### What happened (rail)

A dot per act, newest first, grouped by day: teal = a run, violet diamond = a decision, green square = a tag, green = a validation or an
outcome, ring = a plan, dark square = a cycle opened, red triangle and red text = a refusal. Bold = a person's act. The small tile before
a line (task page) is the cycle it was in. A smoke run (a train's, or a row ladder's 1-row first rung) folds into the run that came right after it on the same step: one line, its dot
with a layer behind (the smoke run's time and result in the tooltip), as the ladder stacks its rungs. A smoke run with no run after it
yet (or that failed) keeps its own line.

**Stacking, one rule everywhere:** a step is the same recipe work on the same inputs in the same cycle. Its smoke run and its rungs are
one step: the cycle card, the graph box and the rail line all show it once. In the graph, the box is stacked by its runs (a layer per
earlier run); on the rail, a smoke run folds into the run after it. A row a later rung reused says so in its line ("reused … from
rung 1"), so the smoke run's row is never counted twice.

## Open (owner to decide)

- Dashed means two things: an explore cycle (tile) and another cycle or task (graph box). Proposal: give the graph's outside box its own
  shape (a tab or an arrow-ended box) and keep dashed for explore.
- Amber means three things: judge / act (tile), still going (number), cited (corner). Proposal: keep amber for "waiting" (judge / act,
  still going) and give "cited" its own mark.
- Refusals dominate a busy rail (the vk replay); repeated identical runs make long run grids. Fold or thin them?
