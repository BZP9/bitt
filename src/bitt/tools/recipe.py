"""The recipe tool (spec/cards/recipe.yaml): a use of a module (foundation.md §C1, §M).

A recipe node holds the module (a link: that exact version), the artifacts by role (links + the {role: id} map), the params (the
module's defaults filled in, so one setting is one hash) and the cols ({role: column}). Its spec hash is the work: the same in every
task and whoever made it. It has no stored name: its label is derived (`label`: `<base>:<hash8>`, never changing), and `find` reads a
label back; `--name` adds a fixed alias.
"""
import re
from pathlib import Path

from .. import names
from ..errors import Refused
from ..kernel import Package
from ..util import as_list
from .module import fits, inner

from ..cards import CARDS  # noqa: E402  (a release: inside the package)
COL = re.compile(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)?")


def header(eng, recipe):
    return eng.node(eng.node(recipe)["links"]["module"])["payload"]["header"]


def artifacts(eng, recipe):
    """{role: artifact id}: the recipe's own and those its wrap fixed."""
    m = eng.node(eng.node(recipe)["links"]["module"])
    out = {}
    for w in _wraps(eng, m["id"]):
        out.update(eng.node(w)["payload"]["fixed"]["artifacts"])
    return {**out, **(eng.node(recipe)["payload"].get("artifacts") or {})}


def params(eng, recipe):
    """Every param the module runs with: what its wraps fixed, then the recipe's."""
    m = eng.node(recipe)["links"]["module"]
    out = {}
    for w in _wraps(eng, m):
        out.update(eng.node(w)["payload"]["fixed"]["params"])
    return {**out, **eng.node(recipe)["payload"].get("params", {})}


def _wraps(eng, m):
    """The wraps from the innermost out (a module is no wrap)."""
    chain = []
    while eng.node(m)["links"].get("wraps"):
        chain.append(m)
        m = eng.node(m)["links"]["wraps"]
    return list(reversed(chain))


def needs(eng, module, arts):
    """Every role a recipe must bind: what the module reads, then each artifact's needs (a prompt's slots)."""
    out = list(eng.node(module)["payload"]["header"]["reads"])
    for a in arts.values():
        out += [x for x in (eng.node(a)["payload"].get("contract") or {}).get("needs", []) if x not in out]
    return out


def i_make(eng, e, ctx, refs):
    h = eng.node(ctx["module"])["payload"]["header"]
    given = ctx.get("params") or {}
    filled = {k: d["default"] for k, d in h["params"].items() if "default" in d and k not in given}
    extra = {}
    if h["kind"] == "pipeline":                                  # every version its steps name, pinned now (C11)
        from .pipeline import pins
        extra["pins"] = pins(eng, ctx["module"], eng.task_of(ctx["in"]), {**filled, **given})
    if int(ctx.get("samples") or 1) < 1:
        raise Refused("recipe.make: samples is at least 1")
    if ctx.get("sample_rows") is not None and int(ctx["sample_rows"]) < 2:
        raise Refused("recipe.make: sample_rows is at least 2 (the smoke rung is 1 row)")
    r = eng.make("recipe", {**ctx, "params": {**filled, **given}, "cols": ctx.get("cols") or {}, "samples": int(ctx.get("samples") or 1),
                                **({"sample_rows": int(ctx["sample_rows"])} if ctx.get("sample_rows") else {})},
                 refs, **extra)
    if ctx.get("name"):
        task = eng.task_of(ctx["in"])
        if names.binding(eng, task, ctx["name"]):
            raise Refused(f"recipe.make: `{ctx['name']}` is taken in this task (a name names one thing)")
        names.bind(eng, ctx, task, ctx["name"], r)
    return {"recipe": r}


def c_fits(eng, s, scope):
    n = eng.node(s)
    m = n["links"]["module"]
    h = eng.node(m)["payload"]["header"]
    who = names.label(eng, m) or "the module"
    if p := fits(h["params"], n["payload"]["params"], who):
        return "fail", p
    missing = [k for k, d in h["params"].items() if "default" not in d and k not in n["payload"]["params"]]
    if missing:
        return "fail", f"{who} needs params {missing} (no default). next: --params {missing[0]}=<value>"
    arts = n["payload"].get("artifacts") or {}
    extra = [r for r in arts if r not in h["roles"]]
    if extra:
        return "fail", f"{who} has no role {extra} (its roles: {sorted(h['roles']) or 'none'})"
    for role, kind in h["roles"].items():
        if role not in arts:
            return "fail", f"{who} fills its `{role}` role with a {kind} artifact. next: --fill {role}=<{kind}>"
        if (k := eng.node(arts[role])["payload"]["artifact_kind"]) != kind:
            return "fail", f"role `{role}` takes a {kind} artifact, not a {k}"
    return "pass", "fits"


