"""Names (docs/v2/names.md): hash first, then names. One grammar, one registry, one resolver for every reader.

A line (the versions of one thing) is identified by its root node; every later member links `line` → the root. A name is a `name`
node: payload {ns, name, class, kind}, links {target: <line root>}. Node bodies hold no names. A version (`@1.0`) or an alias
(`@live`) is a tag on a member (foundation.md §C2): the resolver reads the tags.

  ns   ""          task names (target: the root goal)
       "raw"       raw lines (target: the line's first import)
       "lib"       the shelf: modules (wraps too) and artifacts, every task's short names (foundation.md §B: types are global)
       <goal id>   a task's data lines (datasets, evalsets) and recipe names (`--name`)
"""
import re

from .errors import Refused

NAME = re.compile(r"[a-z][a-z0-9_]*")
MAX = 40
RESERVED = {"tables", "runs", "versions", "refusals", "catalog", "all", "last", "raw", "lib", "bitt", "data", "dataset", "public",
            "information_schema", "made"}           # a task's name is also the schema of its views (A23)
TYPE = {"module", "artifact"}                 # what you write: on the shelf
DATA = {"dataset", "evalset", "raw"}         # what is made or loaded: a data line
REF = re.compile(r"(?:(?P<ns>[a-z][a-z0-9_]*)/)?(?P<name>[a-z][a-z0-9_]*)(?:@(?P<at>\d+(?:\.\d+)?|[a-z][a-z0-9_]*))?")
CYCLE = re.compile(r"(?P<task>[a-z][a-z0-9_]*)#(?P<n>\d+)")
GOAL = re.compile(r"(?P<task>[a-z][a-z0-9_]*)#g(?P<n>\d+)")       # a task's n-th goal or sub-goal, in the order opened
HEX = re.compile(r"[0-9a-f]{8,}")
NEXT = "names: lower-case letters, digits and _ (docs/v2/names.md)"


def family(kind):
    return kind.split(":")[0]


def klass(kind):
    f = family(kind)
    return "task" if f == "goal" else "type" if f in TYPE else "data" if f in DATA else "recipe" if f == "recipe" else None


def problem(name):
    """Why `name` cannot be a name (None = it can)."""
    if not isinstance(name, str) or not NAME.fullmatch(name) or len(name) > MAX:
        return f"{name!r} is not a name: [a-z][a-z0-9_]*, at most {MAX} characters"
    if "__" in name or name.endswith("_"):
        return f"{name!r}: `__` and a trailing `_` are reserved for bitt's table suffixes"
    if re.search(r"v\d+$", name):
        return f"{name!r} ends in a version: a version is always written with @ (`{re.sub(r'_?v(\d+)$', r'@\1', name)}`)"
    if name.startswith("pg_"):
        return f"{name!r}: names starting pg_ are Postgres's (a task's name is its views' schema)"
    if name in RESERVED:
        return f"{name!r} is reserved ({', '.join(sorted(RESERVED))})"
    if HEX.fullmatch(name):
        return f"{name!r} looks like a hash: names of 8+ hex characters are reserved for ids"
    return None


def check(name, what="name"):
    p = problem(name)
    if p:
        raise Refused(f"{what}: {p}")
    return name


# ---------------------------------------------------------------- the registry
def line_of(eng, nid):
    return eng.node(nid)["links"].get("line") or nid


def members(eng, root):
    """The line's nodes in seq order: its root, then every node that links `line` → it."""
    return [eng.node(root)] + eng.kids(root, role="line")


def binding(eng, ns, name):
    """The name node for ns/name, or None."""
    hits = [n for n in eng.rec.find("name") if n["payload"]["ns"] == ns and n["payload"]["name"] == name]
    return hits[0] if hits else None


def bound(eng, root):
    """The active name node of a line, or None."""
    hits = eng.kids(root, role="target", kind="name")
    return hits[-1] if hits else None


def born(eng, root):
    """The first name a line was given (its tables keep it), or None."""
    hits = eng.kids(root, role="target", kind="name")
    return hits[0]["payload"]["name"] if hits else None


def task_name(eng, task):
    b = bound(eng, task) if task else None
    return b["payload"]["name"] if b else None


