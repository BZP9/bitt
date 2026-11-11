"""What the panel draws (docs/v2/panel.md), read from a store (owner 11-04): `model(k)` → {seq, tasks: [{name, needs, cycles, shelf, acts, whole, …}]}.
Read only. The sentence helpers (name, say, needs_you, step_lines, …) are the old viz's, kept as they were: they read the record the
way the owner already checked; the look is bitt.panel.view's.
"""
import datetime
import json

from .. import names
from ..tools import recipe as recipes
from ..tools.run import status_of
from ..util import as_list
from ..walk import Walk


def inputs_of(k, nid):
    """A run's inputs (`on`), through the walker (walk.md: the one way to walk the record)."""
    return Walk(k).links(nid, "on")


def members(k, sh):
    """[(row, split)] of a set, through the walker."""
    return [(m, sp) for _, m, sp in Walk(k).set_rows(sh)]

ACTS = ("goal", "cycle", "outcome", "plan", "want", "run", "dataset", "evalset", "decision", "finding", "validation", "tag",
        "refusal", "artifact")
PERSON_CHECKS = ("control.approval", "control.can_approve", "control.human_actor", "control.act_allowed", "control.has_authority")
DONE = ("CLOSED", "EARLYSTOPPED")


def when(n):
    return datetime.datetime.fromtimestamp(n["stamp"]["at"] / 1e9)


def name(k, nid, task):
    """A node's short handle."""
    from bitt.tools import recipe as recipes
    from bitt.tools.where import ref
    n = k.node(nid)
    kind = n["kind"]
    if kind == "recipe":
        return recipes.label(k, nid, task)
    if kind == "run":
        return f"{n['payload'].get('kind')} {recipes.label(k, n['links']['recipe'], task)}"
    if kind in ("cycle", "goal"):
        return ref(k, nid)
    if kind in ("module", "artifact"):
        return names.vlabel(k, nid, task)
    if kind == "decision":
        p = n["payload"]
        where = f" in {ref(k, n['links']['in'])}" if n["links"].get("in") in k.rec.nodes and k.node(n["links"]["in"])["kind"] == "cycle" else ""
        return (f"{'won' if p.get('won') else 'lost'} {p['rule']}" if "rule" in p else p.get("text", "")[:40]) + where
    if names.label(k, nid):
        return names.ref_of(k, nid, task)
    return f"{kind} {nid[:8]}"


def who(n):
    """The actor as a person reads it: a plan's eval acts as `pipeline:<plan>`."""
    a = n["stamp"].get("actor") or ""
    return "the plan's eval" if a.startswith("pipeline:") else a


def plural(n, word, many=None):
    return f"{n} {word if n == 1 else many or word + 's'}"


def run_result(k, nid):
    e = k.rec.get_row("bitt.run_end", (nid,))
    if k.node(nid)["payload"].get("kind") == "pipeline" and e:
        return f"{len(as_list(k.node(nid)['links'].get('steps')))} steps, {e['status']}"
    if not e:
        return "running" if k.node(nid)["payload"].get("kind") == "train" else "open"
    earlier = sum(c for _, c in reused_from(k, nid))           # rows earlier runs had made
    repeats = e["reused"] - earlier                             # equal values within this run: stored once, counted per unit
    out = (f"{e['made']} made" + (f", {earlier} reused from earlier runs" if earlier else "")
           + (f", {plural(repeats, 'repeat')} of equal values" if repeats else "") + (f", {e['failed']} failed" if e["failed"] else ""))
    return out + (" (FAILED)" if e["status"] == "failed" else "")


def reused_from(k, nid):
    """[(run, how many of this run's entries it had made)]: where the rows a run reused came from (earlier runs of the same work)."""
    e = k.rec.get_row("bitt.run_end", (nid,))
    if not e or not e["out_set"] or not e["reused"]:
        return []
    t = k.rec.get_row("bitt.set", (e["out_set"],))["tbl"]
    by = {}
    for m, _ in members(k, e["out_set"]):
        maker = k.rec.get_row(t, (m,))["bitt_run_hash"]
        if maker != nid:
            by[maker] = by.get(maker, 0) + 1
    return sorted(by.items(), key=lambda x: k.node(x[0])["seq"])


def ladder_key(k, n):
    """The runs of one step on one input in one cycle are one ladder (its rungs); a smoke run is a ladder of its own. The step is the recipe's
    work (its spec), not its record: `bitt recipe` again before each rung makes another record of the same recipe."""
    rc = n["links"].get("recipe")
    ons = tuple(ladder_key(k, k.node(x)) if k.node(x)["kind"] == "run" and k.node(x)["payload"].get("kind") != "pipeline" else x
                for x in inputs_of(k, n["id"]))           # an input that is another rung of one ladder is the same input
    return (k.node(rc)["spec_h"] if rc else None, ons, bool(n["payload"].get("smoke")), n["links"].get("in"))