def c_cols_bound(eng, s, scope):
    n = eng.node(s)
    if header(eng, s)["kind"] == "join":
        return join_bound(n["payload"]["cols"], n["payload"]["params"])
    want = needs(eng, n["links"]["module"], artifacts(eng, s))
    cols = n["payload"]["cols"]
    unbound = [r for r in want if r not in cols]
    if unbound:
        return "fail", f"unbound: {unbound}. next: --cols {unbound[0]}=<column>"
    extra = [r for r in cols if r not in want]
    if extra:
        return "fail", f"nothing reads {extra} (the module and its artifacts need {want})"
    own = [v for v in cols.values() if isinstance(v, str) and v.rpartition(".")[2].startswith("bitt_")]
    if own:
        return "fail", (f"{own}: bitt_* columns are bitt's and are never bound (bitt_extra holds what a module did not declare). next: "
                        "declare the column in the module that makes it, then bind it")
    bad = [v for v in cols.values() if not isinstance(v, str) or not COL.fullmatch(v)]
    if bad:
        return "fail", f"{bad} are not column names (a column, or <table>.<column>)"
    return "pass", ", ".join(f"{r} ← {c}" for r, c in cols.items()) or "nothing to bind"


def join_keys(key):
    """{lookup role: {lookup column: unit column}} of a join's `key` param ({role: column} = the same name on both sides)."""
    return {role: ({v: v} if isinstance(v, str) else dict(v)) for role, v in (key or {}).items()}


def join_bound(cols, params):
    """A join's columns (docs/v2/inputs.md §3): each output column ← `<lookup role>.<column>`, every role a key of `key`."""
    key = params.get("key")
    if not isinstance(key, dict) or not key or not all(isinstance(v, str) or (isinstance(v, dict) and v) for v in key.values()):
        return "fail", 'key is {lookup role: column} or {lookup role: {lookup column: unit column}}. next: --params key=\'{"profile": "customer_id"}\''
    names_ = [x for role, kv in join_keys(key).items() for x in (role, *kv, *kv.values())]
    if bad := [x for x in names_ if not isinstance(x, str) or not COL.fullmatch(x) or "." in x]:
        return "fail", f"key names {bad}: roles and columns are plain names"
    many, asof = params.get("many") or [], params.get("asof") or {}
    if not isinstance(many, list) or (bad := [r for r in many if r not in key]):
        return "fail", f"many names {bad[0] if isinstance(many, list) else many}, which is not a lookup (the lookups: {sorted(key)})"
    if not isinstance(asof, dict) or (bad := [r for r in asof if r not in many]):
        return "fail", f"asof is for a many role (a list read as of the unit's time); {bad[0] if isinstance(asof, dict) else asof} is not in many"
    if bad := [r for r, v in asof.items() if not (isinstance(v, list) and len(v) == 2 and all(isinstance(x, str) and COL.fullmatch(x) for x in v))]:
        return "fail", f"asof {bad[0]} is [lookup column, unit column]"
    if params.get("miss", "empty") not in ("empty", "drop", "fail"):
        return "fail", f"miss is empty, drop or fail, not {params['miss']!r}"
    if not cols:
        return "fail", "a join picks columns: --cols <output column>=<lookup role>.<column>"
    for out, src in cols.items():
        role, dot, col = src.partition(".") if isinstance(src, str) else ("", "", "")
        if not dot or not COL.fullmatch(src) or not COL.fullmatch(out) or out.startswith("bitt_") or col.startswith("bitt_"):
            return "fail", f"{out} ← {src!r}: a join's column is <lookup role>.<column> (an output column of your choosing ← it)"
        if role not in key:
            return "fail", f"{out} ← {src}: {role} is not a lookup (the lookups are the roles of key: {sorted(key)})"
    return "pass", ", ".join(f"{r} ← {c}" for r, c in cols.items())


