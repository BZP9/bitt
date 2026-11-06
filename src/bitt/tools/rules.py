"""The rules on lineage and results (rebuild.md §3): they read rows and their lineage, never what a module claims, so they hold for
code bitt does not understand. Each returns (verdict, detail).

Every walk goes through the walker (docs/v2/walk.md): a row reaches the rows it was made from (`walk.rows_up`; a whole-set link
stands for every member, so a walk may over-include, never miss); a model saw its train run's input set, train side (`walk.seen`);
the data path (`walk.up(x, via=DATA_PATH)`) follows every input a run walked or read, a join's lookups included.
"""
from .. import names
from ..walk import DATA_PATH, Walk
from . import recipe as recipes
from .module import inner


def units(rows):
    return {r for t, r in rows if t.startswith("raw.")}


def models_of(eng, recipe):
    """The models (artifacts made by a train run) a recipe runs with: in its roles or its wraps'."""
    w = Walk(eng)
    return [a for a in recipes.artifacts(eng, recipe).values()
            if eng.node(a)["payload"].get("artifact_kind") == "model" and w.links(a, "run")]


def seers_of(eng, recipe):
    """Every artifact a recipe runs with that saw data (charter guarantee 8): its models, and the artifacts a run made from rows
    (examples, a rubric: W4). What each saw is `walk.seen`."""
    w = Walk(eng)
    return [a for a in recipes.artifacts(eng, recipe).values() if w.links(a, "run")]


def generate_runs(eng, ref):
    """(producers, judges): the generate runs on the data path to `ref` (itself included). A producer has no generate on its own data
    path (it made the rows from data); a judge has one (it read another generate's outputs)."""
    w = Walk(eng)
    gens = w.up(ref, via=DATA_PATH).runs(kind="generate")
    judges = [g for g in gens if any(x != g for x in w.up(g, via=DATA_PATH).runs(kind="generate"))]
    return [g for g in gens if g not in judges], judges


def norm_text(v):
    """A value as the model reads it, for comparing by content (#3): case and runs of whitespace do not hide a duplicate."""
    return " ".join(str(v).lower().split()) if v is not None else None


def seen_values(eng, run, cols, skip_test):
    """{(normalized values of cols): (table, row hash)} of a run's input entries (the train side only when skip_test)."""
    from .run import entries_of, values_at
    memo, w = {}, Walk(eng)
    ref = w.links(run, "on")[0]
    out = {}
    for i, (m, sp, _) in enumerate(entries_of(eng, ref, memo)[2]):
        if skip_test and sp == "test":
            continue
        vals = values_at(eng, ref, i, cols, memo)[0]
        key = tuple(norm_text(vals[r]) for r in sorted(cols))
        if all(x not in (None, "") for x in key):
            out.setdefault(key, (entries_of(eng, ref, memo)[0], m))
    return out


def same_content(eng, m, run):
    """[(eval row, train row)]: rows this run fed the model whose values, in the columns the model reads, equal a row it was trained
    on, by content, whatever table either came from (#3). The model reads the roles its predict recipe binds that its train recipe
    bound too (a label is bound only at training)."""
    w = Walk(eng)
    trains = w.links(m, "run")
    if not trains or not w.links(run, "on"):
        return []
    tcols = eng.node(w.links(trains[0], "recipe")[0])["payload"].get("cols") or {}
    pcols = eng.node(w.inputs(run)["recipe"])["payload"].get("cols") or {}
    roles = sorted(set(tcols) & set(pcols))
    if not roles or not w.links(trains[0], "on"):
        return []
    seen = seen_values(eng, trains[0], {r: tcols[r] for r in roles}, skip_test=True)
    now = seen_values(eng, run, {r: pcols[r] for r in roles}, skip_test=False)
    return [(now[k_], seen[k_]) for k_ in now if k_ in seen]


def _overlap(eng, run):
    """[(model, the units it was trained on that this run read, [(eval row, train row)] equal by content)]."""
    w = Walk(eng)
    read = set()
    for t, r, _ in w.set_rows(eng.node(run)["payload"]["input_set"]):
        read |= set(w.rows_up(t, r))
    out = []
    for m in seers_of(eng, w.inputs(run)["recipe"]):
        made_from_data = eng.node(m)["payload"].get("artifact_kind") != "model"
        both, same = units(w.seen(m)) & units(read), ([] if made_from_data else same_content(eng, m, run))
        if both or same:
            out.append((m, both, same))
    return out


def _says(eng, m, both, same, who="model", what="is evaluated on"):
    name = names.label(eng, m) or m[:12]
    kind = eng.node(m)["payload"].get("artifact_kind")
    if kind != "model":                                          # made from data (W4): shown to the model in its prompt or role
        return f"{kind} {name} {'were' if kind.endswith('s') else 'was'} made from {len(both)} of the rows it {what}"
    if both:
        return f"{who} {name} was trained on {len(both)} of the rows it {what}"
    (et, er), (tt, tr) = same[0]
    return (f"{who} {name} saw the same input as {len(same)} of the rows it {what}, by content (e.g. {et} {er[:12]} = {tt} {tr[:12]} "
            "it was trained on)")