def step_key(k, n):
    """One step in the graph and the cycle card: the same recipe work on the same inputs in the same cycle. A smoke run and the rungs
    of its step are one step (the smoke run is their first layer), so the graph draws one stacked box, not one per run."""
    key = ladder_key(k, n)
    return (key[0], key[1], key[3])


def source_of(k, nid, r, task):
    """Where reused rows came from, in words: an earlier rung of this ladder, or another step (what it ran on, and when)."""
    n = k.node(r)
    if ladder_key(k, n) == ladder_key(k, k.node(nid)):
        rung, of = n["payload"].get("rung"), n["payload"].get("of")
        return f"rung {rung} ({when(n):%H:%M})" if rung and of and rung < of else f"this step's earlier full run ({when(n):%H:%M})"
    ons = ", ".join(name(k, x, task) for x in inputs_of(k, n["id"]))
    return f"{name(k, r, task)} on {ons} ({when(n):%H:%M})"


def reuse_line(k, nid, task):
    got = reused_from(k, nid)
    return ("reused " + "; ".join(f"{c} from {source_of(k, nid, r, task)}" for r, c in got)) if got else ""


def short_reason(text, n=140):
    """A refusal's reason without the card noise: what was wrong, and its next step."""
    t = str(text).replace("Refused: ", "").replace("Failed: ", "")
    why, _, nxt = t.partition(". next: ")
    if "→ fail (" in why:
        why = why.split("→ fail (", 1)[1].rstrip(")")
    return why[:n], nxt[:n]


def splits(ms):
    c = {}
    for _, sp in ms:
        c[sp] = c.get(sp, 0) + 1
    return "" if list(c) == [None] else ": " + ", ".join(f"{sp} {v}" for sp, v in sorted(c.items(), key=str))


def recipe_name(k, rc, task):
    """A recipe with the versions it pinned, so two arms of one prompt read apart: `title:4a51… (title, unversioned 2)`."""
    from bitt.tools import recipe as recipes
    pins = [x for x in (names.vlabel(k, a, task) for a in recipes.artifacts(k, rc).values()) if x]
    return name(k, rc, task) + (f" ({', '.join(pins)})" if pins else "")


def arm_of(k, n, task):
    """What a decision judged: the recipe of each run it measured, with its versions."""
    return ", ".join(recipe_name(k, k.node(r)["links"]["recipe"], task) for r in as_list(n["links"].get("subject"))
                     if k.node(r)["kind"] == "run" and k.node(r)["links"].get("recipe"))


def say(k, n, task):
    """One act as a sentence (without its actor)."""
    p, kind, nid = n["payload"], n["kind"], n["id"]
    if kind == "run":
        ons = ", ".join(name(k, x, task) for x in inputs_of(k, n["id"]))
        return f"ran {name(k, nid, task)} on {ons or 'its input'}{' (smoke run)' if p.get('smoke') else ''}: {run_result(k, nid)}"
    if kind == "decision":
        read = ", ".join(f"{c} {v}" for c, v in (p.get("row") or {}).items())
        ev = name(k, n["links"]["eval"], task) if n["links"].get("eval") else ""
        arm = arm_of(k, n, task)
        return f"decided with {ev}{' for ' + arm if arm else ''}: {'WON' if p['won'] else 'LOST'} ({p['rule']}; {read})"
    if kind == "finding":
        return ("concluded: " if p.get("finding_kind") == "conclusion" else "noted: ") + p.get("text", "")
    if kind == "validation":
        verb = {"approve": "approved", "reject": "rejected", "pass": "passed", "fail": "failed"}.get(p.get("verdict"), p.get("verdict"))
        return f"{verb} {name(k, n['links']['subject'], task)}"
    if kind == "tag":
        what = {"version": f"version {p.get('value')} ({p.get('bump')})", "alias": f"alias @{p.get('value')}",
                "trust": f"trust {p.get('value')}", "deprecated": f"deprecated: {p.get('value')}"}.get(p["tag"], p["tag"])
        return f"tagged {name(k, n['links']['target'], task).split('@')[0]}: {what}"
    if kind == "outcome":
        return f"{p.get('outcome')} {name(k, n['links']['in'], task)}" + (f": {p['reason']}" if p.get("reason") else "")
    if kind == "plan":
        judge = name(k, n["links"]["pipeline"], task) if n["links"].get("pipeline") else (p.get("judged_by") or "a person")
        return (f"planned {plural(len(as_list(n['links'].get('arms'))), 'arm')}, judged by {judge}"
                + ("" if k.plan_confirmed(n) else " (a proposal: waiting for a person)"))
    if kind == "want":
        return f"wants a {p.get('want_kind')}" + (f" named {p['name']}" if p.get("name") else "")
    if kind == "refusal":
        return f"was refused ({p['card']}): {short_reason(p['reason'])[0]}"
    if kind == "cycle":
        return f"opened {name(k, nid, task)} ({p.get('level')}): {p.get('question', '')}"
    if kind == "goal":
        return f"opened the goal: {p.get('problem', '')}" if n["links"].get("in") else f"opened the task: {p.get('problem', '')}"
    if kind in ("dataset", "evalset"):
        ms = members(k, p["set"])
        return f"made the {kind} {name(k, nid, task)} ({len(ms)} rows{splits(ms)})"
    if kind == "artifact":
        return f"a model landed: {name(k, nid, task)} (from {name(k, n['links']['run'], task)})"
    return kind