def c_not_deprecated(eng, s, scope):
    n = eng.node(s)
    for x in [n["links"]["module"], *_wraps(eng, n["links"]["module"]), inner(eng, n["links"]["module"]), *artifacts(eng, s).values()]:
        if d := [t for t in names.tags(eng, x, "deprecated")]:
            return "fail", f"{names.ref_of(eng, x)} is deprecated: {d[-1]['payload']['value']}"
    return "pass", "nothing deprecated"


# ---------------------------------------------------------------- labels (foundation.md §M)
def main_part(eng, recipe):
    """The part a recipe is named after: the artifact in its module's main role (a connector's prompt), else the module."""
    h = header(eng, recipe)
    arts = eng.node(recipe)["payload"].get("artifacts") or {}
    main = "prompt" if "prompt" in h["roles"] else next(iter(h["roles"]), None)
    return arts.get(main) or eng.node(recipe)["links"]["module"]


def _part(eng, nid, task=None):
    lab = names.short(eng, nid, task or eng.task_of(nid)) or nid[:8]
    lab = lab.removeprefix("lib/")
    v = names.version_of(eng, nid)
    return f"{lab}@{v}" if v else lab


def in_task(eng, task):
    """The task's recipes, one per work (spec hash), newest last."""
    seen = {}
    for r in eng.rec.find("recipe"):
        if eng.task_of(r["id"]) == task:
            seen.pop(r["spec_h"], None)
            seen[r["spec_h"]] = r["id"]
    return list(seen.values())


def base_of(eng, recipe):
    """What a label starts with: the main part @v (`summarize@2`, `clean`)."""
    return _part(eng, main_part(eng, recipe))


def label(eng, recipe, task=None):
    """`<base>:<hash8>` (C10, 10-30): the main part @v, then the first 8 hex of the work, always, so a label never changes when another
    recipe appears. An alias (`--name`) resolves alongside it; the label stays the same."""
    n = int(eng.node(recipe)["payload"].get("samples") or 1)
    return f"{base_of(eng, recipe)}:{eng.node(recipe)['spec_h'][:8]}" + (f"x{n}" if n > 1 else "")


def find(eng, ref, task):
    """The recipe a label (`summarize:1d2b8a52`, `summarize@2:1d2b8a52`) or an alias names in a task, or Refused. The base alone
    (`summarize`) never resolves: the refusal lists the full labels of that base, newest first."""
    if b := names.binding(eng, task, ref):
        if eng.node(b["links"]["target"])["kind"] == "recipe":
            return b["links"]["target"]
    rs = in_task(eng, task)
    hits = [r for r in rs if label(eng, r, task) == ref]
    if len(hits) == 1:
        return hits[0]
    same = [r for r in reversed(rs) if ref in (base_of(eng, r), base_of(eng, r).split("@")[0])]
    if same and not hits:
        raise Refused(f"`{ref}` is the start of a label: a recipe's label always ends in its hash. next: write one of "
                      f"{', '.join(label(eng, r, task) for r in same)} (copy it from `bitt recipe` or `bitt recipe list`)")
    if not hits:
        raise Refused(f"no recipe `{ref}` in task {names.task_name(eng, task)!r}. next: bitt recipe list")
    raise Refused(f"`{ref}` names {len(hits)} recipes: {', '.join(label(eng, r, task) for r in hits)}. next: write one of them")


def resolver(eng, ref, task, kinds):
    """A recipe's label where a recipe is wanted (None: not a label here, the names registry reads it)."""
    from .. import cards as lint
    if not task or names.HEX.fullmatch(ref):
        return None
    if not (kinds and any(lint.kind_matches(k, "recipe") for k in kinds)) and ":" not in ref:   # `:` is never in a name: a label
        return None
    try:
        return find(eng, ref, task)
    except Refused as x:
        if ":" in ref or "next: write one of" in str(x):
            raise
        return None


def package():
    return Package(name="recipe", cards=[CARDS / "recipe.yaml"], impls={"recipe.make": i_make},
                   rules={"recipe.fits": c_fits, "recipe.cols_bound": c_cols_bound, "recipe.not_deprecated": c_not_deprecated},
                   resolver=resolver)


__all__ = ["artifacts", "params", "find", "label", "needs", "inner", "as_list"]
