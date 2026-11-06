"""The tag tool (spec/cards/tag.yaml): what the workflow says about a version (foundation.md §C2, words.md W14).

  version     the next version on the line: major when the contract changed against the previous version tag (a module's header, an
              artifact's needs → gives, a dataset's units or test side), else minor; the first is 1.0, bump `first` (anyone's) on a
              module or an artifact, a major (a person's) on a dataset or an evalset
  alias       a movable name (`@live`) on a versioned target: the newest alias tag of that name on the line wins
  trust       trusted / hint, per task (D16): `builtin` is a module bitt ships, everywhere; trusted needs a measured agreement about this
              exact module or wrap, a deterministic check, committed code and a person
  deprecated  new recipes over it are warned; old records stay readable
"""
import json
import re
from pathlib import Path

from .. import names, sets
from ..errors import Refused
from ..kernel import Package
from ..util import as_list
from ..walk import Walk
from . import envs
from .header import contract_of
from .module import code_of, inner

CARDS = Path(__file__).resolve().parents[3] / "spec" / "cards"
ALIAS = re.compile(r"[a-z][a-z0-9_]*")


def vparse(v):
    return tuple(map(int, str(v).split(".")))


def previous(eng, target):
    """(the line member with the highest version tag other than target, its version) or (None, None)."""
    best = (None, None)
    for m in names.members(eng, names.line_of(eng, target)):
        v = names.version_of(eng, m["id"]) if m["id"] != target else None
        if v and (best[1] is None or vparse(v) > vparse(best[1])):
            best = (m["id"], v)
    return best


def change(eng, old, new):
    """major or minor (version.bump): what changed between two members of one line."""
    a, b = eng.node(old), eng.node(new)
    if a["kind"] == "module":
        pins = [(x["payload"].get("fixed") or {}).get("pin") or {} for x in (a, b)]
        return "minor" if contract_of(a["payload"]["header"]) == contract_of(b["payload"]["header"]) and pins[0] == pins[1] else "major"
    if a["kind"] == "artifact":
        ca, cb = a["payload"].get("contract") or {}, b["payload"].get("contract") or {}
        return "minor" if (ca.get("needs"), ca.get("gives")) == (cb.get("needs"), cb.get("gives")) else "major"
    w = Walk(eng)
    ma, mb = ({m: sp for _, m, sp in w.set_rows(x["payload"]["set"])} for x in (a, b))
    if a["payload"]["table"] != b["payload"]["table"] or set(mb) - set(ma):
        return "major"                                          # another unit table, or members added
    if {m for m, sp in ma.items() if sp == "test"} != {m for m, sp in mb.items() if sp == "test"}:
        return "major"                                          # the test side changed
    return "minor"                                              # members removed (not test)


def i_make(eng, e, ctx, refs):
    tag, target = ctx["tag"], ctx["target"]
    bump, value = "-", ctx.get("value")
    if tag == "version":
        prev, v = previous(eng, target)
        first = "major" if eng.node(target)["kind"] in ("dataset", "evalset") else "first"   # an agent versions its own code
        bump = first if prev is None else change(eng, prev, target)
        value = "1.0" if prev is None else (f"{vparse(v)[0] + 1}.0" if bump == "major" else f"{vparse(v)[0]}.{vparse(v)[1] + 1}")
    t = eng.make("tag", {**ctx, "value": value}, refs, bump=bump)
    return {"tagged": t, "bump": bump}


def trust_of(eng, module, task):
    """builtin (bitt ships it: everywhere), else the newest trust tag on it in `task`, else hint (D16)."""
    if eng.node(inner(eng, module))["payload"].get("builtin"):
        return "builtin"
    ts = [t for t in names.tags(eng, module, "trust") if eng.task_of(t["id"]) == task]
    return ts[-1]["payload"]["value"] if ts else "hint"


def trusted_elsewhere(eng, module, task):
    """The tasks where it is trusted (information only: trust does not travel)."""
    return sorted({names.task_name(eng, eng.task_of(t["id"])) for t in names.tags(eng, module, "trust")
                   if t["payload"]["value"] == "trusted" and eng.task_of(t["id"]) != task})


def deprecated(eng, nid):
    d = names.tags(eng, nid, "deprecated")
    return d[-1]["payload"]["value"] if d else None


# ---------------------------------------------------------------- checks
def c_once(eng, s, scope):
    tag, v, n = scope["tag"], scope.get("value"), eng.node(s)
    if tag == "version" and names.version_of(eng, s):
        return "fail", f"it is {names.ref_of(eng, s)} already"
    if tag == "version" and not names.label(eng, s):
        return "fail", "a version names a line: name it first"
    if tag == "alias" and (not v or not ALIAS.fullmatch(v) or v in names.RESERVED):
        return "fail", f"an alias is a name ([a-z][a-z0-9_]*, never a version, not reserved), not {v!r}"
    if tag == "trust":
        if v not in ("trusted", "hint"):
            return "fail", f"trust is trusted or hint (builtin is bitt's), not {v!r}"
        if n["kind"] != "module" or n["payload"]["header"]["kind"] != "check":
            return "fail", "trust is said of a check module or wrap (what judges); a generate that judges is a hint"
    if tag == "deprecated" and not v:
        return "fail", "say why it is deprecated (value)"
    return "pass", "ok"


def c_alias_on_version(eng, s, scope):
    return ("pass", names.ref_of(eng, s)) if names.version_of(eng, s) else ("fail", "the target has no version tag")