def smoke_folds(k, acts):
    """{run id: its smoke run}: each run takes the smoke run right before it on its own step (same recipe work, inputs and cycle),
    so the rail shows one stacked line, as the ladder stacks its rungs. A smoke run is a train's smoke run or a row ladder's first
    rung (1 row of more). A smoke run with no run after it (it failed, or the rest is still to come) keeps its own line."""
    runs = sorted((n for n in acts if n["kind"] == "run"), key=lambda n: n["seq"])
    key = {n["id"]: (lambda x: (x[0], x[1], x[3]))(ladder_key(k, n)) for n in runs}
    out, last_smoke = {}, {}
    for n in runs:
        p = n["payload"]
        if p.get("smoke") or (p.get("rung") == 1 and (p.get("of") or 0) > 1):
            last_smoke[key[n["id"]]] = n
        elif (s := last_smoke.pop(key[n["id"]], None)) is not None:
            out[n["id"]] = s
    return out


def acts(k, task):
    """Every act in the task, newest first."""
    return sorted((n for n in k.rec.nodes.values() if n["kind"] in ACTS and (n["id"] == task or k.task_of(n["id"]) == task)
                   and not (n["kind"] == "artifact" and not n["links"].get("run"))), key=lambda n: -n["seq"])


def needs_you(k, task, all_acts):
    """[(kind, node, what, how)]: what a person must do, what is broken, what is still going."""
    from bitt.tools.run import status_of
    items = []
    for c in (n for n in all_acts if n["kind"] == "cycle" and k.cstate(n["id"]) not in DONE):
        plan = k.latest_plan(c["id"])
        if plan and not k.plan_confirmed(plan):
            items.append(("you", plan["id"], f"approve or reject the plan {plan['stamp']['actor']} proposed in {name(k, c['id'], task)}",
                          f"bitt validate {plan['id'][:12]} approve"))
        if k.cstate(c["id"]) == "ACT" and c["payload"].get("level") == "working":
            items.append(("you", c["id"], f"{name(k, c['id'], task)} has its verdict: close it, iterate or spawn",
                          f"bitt cycle close {name(k, c['id'], task)}"))
    def about(args):                                            # what an act was on, as an id when it resolves
        x = args.get("target") or args.get("subject") or args.get("recipe") or args.get("in")
        try:
            return k.resolve(x, task)[0] if isinstance(x, str) else json.dumps(x, default=str)
        except Exception:                                       # noqa: BLE001 — a ref that no longer resolves stays as typed
            return x
    done = {}                                                   # (card, what) → the seq of its latest act that went through
    for e in k.rec.find("event"):
        if e["payload"]["card"] in ("tag.make", "control.validate", "control.act", "control.goal.open", "run.go", "recipe.make"):
            key = (e["payload"]["card"], about({**e["payload"]["args"], **e["links"]}))
            done[key] = max(done.get(key, -1), e["seq"])
    seen = set()
    for r in (n for n in all_acts if n["kind"] == "refusal"):           # newest first: the latest refusal of each act on each thing
        p = r["payload"]
        key = (p["card"], about(p["args"]))
        fresh = key not in seen and done.get(key, -1) < r["seq"]          # an act that went through later settles it
        seen.add(key)
        if fresh and r["stamp"]["actor"].startswith("agent") and any(c in p["reason"] for c in PERSON_CHECKS):
            why, nxt = short_reason(p["reason"])
            items.append(("you", r["id"], f"{r['stamp']['actor']} needed a person for {p['card']}: {why}", nxt))
    latest = {}
    for n in reversed(all_acts):
        if n["kind"] == "run":
            latest[n["links"]["recipe"]] = n
    for r in latest.values():
        st = status_of(k.rec, r["id"])
        if st == "failed":
            errs = k.rec.table_rows("bitt.run_error", bitt_run_hash=r["id"])
            items.append(("problem", r["id"], f"{name(k, r['id'], task)} failed" + (f": {errs[0]['error'][:120]}" if errs else ""),
                          "fix it, then run the same recipe again (rows already made are kept)"))
        elif st == "open" and r["payload"].get("person"):
            items.append(("waiting", r["id"], f"{name(k, r['id'], task)}: {len(r['payload']['asks'])} rows wait for a person's answers",
                          f"bitt run answer {r['id'][:12]} --file answers.jsonl, then bitt run close {r['id'][:12]}"))
        elif st == "open" and r["payload"].get("kind") == "train":
            items.append(("waiting", r["id"], f"{name(k, r['id'], task)} is training ({'smoke run' if r['payload'].get('smoke') else 'full'})",
                          "bitt run sync lands it when it is done"))
    return items