def task_by_name(eng, name):
    b = binding(eng, "", name)
    if not b:
        raise Refused(f"no task named {name!r} (`bitt tasks` lists them)")
    return b["links"]["target"]


def ns_of(eng, kind, task):
    f = family(kind)
    return "" if f == "goal" else "raw" if f == "raw" else "lib" if f in TYPE else task


def home_of(eng, nid):
    """The namespace a named line lives in: `lib` (the shelf), `raw`, or its task's id."""
    b = bound(eng, line_of(eng, nid))
    if b:
        return b["payload"]["ns"]
    return eng.task_of(nid)


def join(eng, ns, name, kind):
    """The root of the line `name` names in ns, for a new member of `kind` (None = a new line). Refused when the name belongs to
    another kind."""
    check(name)
    b = binding(eng, ns, name)
    if not b:
        return None
    p = b["payload"]
    if p["kind"] != family(kind):
        raise Refused(f"`{name}` names a {p['kind']}; a name is one kind: pick another name. next: give this {family(kind)} another "
                      f"name: a module after what it does (split_by_qid), an artifact after what it holds (summarize), a dataset after "
                      f"what it is (tickets_split)")
    return b["links"]["target"]


def bind(eng, ctx, ns, name, root):
    """A name node: `name` in ns → the line rooted at `root`. The one place a name is given."""
    check(name)
    kind = eng.node(root)["kind"]
    if klass(kind) is None:
        raise Refused(f"a {kind} is not named (names are for tasks, types, data lines and recipes)")
    if ns != "" and binding(eng, ns, name):                 # a task name: the card's control.unique_task_name judges it
        raise Refused(f"`{name}` is taken in this namespace (a name names one line)")
    if clash := _shelf_clash(eng, ns, name, root):
        raise Refused(clash)
    links = {"target": root}
    return eng.rec.put("name", {"ns": ns, "name": name, "class": klass(kind), "kind": family(kind)},
                       links, ctx["_stamp"])


def _shelf_clash(eng, ns, name, root):
    """A short name means one thing: a task's name may not equal a shelf name (a module's, an artifact's), and the reverse."""
    if ns == "lib":
        hit = [b for b in eng.rec.find("name") if b["payload"]["name"] == name and b["payload"]["ns"] not in ("", "raw", "lib")
]
        if hit:
            return (f"`{name}` is already a name in task {task_name(eng, hit[0]['payload']['ns'])!r}; a shelf name is every "
                    f"task's short name. next: add it under another name")
        return None
    if ns in ("", "raw") or not binding(eng, "lib", name):
        return None
    n = eng.node(root)
    return (f"`{name}` names a {binding(eng, 'lib', name)['payload']['kind']} on the shelf (lib/{name}); a task's name may not shadow "
            f"it. next: give this {family(n['kind'])} another name (a dataset after what it is: tickets_split)")


# ---------------------------------------------------------------- versions and display
def vparse(v):
    return tuple(map(int, str(v).lstrip("v").split(".")))


def label(eng, nid):
    """`[ns/]name` of a node's line (the task's own short name never prefixed here), or None if unnamed."""
    b = bound(eng, line_of(eng, nid))
    if not b:
        return None
    ns = b["payload"]["ns"]
    pre = "raw/" if ns == "raw" else "lib/" if ns == "lib" else "" if ns == "" else f"{task_name(eng, ns)}/"
    return pre + b["payload"]["name"]


def short(eng, nid, task=None):
    """label() without the reader's own task prefix (`vk_train` inside vk, `vk/vk_train` elsewhere)."""
    lab = label(eng, nid)
    own = task_name(eng, task) if task else None
    if lab and task and lab.startswith("lib/"):              # a shelf module is every task's short name
        return lab[4:]
    return lab.split("/", 1)[1] if lab and own and lab.startswith(own + "/") else lab


def ref_of(eng, nid, task=None):
    """How to type this node: `name@1.0` (a version), `raw/x@2` (an import), `name` (a task or an unversioned thing), else its short hash."""
    n = eng.node(nid)
    lab = label(eng, nid)
    if not lab:
        return nid[:12]
    if task and not lab.startswith("raw/") and "/" in lab and n.get("task") == task:
        lab = lab.split("/", 1)[1]
    if family(n["kind"]) == "raw":
        imports = [m["id"] for m in members(eng, line_of(eng, nid))]
        return f"{lab}@{imports.index(nid) + 1}"
    v = version_of(eng, nid)
    return f"{lab}@{v}" if v else lab


