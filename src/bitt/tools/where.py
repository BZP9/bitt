"""Where work goes (scenarios.md F11): your current cycle, a local pointer per store (never a node: it is where *you* are, not a
fact about the work), and the line every command prints first so a person or an agent always knows the task, goal and cycle.

  bitt cycle use <cycle>       set it          ·  bitt cycle list [task]   every cycle, its state and goal, the current one marked
  --in <cycle>                 one call elsewhere  ·  --in <task> / <task>#g<n>: the current cycle there, else its only open cycle
The pointer lives in $BITT_CURRENT (default ~/.config/bitt/current.json), keyed by store.
"""
import json
import os
import sys
from pathlib import Path

from .. import names

STORE = "memory"                # set by cli.main: the store this command talks to (the pointer is per store)
SHOWN = set()                   # cycles whose line this command already printed


def _file():
    return Path(os.environ.get("BITT_CURRENT") or Path.home() / ".config" / "bitt" / "current.json")


def _all():
    try:
        return json.loads(_file().read_text())
    except (OSError, ValueError):
        return {}


def is_open(k, cyc):
    return cyc in k.rec.nodes and k.node(cyc)["kind"] == "cycle" and k.cstate(cyc) not in ("CLOSED", "EARLYSTOPPED")


def current(k):
    """Your current cycle in this store, if it is still open."""
    c = _all().get(STORE)
    return c if c and is_open(k, c) else None


def use(cyc):
    d = _all()
    d[STORE] = cyc
    f = _file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(d, indent=1))


def goals(k, task):
    """A task's goals and sub-goals in the order they were opened (`task#g1`, `task#g2`, …)."""
    return [g["id"] for g in k.rec.find("goal") if g["links"].get("in") and k.task_of(g["id"]) == task]


def cycles(k, task):
    return [c["id"] for c in k.rec.find("cycle") if k.task_of(c["id"]) == task]


def ref(k, nid):
    """`task#N` for a cycle, `task#gN` for a goal, the task's name for a task."""
    t = k.task_of(nid)
    tn = names.task_name(k, t) or t[:12]
    if nid == t:
        return tn
    if k.node(nid)["kind"] == "cycle":
        return f"{tn}#{cycles(k, t).index(nid) + 1}"
    gs = goals(k, t)
    return f"{tn}#g{gs.index(nid) + 1}" if nid in gs else nid[:12]


def path(k, nid):
    """task / goal / sub-goal … for a node under a task: its containers, outermost first."""
    out, cur = [], k.node(nid)["links"].get("in")
    while cur:
        n = k.node(cur)
        out.append(names.task_name(k, cur) if not n["links"].get("in") else f"{ref(k, cur)} {n['payload'].get('problem', '')[:40]!r}")
        cur = n["links"].get("in")
    return " / ".join(reversed(out))


def line(k, cyc):
    n = k.node(cyc)
    mark = " (current)" if current(k) == cyc else ""
    return f"→ {path(k, cyc)} · {ref(k, cyc)}{mark} {n['payload'].get('question', '')[:50]!r} [{n['payload']['level']}, {k.cstate(cyc)}]"


def show(k, cyc):
    """Print where this command's work goes, once per command (stderr, so a command's own output stays parseable)."""
    if cyc not in SHOWN:
        SHOWN.add(cyc)
        print(line(k, cyc), file=sys.stderr)


def listing(k, cs):
    return "; ".join(f"{ref(k, c)} {k.node(c)['payload'].get('question', '')[:40]!r} [{k.cstate(c)}]" for c in cs)


def pick(k, container, what):
    """The cycle work under `container` (a task or a goal) goes to: the current cycle if it is under it, else its only open cycle;
    several open and none current → refused, listing them."""
    cur = current(k)
    under = lambda c: container in k.ancestors(c) or k.node(c)["links"].get("in") == container  # noqa: E731
    if cur and under(cur):
        return cur
    open_ = [c for c in cycles(k, k.task_of(container)) if is_open(k, c) and under(c)]
    if len(open_) == 1:
        return open_[0]
    tn = ref(k, container)
    if not open_:
        raise SystemExit(f"bitt: {what}: {tn} has no open cycle. next: bitt cycle new {tn} \"<question>\"")
    raise SystemExit(f"bitt: {what}: {tn} has {len(open_)} open cycles and none is your current one: {listing(k, open_)}. next: "
                     f"bitt cycle use <one> (then every command works there), or --in <one> for this call")