def arm_label(k, a, task):
    f = k.fill_of(a) or a
    return recipe_name(k, f, task) if k.node(f)["kind"] == "recipe" else name(k, f, task)


def arm_work(k, a):
    """The work an arm stands for (its recipe's spec), so every decision on a run of it is found, on any data."""
    f = k.node(k.fill_of(a) or a)
    rc = f["id"] if f["kind"] == "recipe" else f["links"].get("recipe") if f["kind"] == "run" else None
    return k.node(rc)["spec_h"] if rc else None


def step_lines(k, nid, task):
    """A step box: what ran (kind, recipe), how (module, artifacts, params), and what came of it."""
    from bitt.tools import recipe as recipes
    n = k.node(nid)
    r = k.node(n["links"]["recipe"])
    how = [names.vlabel(k, r["links"]["module"], task)] + [f"{role} {names.vlabel(k, a, task)}" for role, a in recipes.artifacts(k, r["id"]).items()]
    params = {p: v for p, v in (r["payload"].get("params") or {}).items() if v not in (None, "") and p not in ("url", "key_file", "timeout")}
    how += [", ".join(f"{p}={v}" for p, v in params.items())] if params else []
    if n["payload"].get("kind") == "pipeline":
        how = ["steps: " + " → ".join(name(k, s, task).split(" ", 1)[-1].split(":")[0] for s in as_list(n["links"].get("steps")))]
    return [f"{n['payload'].get('kind')} · {recipes.label(k, r['id'], task)}", " · ".join(how), run_result(k, nid),
            reuse_line(k, nid, task)]


def cols_fed(k, run, role=None):
    """The columns an input fed a step, from its recipe: `on` → the plain columns it binds; a --read role → its `role.col` ones."""
    cols = (k.node(k.node(run)["links"]["recipe"])["payload"].get("cols") or {}).values()
    cols = [c for c in cols if isinstance(c, str)]
    return [c for c in cols if "." not in c] if role is None else [c.split(".", 1)[1] for c in cols if c.startswith(role + ".")]


def few(xs, n=2):
    return ", ".join(xs[:n]) + (f" +{len(xs) - n}" if len(xs) > n else "")


def data_lines(k, nid, task):
    n = k.node(nid)
    p = n["payload"]
    if n["kind"] == "decision":
        return ["decision", f"{'WON' if p.get('won') else 'LOST'}: {p['rule']}",
                ", ".join(f"{c} {v}" for c, v in (p.get("row") or {}).items())]
    if n["kind"] == "artifact":
        return ["model", name(k, nid, task), p.get("artifact_kind", "")]
    ms = members(k, p["set"])
    head = n["kind"]
    if (t := k.task_of(nid)) and t != task:                     # another task's (#4): whose it is, and whether it is a version
        owner = k.node(t)["stamp"]["actor"]
        head += f" · from task {names.task_name(k, t)} ({owner}){'' if names.version_of(k, nid) else ', unversioned'}"
    return [head, name(k, nid, task), f"{len(ms)} rows{splits(ms)}"]


acts_of = acts