def vlabel(eng, nid, task=None):
    """How a version reads: `summarize@1.1` once tagged, else `summarize, unversioned 3` (its place among the line's members)."""
    n = eng.node(nid)
    if version_of(eng, nid):
        return ref_of(eng, nid, task)
    lab = short(eng, nid, task) or nid[:12]
    same = [m["id"] for m in members(eng, line_of(eng, nid)) if m["kind"] == n["kind"]] if label(eng, nid) else []
    return f"{lab}, unversioned {same.index(nid) + 1}" if nid in same else lab


# ---------------------------------------------------------------- the resolver
def _pick(eng, root, at, kinds, task):
    from . import cards as lint
    ms = members(eng, root)
    fam = family(ms[0]["kind"])
    if fam == "goal":                                     # a task name where a cycle is wanted: its newest open cycle
        if kinds and not any(lint.kind_matches(k, "goal") for k in kinds) and any(lint.kind_matches(k, "cycle") for k in kinds):
            return newest_open_cycle(eng, root)
        return root
    if fam == "raw":
        if at is None:
            return ms[-1]["id"]
        if not at.isdigit() or not 1 <= int(at) <= len(ms):
            raise Refused(f"raw/{label(eng, root).split('/')[-1]}@{at}: a raw line's versions are its imports, 1–{len(ms)}"
                          + (" (`@all` = the table, for inspect)" if at == "all" else ""))
        return ms[int(at) - 1]["id"]
    want = [m for m in ms if (any(lint.kind_matches(k, m["kind"]) for k in kinds) if kinds else family(m["kind"]) == fam)]
    if not want:
        raise Refused(f"`{label(eng, root)}` names a {fam}, not one of {list(kinds)}")
    if at is None:
        return want[-1]["id"]
    if at[0].isdigit():
        tagged = [(m, version_of(eng, m["id"])) for m in want]
        tagged = [(m, v) for m, v in tagged if v]
        hit = [(m, v) for m, v in tagged if (vparse(v) == vparse(at) if "." in at else vparse(v)[0] == int(at))]
        if not hit:
            have = sorted({v for _, v in tagged}, key=vparse)
            raise Refused(f"`{label(eng, root)}@{at}` is not a version (tagged: {', '.join(have) or 'none yet'}). next: bitt tag "
                          f"{label(eng, root)} --version (a version tag names a version)")
        return max(hit, key=lambda mv: vparse(mv[1]))[0]["id"]
    ids = {m["id"] for m in ms}
    moved = [t for t in eng.rec.find("tag") if t["payload"]["tag"] == "alias" and t["payload"]["value"] == at
             and t["links"]["target"] in ids]
    if not moved:
        raise Refused(f"no alias `{at}` on `{label(eng, root)}` (bitt tag {label(eng, root)}@<version> --alias {at} sets one)")
    return moved[-1]["links"]["target"]


def tags(eng, nid, tag=None):
    """The tags on a node, in the order they were made (foundation.md §C2: a tag points at the unchanged thing)."""
    return [t for t in eng.kids(nid, role="target", kind="tag") if tag is None or t["payload"]["tag"] == tag]


def version_of(eng, nid):
    """Its version (`1.0`), or None: unversioned (no version tag yet). A version is set once (W14)."""
    vs = tags(eng, nid, "version")
    return vs[0]["payload"]["value"] if vs else None


def newest_open_cycle(eng, task):
    cs = [n for n in eng.rec.find("cycle") if eng.task_of(n["id"]) == task and eng.cstate(n["id"]) not in ("CLOSED", "EARLYSTOPPED")]
    if not cs:
        raise Refused(f"task {task_name(eng, task)!r} has no open cycle. next: bitt cycle new {task_name(eng, task)} \"<question>\"")
    return cs[-1]["id"]


