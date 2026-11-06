"""The module tool (spec/cards/module.yaml): modules and wraps on the shelf (foundation.md §B).

  module.define   a file (kept by hash) + its contract (tools/header.py); a new version joins its parent's line (or its name's)
  module.wrap     a module with params / artifacts fixed: a module of the same kind, on its own line, pinning what it wraps
The shelf is `lib`: a module belongs to no task (its `origin` link is where it was added, F18). Versions are tags (tag.yaml).
"""
import hashlib
from pathlib import Path

from .. import blobs, names
from ..errors import Refused
from ..kernel import Package
from . import header

from ..cards import CARDS  # noqa: E402  (a release: inside the package)


def code_of(eng, module):
    """The bytes of a module (a wrap: of the module it wraps)."""
    n = eng.node(module)
    if n["links"].get("wraps"):
        return code_of(eng, n["links"]["wraps"])
    return blobs.get(n["payload"]["code_blob"])


def inner(eng, module):
    """The module a wrap wraps, all the way down (a module is its own inner)."""
    n = eng.node(module)
    return inner(eng, n["links"]["wraps"]) if n["links"].get("wraps") else module


def pins_of(eng, module):
    """{role: data} a module's wraps pin, the outermost first wins (a wrap of a wrap may pin another role, never re-pin one)."""
    out, m = {}, module
    while m:
        n = eng.node(m)
        for role, d in ((n["payload"].get("fixed") or {}).get("pin") or {}).items():
            out.setdefault(role, d)
        m = n["links"].get("wraps")
    return out


def kind_of(eng, module):
    return eng.node(module)["payload"]["header"]["kind"]


def shipped():
    """{name: path} of every module bitt ships (the built-ins): `builtin` everywhere (D16)."""
    from ..builtins import SHIPPED
    return dict(SHIPPED)


def shipped_hashes():
    return {hashlib.sha256(p.read_bytes()).hexdigest() for p in shipped().values()}


def _line(eng, ctx, kind):
    """(root, the parent node or None): the line a new member joins, its parent's or its name's."""
    parent = eng.node(ctx["parent"]) if ctx.get("parent") else None
    if parent and parent["kind"] != kind:
        raise Refused(f"{ctx['_stamp']['card']}: parent {ctx['parent'][:12]} is a {parent['kind']}, not a {kind}")
    root = names.place(eng, "lib", ctx["name"], kind, ctx.get("parent"))
    if root and not parent:
        parent = names.members(eng, root)[-1]                     # the same name again = the line's next version
    return root, parent


def i_define(eng, e, ctx, refs):
    raw = ctx["code"] if isinstance(ctx["code"], bytes) else ctx["code"].encode()
    h, _ = header.parse(raw)                                     # module.header refuses an incomplete one
    root, parent = _line(eng, ctx, "module")
    extra = {"builtin": True} if hashlib.sha256(raw).hexdigest() in shipped_hashes() else {}
    links = {**names.line_link(root), **({"prev": parent["id"]} if parent and not ctx.get("parent") else {})}
    m = eng.make("module", ctx, refs, code_blob=blobs.put(raw), header=h, _links=links,
                 **({"source": ctx["source"]} if ctx.get("source") else {}), **extra)
    names.settle(eng, ctx, "lib", ctx["name"], m, root)
    return {"module": m}


def i_wrap(eng, e, ctx, refs):
    base = eng.node(ctx["module"])["payload"]["header"]
    fixed = ctx.get("params") or {}
    roles = ctx.get("artifacts") or {}
    h = {**base, "params": {k: v for k, v in base["params"].items() if k not in fixed},
         "roles": {k: v for k, v in base["roles"].items() if k not in roles}, "does": ctx["does"]}
    root, parent = _line(eng, ctx, "module")
    links = {"wraps": ctx["module"], **names.line_link(root), **({"prev": parent["id"]} if parent and not ctx.get("parent") else {})}
    w = eng.make("module", ctx, refs, header=h, fixed={"params": fixed, "artifacts": roles, "pin": ctx.get("pin") or {}}, _links=links)
    names.settle(eng, ctx, "lib", ctx["name"], w, root)
    return {"wrap": w}