def model(k):
    """{seq, tasks: [...]}: everything the three levels draw, read from one kernel's record (read only)."""
    DATA = ("raw", "dataset", "evalset", "selection")


    def cycle_of(nid, cyc_n):
        seen = set()
        while nid and nid not in seen and nid in k.rec.nodes:
            seen.add(nid)
            if nid in cyc_n:
                return cyc_n[nid]
            n = k.node(nid)
            nid = n["links"].get("in") or next((x for x in as_list(n["links"].get("subject")) + as_list(n["links"].get("target")) if x), None)
        return None


    def state(c):
        st = k.cstate(c)
        return "CLOSED" if st in DONE else st


    def ladders(runs, task):
        """A cycle's runs as ladders: one per step (its recipe's work, on one input), the smoke run first, then each rung."""
        lad = {}
        for r in runs:
            key = ladder_key(k, r)
            lad.setdefault((key[0], key[1], key[3]), []).append(r)
        out = []
        for rs in lad.values():
            rungs, of = [], None
            for r in rs:
                e = k.rec.get_row("bitt.run_end", (r["id"],)) or {}
                made, failed = (e.get("made") or 0) + (e.get("reused") or 0), e.get("failed") or 0
                st = status_of(k.rec, r["id"])
                p = r["payload"]
                of = p.get("of") or of
                rungs.append({"rung": "smoke" if p.get("smoke") else p.get("rung") or "full", "n": max(made + failed, 1), "made": made,
                              "failed": failed, "status": "running" if st == "open" else st,
                              "skipped_smoke": p.get("skip_smoke") == "yes"})           # SOP Q3: which run went without its smoke run
            kind, _, rest = name(k, rs[-1]["id"], task).partition(" ")
            ons = ", ".join(name(k, x, task) for x in inputs_of(k, rs[-1]["id"]))
            out.append({"label": rest.split(":")[0], "kind": kind, "on": ons, "of": of, "rungs": rungs, "nid": rs[-1]["id"]})
        return out


    def shape(n):
        if n["kind"] == "run":
            return "step"
        if n["kind"] == "decision":
            return "decision"
        if n["kind"] == "artifact":
            return "model"
        return "raw" if n["kind"] == "raw" else "dataset"


    def sub(n, task):
        if n["kind"] == "run":
            return run_result(k, n["id"])[:28]
        if n["kind"] == "decision":
            return "won" if n["payload"].get("won") else "lost"
        v = names.version_of(k, n["id"])
        if n["kind"] in DATA:
            rows = len(members(k, n["payload"]["set"])) if n["payload"].get("set") else 0
            return f"{v or 'draft'} · {rows}" if rows else (v or "")
        return v or ""



    SRC, CONS, CITED = {}, {}, set()                                    # what fed a node, what it fed, cited as a note's evidence
    for n in k.rec.nodes.values():
        srcs = []
        if n["kind"] == "run":
            srcs = inputs_of(k, n["id"]) + list((n["payload"].get("read") or {}).values())
            if n["links"].get("recipe"):
                srcs += [a for a in recipes.artifacts(k, n["links"]["recipe"]).values() if a]   # few_shots, a model: through the recipe
        elif n["kind"] in (*DATA, "artifact"):
            srcs = as_list(n["links"].get("run"))
        elif n["kind"] == "decision":
            srcs = [r for r in as_list(n["links"].get("subject")) if r in k.rec.nodes and k.node(r)["kind"] == "run"]
        srcs = [x for x in dict.fromkeys(srcs) if x in k.rec.nodes]
        SRC[n["id"]] = srcs
        for x in srcs:
            CONS.setdefault(x, []).append(n["id"])
        if n["kind"] in ("finding", "tag"):
            CITED |= {x for r in ("evidence", "agreement", "because") for x in as_list(n["links"].get(r))}
    CYC = {}                                                            # cycle id → (task name, its number in the task)
    for g in k.rec.find("goal"):
        if not g["links"].get("in"):
            cs = sorted((c for c in k.rec.find("cycle") if k.task_of(c["id"]) == g["id"]), key=lambda c: c["seq"])
            CYC.update({c["id"]: (names.task_name(k, g["id"]), i + 1) for i, c in enumerate(cs)})


    def home_of(x):
        """The cycle a node was made in, else its task (a goal with no parent), else None."""
        seen = set()
        while x and x not in seen and x in k.rec.nodes:
            seen.add(x)
            n = k.node(x)
            if x in CYC or (n["kind"] == "goal" and not n["links"].get("in")):
                return x
            x = n["links"].get("in")
        return None


    def ext_box(home, task):
        """A box standing for another cycle (or task): where an arrow goes to or comes from."""
        if home in CYC:
            tn, num = CYC[home]
            q = k.node(home)["payload"].get("question", "")
            return {"id": "ext" + home[:9], "shape": "ext", "label": f"{'' if tn == names.task_name(k, task) else tn}#{num}",
                    "lines": [f"{'' if tn == names.task_name(k, task) else tn}#{num}", q[:34]], "to": [tn, num], "rungs": 0}
        tn = names.task_name(k, home)
        return {"id": "ext" + home[:9], "shape": "ext", "label": tn, "lines": [tn, "task"], "to": [tn, None], "rungs": 0}


    def flow(cid, task, cset=None):
        """What this cycle made (or, `cset`: every cycle of the task and the task itself), left to right: its runs (a ladder as one step),
        what they read, what came of them."""
        cset = cset or {cid}
        mine = [n for n in k.rec.nodes.values() if n["links"].get("in") in cset and n["kind"] in ("run", "decision", "artifact", *DATA)]
        rep, lad = {}, {}
        for n in sorted(mine, key=lambda n: n["seq"]):
            if n["kind"] == "run":
                lad.setdefault(step_key(k, n), []).append(n["id"])
        for ids in lad.values():
            for x in ids:
                rep[x] = ids[-1]
        nodes, edges = {}, set()

        def add(x):
            x = rep.get(x, x)
            nodes.setdefault(x, k.node(x))
            return x
        fed = {}
        for n in mine:
            x = add(n["id"])
            if n["kind"] == "run":
                for i in inputs_of(k, n["id"]):
                    if i in k.rec.nodes:
                        edges.add((add(i), x))
                        cs = few(cols_fed(k, n["id"]))                        # J4: with --read inputs too, each arrow names its role
                        fed[(rep.get(i, i), x)] = (f"on: {cs}" if cs else "on") if n["payload"].get("read") else cs
                for role, i in (n["payload"].get("read") or {}).items():
                    if i in k.rec.nodes:
                        edges.add((add(i), x))
                        fed[(rep.get(i, i), x)] = f"{role}: {few(cols_fed(k, n['id'], role))}"
                continue
            for role in ("run", "subject"):
                for r in as_list(n["links"].get(role)):
                    if r in k.rec.nodes and k.node(r)["kind"] == "run":
                        edges.add((add(r), x))
        for n in mine:                                                  # an artifact a recipe runs with (few_shots, a model)
            if n["kind"] == "run":
                for a in SRC[n["id"]]:
                    if k.node(a)["kind"] == "artifact":
                        edges.add((add(a), add(n["id"])))
        for n in mine:                                                  # a set a run made: from the run that made it
            if n["kind"] in DATA:
                for r in as_list(n["links"].get("run")):
                    if r in k.rec.nodes:
                        edges.add((add(r), add(n["id"])))
        edges = {(a, b) for a, b in edges if a != b}
        ext = {}
        task_home = home_of(task)
        made_here = {rep.get(m["id"], m["id"]) for m in mine}
        for x in list(nodes):
            for c in (CONS.get(x, []) if x in made_here else []):       # what this cycle made, used in another cycle or task
                h = home_of(c)
                if h and h not in cset and h != task_home:
                    ext.setdefault(h, ext_box(h, task))
                    edges.add((x, ext[h]["id"]))
            h = home_of(x)                                              # made in another cycle or task, read here
            if h and h not in cset and h != task_home and x not in made_here:
                ext.setdefault(h, ext_box(h, task))
                edges.add((ext[h]["id"], x))
        depth = {x: 0 for x in [*nodes, *(b["id"] for b in ext.values())]}
        for _ in range(len(nodes)):
            for a, b in edges:
                depth[b] = max(depth[b], depth[a] + 1)
        row = {}
        out = []
        for x in sorted(nodes, key=lambda x: (depth[x], nodes[x]["seq"])):
            d = depth[x]
            row[d] = row.get(d, -1) + 1
            out.append({"id": x[:12], "nid": x, "label": name(k, x, task), "sub": sub(nodes[x], task), "shape": shape(nodes[x]), "col": d, "row": row[d],
                        "lines": lines(x, task), "rungs": len(lad.get(step_key(k, nodes[x]), [])) if nodes[x]["kind"] == "run" else 0,
                        "cited": x in CITED, **({"cyc": CYC[home_of(x)][1]} if len(cset) > 1 and home_of(x) in CYC else {})})
        for b in ext.values():
            out.append({**b, "col": depth[b["id"]], "row": 0})
        short = lambda x: x if x.startswith("ext") else x[:12]  # noqa: E731
        return {"nodes": out, "edges": [[short(a), short(b), fed.get((a, b), "")] for a, b in sorted(edges)]}


    def lines(x, task):
        """A box's text, as the old viz wrote it: a step = what ran, with what, what came of it; data = kind, name, rows."""
        try:
            ls = step_lines(k, x, task) if k.node(x)["kind"] == "run" else data_lines(k, x, task)
        except Exception:                                               # noqa: BLE001 — a raw import has no set rows here
            ls = [k.node(x)["kind"], name(k, x, task)]
        return [t for t in ls if t]


    def plan_of(cid, task):
        p = k.latest_plan(cid)
        if not p:
            return None
        arms = as_list(p["links"].get("arms"))
        work = {a: arm_work(k, a) for a in arms}
        got, cols = {a: {} for a in arms}, []
        for d in sorted(k.rec.find("decision"), key=lambda n: n["seq"]):
            if k.task_of(d["id"]) != task or "won" not in d["payload"]:
                continue
            for r in as_list(d["links"].get("subject")):
                if k.node(r)["kind"] != "run" or not k.node(r)["links"].get("recipe"):
                    continue
                on = inputs_of(k, r)
                col = name(k, on[0], task) if on else "?"
                row = d["payload"].get("row") or {}
                rate = next((v for v in row.values() if isinstance(v, (int, float)) and not isinstance(v, bool)), None)
                rate = row.get("rate", rate)
                if rate is None:
                    continue
                for a in arms:
                    if work[a] and k.node(k.node(r)["links"]["recipe"])["spec_h"] == work[a]:
                        got[a][col] = {"rate": float(rate), "lo": float(row.get("lo", rate)), "hi": float(row.get("hi", rate)),
                                       "n": row.get("n", ""), "won": bool(d["payload"]["won"])}
                        cols += [col] if col not in cols else []
        judge = name(k, p["links"]["pipeline"], task) if p["links"].get("pipeline") else (p["payload"].get("judged_by") or "person")
        return p, {"judge": judge, "cols": cols,
                   "arms": [{"label": arm_label(k, a, task)[:40], "state": k.arm_state(a, p), "cells": got[a]} for a in arms]}


    def task_of(tid, num):
        task = tid
        acts = acts_of(k, task)
        cycles = sorted((n for n in acts if n["kind"] == "cycle"), key=lambda n: n["seq"])
        cyc_n = {c["id"]: i + 1 for i, c in enumerate(cycles)}
        out_c = []
        for c in cycles:
            cid = c["id"]
            runs = sorted((n for n in acts if n["kind"] == "run" and n["links"].get("in") == cid), key=lambda n: n["seq"])
            d = {"n": cyc_n[cid], "question": c["payload"].get("question", ""), "state": state(cid), "ladder": ladders(runs, task),
                 "seq": max([c["seq"], *(n["seq"] for n in acts if n["links"].get("in") == cid)]),
                 "flow": flow(cid, task)}
            pp = plan_of(cid, task)
            if pp:
                p, d["plan"] = pp
                if not k.plan_confirmed(p) and d["state"] != "CLOSED":
                    d["planWaiting"] = {"actor": p["stamp"]["actor"], "cmd": f"bitt validate {p['id'][:12]} approve"}
            if any(status_of(k.rec, r["id"]) == "failed" for r in runs):
                d["failed"] = sum(status_of(k.rec, r["id"]) == "failed" for r in runs)
            tr = [r for r in runs if r["payload"].get("kind") == "train" and status_of(k.rec, r["id"]) == "open"]
            if tr:
                d["train"] = {"p": 0.5, "label": f"{name(k, tr[-1]['id'], task)} training"}
            concl = [f for f in k.kids(cid, role="in", kind="finding") if f["payload"].get("finding_kind") == "conclusion"]
            if concl:
                d["verdict"] = concl[-1]["payload"]["text"][:80]
            out_c.append(d)
        first = out_c[0]["n"] if out_c else 1
        needs = [{"kind": kind, "text": what[:160], "cmd": how[:120], "cycle": cycle_of(nid, cyc_n) or first}
                 for kind, nid, what, how in needs_you(k, task, acts)]
        shelf, lines = [], {}
        for n in sorted((n for n in acts if n["kind"] in ("dataset", "evalset", "artifact")), key=lambda n: n["seq"]):
            ln = names.label(k, n["id"])
            if not ln:
                continue
            it = lines.setdefault((n["kind"], ln), {"name": ln, "kind": "model" if n["kind"] == "artifact" else n["kind"], "rows": 0,
                                                   "approved": False, "versions": []})
            if n["payload"].get("set"):
                it["rows"] = len(members(k, n["payload"]["set"]))
            it["approved"] |= any(v["payload"].get("verdict") == "approve" for v in k.rec.find("validation") if n["id"] in as_list(v["links"].get("subject")))
            it["nid"] = n["id"]                                          # the newest version (sorted by seq)
            v = names.version_of(k, n["id"])
            if v:
                al = [t["payload"]["value"] for t in names.tags(k, n["id"], "alias")]
                it["versions"].append({"v": v, **({"alias": al[-1]} if al else {})})
        shelf = list(lines.values())
        folded = smoke_folds(k, acts)
        hidden = {s["id"] for s in folded.values()}
        rail = []
        for n in [n for n in acts if n["id"] not in hidden][:200]:          # newest first; a smoke run folds into the run after it
            w = when(n)
            rail.append({"day": f"{w:%m-%d}", "t": f"{w:%H:%M}", "cycle": cycle_of(n["id"], cyc_n) or "", "actor": who(n), "kind": n["kind"],
                         "text": say(k, n, task)[:200], "seq": n["seq"], "nid": n["id"],
                         **({"after": f"{when(folded[n['id']]):%H:%M} {say(k, folded[n['id']], task)[:160]}"} if n["id"] in folded else {})})
        last = acts[0] if acts else None
        whole = flow(None, task, cset={c["id"] for c in cycles} | {task})
        return {"whole": whole, "name": names.task_name(k, task), "problem": k.node(task)["payload"].get("problem", ""),
                "activity": activity(acts), "changed": False, "seq": max((n["seq"] for n in acts), default=0),
                "last": {"at": last["stamp"]["at"] // 10**9 if last else 0, "actor": who(last) if last else "", "text": say(k, last, task)[:90] if last else ""},
                "needs": needs, "shelf": shelf, "cycles": out_c, "acts": rail}



    def activity(acts, days=14):
        """Acts per day, the last `days` days, oldest first."""
        import time
        today = int(time.time() // 86400)
        out = [0] * days
        for n in acts:
            d = today - n["stamp"]["at"] // 10**9 // 86400
            if 0 <= d < days:
                out[days - 1 - d] += 1
        return out

    tasks = [n["id"] for n in sorted(k.rec.find("goal"), key=lambda n: n["seq"]) if not n["links"].get("in")]
    return {"seq": max((n["seq"] for n in k.rec.nodes.values()), default=0), "tasks": [task_of(t, i) for i, t in enumerate(tasks)]}


# ---------------------------------------------------------------- the inspector (docs/v2/panel.md "Inspect")
def lit(s):
    """A SQL string literal."""
    return "'" + str(s).replace("'", "''") + "'"


def qual(tbl):
    """A table name (`schema.name`) as a quoted SQL identifier."""
    return ".".join('"' + p.replace('"', '""') + '"' for p in tbl.split("."))


def rows_sql(k, sh, limit=100):
    """The rows of a set, in order, with their split: one query over the table and its memberships."""
    s = k.rec.get_row("bitt.set", (sh,))
    if not s:
        return None
    t = s["tbl"]
    return (f"SELECT s.ord, s.split, x.* FROM {qual(t + '__sets')} s JOIN {qual(t)} x USING (bitt_row_hash)\n"
            f" WHERE s.bitt_set_hash = {lit(sh)} ORDER BY s.ord LIMIT {limit};")


def inspect(k, ref):
    """One node as the inspector draws it: its fields and payload, what it links (with the role), what links it (its history, oldest
    first), a run's counts and errors, and the SQL that reads the same in DBeaver. KeyError when no node matches."""
    nid = ref if ref in k.rec.nodes else (k.rec.by_prefix(ref) if len(ref) >= 8 else None)
    if not nid:
        raise KeyError(f"no node {ref}")
    n = k.node(nid)
    task = nid if n["kind"] == "goal" and not n["links"].get("in") else k.task_of(nid)

    def brief(x):
        m = k.node(x)
        try:
            lab = name(k, x, task)
        except Exception:                                           # noqa: BLE001 — a handle that cannot be said keeps its kind
            lab = m["kind"]
        return {"id": x, "kind": m["kind"], "label": lab, "seq": m["seq"], "actor": who(m), "t": f"{when(m):%m-%d %H:%M}"}

    out_ = [{"role": role, **brief(p)} for role, v in n["links"].items() for p in as_list(v) if isinstance(p, str) and p in k.rec.nodes]
    vals = {role: v for role, v in n["links"].items() if not all(isinstance(p, str) and p in k.rec.nodes for p in as_list(v))}
    kids = k.kids(nid)
    hist = [{"role": ",".join(r for r, v in c["links"].items() if nid in as_list(v)), **brief(c["id"])} for c in kids]
    sh = n["payload"].get("set") if isinstance(n["payload"].get("set"), str) else None
    run = None
    if n["kind"] == "run":
        e = k.rec.get_row("bitt.run_end", (nid,)) or {}
        errs = k.rec.table_rows("bitt.run_error", bitt_run_hash=nid)
        run = {"status": status_of(k.rec, nid), "result": run_result(k, nid), "errors": [x["error"][:300] for x in errs[:5]],
               "n_errors": len(errs)}
        sh = e.get("out_set") or sh
    sql = [("the node", f"SELECT * FROM bitt.v_node WHERE id = {lit(nid)};"),
           ("its record", f"SELECT kind, payload, links, stamp FROM bitt.node WHERE id = {lit(nid)};"),
           ("made from (tree)", f"SELECT line FROM bitt.tree({lit(nid)}, 'up');"),
           ("made from it (tree)", f"SELECT line FROM bitt.tree({lit(nid)});"),
           ("history: what links it", "SELECT n.seq, n.kind, l.role, n.stamp->>'actor' AS actor, n.created_at, n.id\n"
                                      f"  FROM bitt.link l JOIN bitt.node n ON n.id = l.child WHERE l.parent = {lit(nid)} ORDER BY n.seq;")]
    if run:
        sql += [("the run", f"SELECT * FROM bitt.v_run WHERE run = {lit(nid)};"),
                ("its errors", f"SELECT * FROM bitt.run_error WHERE bitt_run_hash = {lit(nid)} ORDER BY seq;")]
    if sh and (q := rows_sql(k, sh)):
        sql.append(("its rows", q))
    return {**brief(nid), "card": n["stamp"].get("card") or "", "spec_h": n.get("spec_h") or "",
            "task": names.task_name(k, task) if task else "", "state": n.get("state") or "",
            "payload": json.dumps(n["payload"], indent=1, ensure_ascii=False, default=str), "values": vals,
            "links": out_, "history": hist[:200], "n_history": len(hist), "run": run, "sql": sql}