def c_contamination(eng, s, scope):
    """A model that produced the judged rows was trained on any of the rows it made them from: the same rows, or rows equal by content
    in the columns the model reads (#3)."""
    hits = []
    for run in generate_runs(eng, s)[0]:
        for m, both, same in _overlap(eng, run):
            hits.append(_says(eng, m, both, same))
    return ("fail", "; ".join(hits)) if hits else ("pass", "no evaluated row is in the evaluated model's training data")


def c_leak(eng, s, scope):
    """A judge (a generate that read another generate's outputs) whose model was trained on rows that include what it judges."""
    hits = []
    for run in generate_runs(eng, s)[1]:
        for m, both, same in _overlap(eng, run):
            hits.append(_says(eng, m, both, same, "judge model", "judges"))
    return ("fail", "; ".join(hits)) if hits else ("pass", "no judge was trained on what it judges")


# ---------------------------------------------------------------- datasets and evalsets
def _members(eng, s):
    rows = Walk(eng).rows(s)
    return eng.node(s)["payload"]["table"], [(m, sp) for _, m, sp, _ in rows]


def c_split_assigned(eng, s, scope):
    _, ms = _members(eng, s)
    bad = [m for m, sp in ms if sp not in ("train", "val", "test")]
    return ("fail", f"{len(bad)} members have no split (train / val / test)") if bad else ("pass", "every member has one split")


def group_of(eng, s):
    """The group key of a dataset's select: its `group` param, or the column bound to its `group` role."""
    w = Walk(eng)
    r = eng.node(w.inputs(w.links(s, "run")[0])["recipe"])
    return (r["payload"].get("params") or {}).get("group") or (r["payload"].get("cols") or {}).get("group")


def c_group_leak(eng, s, scope):
    """No group key on two sides of the split, read from the rows and their lineage, never from the module."""
    group = group_of(eng, s)
    if not group:
        return "pass", "no group key"
    col = group.rpartition(".")[2]
    t, ms = _members(eng, s)
    sides, w = {}, Walk(eng)
    for m, sp in ms:
        for ut, u in w.rows_up(t, m):
            if col in {c["name"] for c in eng.rec.spec(ut)["columns"]}:
                if (g := eng.rec.get_row(ut, (u,)).get(col)) is not None:
                    sides.setdefault(g, set()).add(sp)
    both = sorted(str(g) for g, sp in sides.items() if len(sp) > 1)
    return ("fail", f"group {col!r} values on several sides: {both[:5]}") if both else ("pass", f"no {col!r} on two sides")


def c_unit_set(eng, s, scope):
    t, _ = _members(eng, s)
    if t.startswith("raw."):
        return "pass", f"over {t}"
    w = [r for r in eng.rec.table_rows("bitt.writer") if r["tbl"] == t]
    if w and eng.node(w[0]["node"])["kind"] == "module" and eng.node(w[0]["node"])["payload"]["header"]["scope"] == "table":
        return "pass", f"over {t}, made by a table derive (each row = the source rows that made it)"
    return "fail", (f"a dataset is a set over its units: raw rows, or a table a table derive made; {t} holds row outputs, keyed by "
                    "what they read (equal inputs share one row there). next: select over the raw rows, or build the units with a table derive")


def c_frozen_test(eng, s, scope):
    """A new version of a dataset line keeps its parent's test members unless it adds units (then its test side is new: a major)."""
    parent = Walk(eng).links(s, "parent")
    if not parent:
        return "pass", "no parent version"
    before, after = dict(_members(eng, parent[0])[1]), dict(_members(eng, s)[1])
    if set(after) - set(before):
        return "pass", "units added: a new test side (a major)"
    moved = [m for m in after if (before[m] == "test") != (after[m] == "test")]
    if moved:
        return "fail", (f"the select moved {len(moved)} rows onto or off the test side. next: keep the parent's test members as they "
                        "are (rows may be taken out), or add units for a new test side")
    return "pass", "the parent's test members are kept"


def c_excluded_kept(eng, s, scope):
    """A new set still holds rows a person marked excluded in this task (A22): a warning, never a change to the set."""
    task = eng.task_of(scope["in"])
    _, ms = _members(eng, s)
    marked = {r for x in eng.rec.find("excluded") if eng.task_of(x["id"]) == task for r in x["payload"]["rows"]}
    kept = [m for m, _ in ms if m in marked]
    return ("fail", f"{len(kept)} rows marked excluded are in it (bitt data exclude made them)") if kept else ("pass", "none excluded")


def judged_module(eng, run):
    return inner(eng, Walk(eng).inputs(run)["module"])