def c_header(eng, s, scope):
    n = eng.node(s)
    if n["links"].get("wraps"):
        return c_header(eng, inner(eng, s), scope)
    raw = blobs.get(n["payload"]["code_blob"])
    if hashlib.sha256(raw).hexdigest() != n["payload"]["code_blob"]:
        return "fail", "the module's code no longer hashes to its node"
    h, problem = header.parse(raw)
    return ("fail", problem) if problem else ("pass", f"a {h['kind']} module: {h['does']}")


def c_line_free(eng, s, scope):
    """One name, one line, one kind (a module line never turns into an artifact, a derive never into a check)."""
    n = eng.node(s)
    root = names.line_of(eng, s)
    if root == s:
        return "pass", "a new line"
    first = eng.node(root)
    if first["kind"] != n["kind"]:
        return "fail", f"`{names.label(eng, root)}` is a {first['kind']} line"
    a, b = first["payload"].get("header", {}).get("kind"), n["payload"].get("header", {}).get("kind")
    if a != b:
        return "fail", f"`{names.label(eng, root)}` is a line of {a} modules; a {b} module takes another name"
    if first["payload"].get("artifact_kind") != n["payload"].get("artifact_kind"):
        return "fail", f"`{names.label(eng, root)}` is a line of {first['payload']['artifact_kind']} artifacts"
    return "pass", f"the next version on `{names.label(eng, root)}`"


PY = {"text": str, "int": int, "number": (int, float), "bool": bool, "json": (dict, list)}


def fits(declared, given, who):
    """Why `given` params do not fit `declared` ({name: {type, default}}), or None."""
    unknown = [k for k in given if k not in declared]
    if unknown:
        return f"{who} has no params {unknown} (it declares {sorted(declared) or 'none'})"
    for k, v in given.items():
        t = declared[k]["type"]
        if v is not None and (not isinstance(v, PY[t]) or (t in ("int", "number") and isinstance(v, bool))):
            return f"{who}: param {k} is {t}, not {type(v).__name__}"
    return None


def c_wrap_fits(eng, s, scope):
    n = eng.node(s)
    base = eng.node(n["links"]["wraps"])["payload"]["header"]
    if p := fits(base["params"], n["payload"]["fixed"]["params"], names.label(eng, n["links"]["wraps"]) or "the module"):
        return "fail", p
    for role, a in n["payload"]["fixed"]["artifacts"].items():
        if role not in base["roles"]:
            return "fail", f"the module has no role {role!r} (its roles: {sorted(base['roles']) or 'none'})"
        if (k := eng.node(a)["payload"]["artifact_kind"]) != base["roles"][role]:
            return "fail", f"role {role!r} takes a {base['roles'][role]} artifact, not a {k}"
    if again := sorted(set(n["payload"]["fixed"].get("pin") or {}) & set(pins_of(eng, n["links"]["wraps"]))):
        return "fail", f"the wrapped module already pins {again}: a pin never moves (wrap the unpinned module instead)"
    return "pass", "fits"


def c_in_git(eng, s, scope):
    """The exact code is committed: a member of its line with the same code names a commit (re-adding the file after a commit records
    it). A built-in, an artifact or data has nothing of its own to commit here."""
    n = eng.node(s)
    if n["kind"] != "module":
        return "pass", f"a {n['kind']}"
    m = inner(eng, s)
    if eng.node(m)["payload"].get("builtin"):
        return "pass", "a built-in"
    blob = eng.node(m)["payload"]["code_blob"]
    same = [x for x in names.members(eng, names.line_of(eng, m)) if x["payload"].get("code_blob") == blob]
    if any((x["payload"].get("source") or {}).get("commit") for x in same):
        return "pass", "committed"
    src = next((x["payload"]["source"] for x in same if x["payload"].get("source")), None)
    return "fail", f"not committed in git: {names.label(eng, m)} ({(src or {}).get('path') or 'added without a file'})"


def package():
    return Package(name="module", cards=[CARDS / "module.yaml"], impls={"module.define": i_define, "module.wrap": i_wrap},
                   rules={"module.header": c_header, "module.line_free": c_line_free, "module.wrap_fits": c_wrap_fits,
                           "module.in_git": c_in_git})