def c_upstream_tagged(eng, s, scope):
    from .run import other_task_loose
    up = eng.lineage(s) - {s}
    loose = [x for x in up if eng.node(x)["kind"] in ("dataset", "evalset") and not names.version_of(eng, x)]
    if loose:
        return "fail", f"untagged data upstream: {', '.join(names.label(eng, x) or x[:12] for x in loose)}"
    task, w = eng.task_of(scope["in"]), Walk(eng)                # #4: what a step here read from another task is a version of it
    for r in sorted(x for x in up | {s} if eng.node(x)["kind"] == "run" and eng.task_of(x) == task):
        if hit := other_task_loose(eng, task, [*w.links(r, "on"), *w.links(r, "read")]):
            x, t = hit[0]
            return "fail", (f"made from {names.label(eng, x) or eng.node(x)['kind'] + ' ' + x[:12]} of task {names.task_name(eng, t)}, "
                            "which is not a version. next: version it there, then remake this from <task>/<name>@<version>")
    return "pass", "every dataset / evalset upstream is tagged"


def evidence_stands_on(eng, target, evidence):
    """The data the evidence for tagging `target` stands on: a decision → its eval run's data, a finding → its evidence's, a validation
    → what it validated, a run (an agreement) → its own. Never the target or what it is made from (tag.upstream_tagged rules that)."""
    w, out, todo, seen = Walk(eng), [], list(evidence), set()
    while todo:
        e = todo.pop(0)
        if e in seen or e not in eng.rec.nodes:
            continue
        seen.add(e)
        kind = eng.node(e)["kind"]
        if kind == "finding":
            todo += w.links(e, "evidence")
        elif kind == "validation":
            todo += [x for x in w.links(e, "subject") if eng.node(x)["kind"] in ("run", "dataset", "evalset", "selection", "raw")]
        elif kind == "decision":
            todo += w.links(e, "run")
        elif kind in ("run", "dataset", "evalset", "selection", "raw"):
            out += list(w.frontier(e))
    own = eng.lineage(target) | {target}                      # what the target is made from: tag.upstream_tagged's
    return [x for x in dict.fromkeys(out) if x not in own]


def not_a_version(eng, xs):
    return [x for x in xs if not (eng.node(x)["kind"] in ("dataset", "evalset") and names.version_of(eng, x))]


def c_evidence_versioned(eng, s, scope):
    """A version or a trust is a claim; what it cites must stand on named, frozen data: every dataset / evalset the evidence was
    measured on is a version (a raw import or a selection is not)."""
    loose = not_a_version(eng, evidence_stands_on(eng, s, [*as_list(scope.get("because")), *as_list(scope.get("agreement"))]))
    if loose:
        x = loose[0]
        return "fail", (f"the evidence stands on {names.label(eng, x) or eng.node(x)['kind'] + ' ' + x[:12]}, which is not a "
                        f"version{' (a raw import: make a dataset or evalset of it)' if eng.node(x)['kind'] == 'raw' else ''}")
    return "pass", "the evidence stands on versions only"


def c_agreement_about(eng, s, scope):
    a = scope.get("agreement")
    if not a:
        return "fail", "trusting a check cites the agreement run that measured it (--agreement <run>)"
    about = [x for x in eng.lineage(a) if eng.node(x)["kind"] == "run" and eng.node(eng.node(x)["links"]["recipe"])["links"]["module"] == s]
    if not about:
        return "fail", "the agreement run did not read this module's verdicts (it measured another module or configuration)"
    return "pass", f"measured over run {about[0][:12]}"


def c_deterministic(eng, s, scope):
    """The check run twice by the system (scratch jobs, no records) on up to 6 rows it last judged: the same verdicts."""
    from . import run as runs
    h_ = eng.node(s)["payload"]["header"]
    if h_["kind"] != "check" or h_["scope"] != "row":
        return ("pass", "an aggregator is a function of its rows") if h_["kind"] == "check" else ("fail", f"a {h_['kind']} is not a check")
    last = [r for r in eng.rec.find("run") if eng.node(r["links"]["recipe"])["links"]["module"] == s]
    if not last:
        return "fail", "it never ran: run it once, then promote it"
    r = last[-1]
    recipe = r["links"]["recipe"]
    src, memo = Walk(eng).inputs(r["id"])["on"][0], {}
    _, _, es = runs.entries_of(eng, src, memo)
    rows = [runs.values_at(eng, src, i, eng.node(recipe)["payload"]["cols"], memo)[0] for i in range(min(6, len(es)))]
    env = envs.get("local")
    outs = []
    for i in range(2):
        d = env.local_dir(f"determinism-{s[:16]}-{i}")
        params = runs.recipes.params(eng, recipe)
        envs.write_module_job(d, {**runs.job_spec(h_), "params": params}, code_of(eng, s), rows, env.python())
        if runs.run_dir(env, d) != "done":
            return "fail", f"the scratch run failed: {runs.log_tail(d, 200)}"
        outs.append([json.loads(x) for x in (d / "output" / "rows.jsonl").read_text().splitlines() if x.strip()])
    return ("pass", f"the same verdicts twice on {len(rows)} rows") if outs[0] == outs[1] else ("fail", "two runs gave other verdicts")


def package():
    return Package(name="tag", cards=[CARDS / "tag.yaml"], impls={"tag.make": i_make},
                   rules={"tag.once": c_once, "tag.alias_on_version": c_alias_on_version, "tag.upstream_tagged": c_upstream_tagged, "tag.evidence_versioned": c_evidence_versioned,
                           "tag.agreement_about": c_agreement_about, "tag.deterministic": c_deterministic})


__all__ = ["Refused", "trust_of", "trusted_elsewhere", "deprecated"]