def resolve(eng, ref, task=None, kinds=None):
    """(node id, the ref as typed or None) for a hash, a unique ≥8-character prefix, or a name (names.md §3). Inside a task its own
    names are short; another task's are `task/name`; raw is always `raw/name`. With no task (a bare read) a short name resolves when
    exactly one task has it."""
    if not isinstance(ref, str):
        raise Refused(f"record.resolve: {ref!r} is not a reference")
    if ref in eng.rec.nodes:
        return ref, None
    if HEX.fullmatch(ref) and (full := eng.rec.by_prefix(ref)):
        return full, None
    if ref.startswith("@"):
        raise Refused(f"record.resolve: {ref!r}: the @-first form is gone; write `name`, `name@1.0`, `task/name`, `raw/name` "
                      "(docs/v2/names.md)")
    if m := GOAL.fullmatch(ref):
        t = task_by_name(eng, m["task"])
        gs = [n for n in eng.rec.find("goal") if n["links"].get("in") and eng.task_of(n["id"]) == t]
        if not 1 <= int(m["n"]) <= len(gs):
            raise Refused(f"{ref}: task {m['task']!r} has {len(gs)} goal(s) under it")
        return gs[int(m["n"]) - 1]["id"], ref
    if m := CYCLE.fullmatch(ref):
        t = task_by_name(eng, m["task"])
        cs = [n for n in eng.rec.find("cycle") if eng.task_of(n["id"]) == t]
        if not 1 <= int(m["n"]) <= len(cs):
            raise Refused(f"{ref}: task {m['task']!r} has {len(cs)} cycle(s)")
        return cs[int(m["n"]) - 1]["id"], ref
    m = REF.fullmatch(ref)
    if not m and re.search(r"@v\d", ref):
        raise Refused(f"record.resolve: {ref!r}: a version is written with digits only ({re.sub(r'@v(\d)', r'@\1', ref)}), never @v")
    if not m:
        raise Refused(f"record.resolve: {ref!r} is not an id or a name ({NEXT})")
    ns, name, at = m["ns"], m["name"], m["at"]
    if ns in ("raw", "lib"):
        cands = [binding(eng, ns, name)]
    elif ns:
        cands = [binding(eng, task_by_name(eng, ns), name)]
    elif task:                               # the task's own names, then the shelf, then a task name
        cands = [binding(eng, task, name) or binding(eng, "lib", name) or binding(eng, "", name)]
    else:
        cands = [b for b in eng.rec.find("name") if b["payload"]["name"] == name and b["payload"]["ns"] != "raw"]
        if len(cands) > 1:
            opts = [ref_of(eng, b["links"]["target"]) if b["payload"]["ns"] else name for b in cands]
            raise Refused(f"record.resolve: `{name}` is a name in several tasks: write it in full ({', '.join(opts)})")
    b = cands[0] if cands else None
    if not b:
        where = "raw" if ns == "raw" else f"task {ns!r}" if ns else f"task {task_name(eng, task)!r}" if task else "any task"
        hint = " (raw lines are always written raw/<name>)" if not ns and binding(eng, "raw", name) else ""
        raise Refused(f"record.resolve: no name `{name}` in {where}{hint}. next: the names are listed by `bitt module list`, "
                      "`bitt artifact list`, `bitt recipe list` and `bitt data tables`")
    return _pick(eng, b["links"]["target"], at, kinds, task), ref


# ---------------------------------------------------------------- placing a new node on a line (the impls' one entry point)
def place(eng, ns, name, kind, parent=None):
    """The line root a new node of `kind` joins: its parent's line, else the line `name` names in ns, else None (a new line)."""
    if parent and (ns in ("", "raw") or home_of(eng, parent) == ns):  # another task's version starts this task's line
        root = line_of(eng, parent)
        b = bound(eng, root)
        if name and b and b["payload"]["name"] != name:
            raise Refused(f"the parent is on line `{b['payload']['name']}`, not `{name}`: drop the name or the parent")
        return root
    return join(eng, ns, name, kind) if name else None


def line_link(root):
    return {"line": root} if root else {}


def settle(eng, ctx, ns, name, nid, root):
    """After the node is made: a new line with a name gets its name node."""
    if name and not root:
        bind(eng, ctx, ns, name, nid)
