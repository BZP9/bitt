"""A module's contract, read from its file without running it (foundation.md §B, words.md W13).

A module is a Python file: `BITT = {"kind": …}` and one public function. The function's signature is the contract:

  kind      function                                   reads                writes
  load      fn(data: bytes, *, params) -> list         the file             its rows (raw.<line>)
  derive    fn(col: T, …, *, params) -> T | TypedDict  the positional args  one column named fn, or the TypedDict's fields
  derive    fn(rows: list, *, params) -> list          (scope table)        BITT["writes"] {col: type}, or "selection" (a select:
                                                                            [(row index, split or None)])
  derive    fn(rows: list, chat: list, *, params)      (named inputs: J3)   rows of BITT["writes"]; rows = the units (--on), each
            -> list                                                         later list a --read role; bitt_from [[role, index], …]
  derive    fn(rows: list, *, params) -> TypedDict     (scope table)        one row across the rows: an aggregate (below)
  check     fn(col: T, …, *, params) -> T | TypedDict  the positional args  per-row verdict columns
  check     fn(rows: list, *, params) -> TypedDict     (scope table)        an aggregate: exactly one row of the TypedDict's fields
            (or -> dict with BITT["writes"])                                (a rate with its interval, a mean, a count: d15.md §3.3)
  generate  fn(messages: list, *, params) -> str       a prompt (role)      the prompt's `gives` (a connector: qwen, a person)
  generate  fn(col: T, …, *, params) -> T | TypedDict  the positional args  like a derive, but it calls a model (a trained one)
  train     fn(job, *, params) -> None                 BITT["reads"]        a model (an artifact); BITT["reports"] {name: type}: what
                                                                            job.report(step=…, …) may say (rows of <module>_report)
  pipeline  fn(b, on, *, params) -> run                its steps' runs      nothing of its own (steps: `b.run(...)`)
  join      fn(on, *, key, miss)                       its lookups (`read`)  the picked columns, one row per unit (bitt computes it:
                                                                            docs/v2/inputs.md; the body never runs)
  union     fn(on, *, key)                             --on and --read      every input's rows, deduped by key (default: every
                                                                            column); the columns of --on (bitt computes it: J3)

`does` is the docstring's first line, required. A column read from a table above is written `qa__question` (= `qa.question`).
BITT may also name: `calls` (none / model / env), `roles` ({role: artifact kind}: the artifacts a recipe fills; a generate module's
`prompt` is its main role), `claims` ([idempotent]), `scope` (table), `writes` (a table-scope derive's columns, or "selection"), `reads` (the columns a table-scope
module or a train reads: each bound by a recipe), `reports` (a train's reported numbers).
"""
import ast
import re

KINDS = ("load", "derive", "check", "generate", "train", "pipeline", "join", "union")
CALLS = ("none", "model", "env", "person")
TYPES = ("text", "int", "number", "bool", "json")
PY = {"str": "text", "int": "int", "float": "number", "bool": "bool", "dict": "json", "list": "json", "bytes": "bytes"}
FIELDS = {"kind", "calls", "roles", "claims", "scope", "writes", "fn", "reads", "win", "reports"}
WIN = re.compile(r"(?P<column>[a-z][a-z0-9_]*) (?P<op>>=|>|<=|<) (?P<bar>-?\d+(?:\.\d+)?)")
CLAIMS = ("idempotent",)
MAIN_ROLE = {"generate": "prompt", "train": None}


def parse(code):
    """(header, problem): the contract of a module file. problem None = the header is complete."""
    try:
        tree = ast.parse(code)
    except SyntaxError as x:
        return None, f"the file does not parse: {x.msg} (line {x.lineno})"
    found = [n for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "BITT" for t in n.targets)]
    if not found:
        return None, 'no `BITT = {"kind": …}` header (kinds: ' + ", ".join(KINDS) + ")"
    try:
        b = ast.literal_eval(found[-1].value)
    except ValueError:
        return None, "the BITT header must be a plain literal (no names, calls or expressions)"
    if not isinstance(b, dict) or b.get("kind") not in KINDS:
        return None, f"BITT kind must be one of {list(KINDS)}"
    if extra := set(b) - FIELDS:
        return None, f"BITT names unknown fields {sorted(extra)} (it may name {sorted(FIELDS)})"
    if b.get("calls", "none") not in CALLS:
        return None, f"BITT calls {b['calls']!r} is not one of {list(CALLS)}"
    if any(c not in CLAIMS for c in b.get("claims", [])):
        return None, f"BITT claims are from {list(CLAIMS)}"
    roles = b.get("roles", {})
    if not isinstance(roles, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in roles.items()):
        return None, "BITT roles is {role: artifact kind}"
    fns = [n for n in tree.body if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")]
    if b.get("fn"):
        fns = [n for n in fns if n.name == b["fn"]]
    if len(fns) != 1:
        return None, ("define exactly one public function (or name it: BITT = {…, \"fn\": \"<name>\"})" if fns
                      else "the contract is read from a function: define one (`def words(text: str) -> int`)")
    fn = fns[0]
    doc = ast.get_docstring(tree) or ast.get_docstring(fn)
    does = doc.strip().splitlines()[0].strip() if doc and doc.strip() else None
    typed = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)
             and any(getattr(x, "id", getattr(x, "attr", None)) == "TypedDict" for x in n.bases)}
    try:
        h = _contract(b, fn, typed)
    except ValueError as x:
        return None, str(x)
    connector = b["kind"] == "generate" and h["reads"] == []
    h.update(kind=b["kind"], fn=fn.name, does=does, calls=b.get("calls", "model" if b["kind"] == "generate" else "none"),
             roles={"prompt": "prompt", **roles} if connector else roles, claims=list(b.get("claims", [])))
    if not isinstance(b.get("reads", []), list) or not all(isinstance(x, str) for x in b.get("reads", [])):
        return h, "BITT reads is a list of column names"
    if b.get("reads") and h["scope"] == "row" and b["kind"] != "train":
        return h, "a row module's reads are its function's positional arguments (BITT reads is for table scope and train)"
    if b.get("reports") is not None and b["kind"] != "train":
        return h, "BITT reports is a train's (the numbers its job.report(...) says)"
    if not does:
        return h, "a module says what it does: a docstring whose first line is one sentence"
    if h["kind"] == "check" and h["calls"] != "none":
        return h, "a check calls no model (something that calls a model is a generate)"
    if h["kind"] == "pipeline" and (p := _loops(fn)):
        return h, p
    if b.get("win") is not None:
        if h["kind"] != "pipeline" or not isinstance(b["win"], str) or not WIN.fullmatch(b["win"]):
            return h, ("an eval's win is one rule over a column of the one row its function's run made (an aggregate's): "
                       "\"<column> <op> <number>\" (e.g. \"lo >= 0.7\"), on a pipeline")
        h["win"] = b["win"]
    if h["kind"] == "pipeline":
        h["steps"] = steps(fn)
    return h, None


def _ann(a, what):
    t = PY.get(getattr(a, "id", None) if a is not None else None)
    if t is None:
        raise ValueError(f"{what}: annotate it with one of {', '.join(PY)}")
    return t


def _params(fn):
    a = fn.args
    if a.vararg or a.kwarg:
        raise ValueError(f"{fn.name}: no *args / **kwargs (each column and param is named)")
    out = {}
    for x, d in zip(a.kwonlyargs, a.kw_defaults):
        out[x.arg] = {"type": _ann(x.annotation, f"param {x.arg}"), **({"default": ast.literal_eval(d)} if d is not None else {})}
    return out


def _contract(b, fn, typed):
    kind, pos = b["kind"], fn.args.posonlyargs + fn.args.args
    params = _params(fn)
    breads = list(b.get("reads", [])) if isinstance(b.get("reads", []), list) else []
    if kind == "generate" and [x.arg for x in pos][:1] != ["messages"]:
        kind = "row"                                             # a model that reads columns (a trained classifier): a row contract
    elif kind in ("generate", "train", "pipeline", "load", "join", "union"):
        want = {"generate": ["messages"], "train": ["job"], "pipeline": ["b", "on"], "load": ["data"], "join": ["on"],
                "union": ["on"]}[kind]
        if [x.arg for x in pos] != want:
            raise ValueError(f"a {kind} module's function takes ({', '.join(want)}, *, params…), not ({', '.join(x.arg for x in pos)})")
        writes = {"train": "model", "load": "rows", "join": {}, "union": {}}.get(kind)
        out = {"scope": "row" if kind == "generate" else "table", "reads": breads if kind == "train" else [], "writes": writes,
               "params": params, "returns": "value"}
        if kind == "train":
            out["reports"] = _typed_map(b.get("reports", {}), 'BITT "reports"')
        return out
    lists = bool(pos) and all(getattr(x.annotation, "id", None) == "list" for x in pos)
    named = lists and len(pos) > 1 and pos[0].arg == "rows"      # (rows: list, chat: list): a table derive's named inputs
    table = b.get("scope") == "table" or (lists and len(pos) == 1) or named
    if table:
        if len(pos) != 1 and not (lists and pos[0].arg == "rows"):
            raise ValueError(f"a table-scope {kind} takes (rows: list, *, params…), or named inputs (rows: list, chat: list, *, params…)")
        inputs = [x.arg for x in pos[1:]]                          # the named inputs after the units (docs/v2/inputs.md J3): --read
        r = fn.returns
        if kind == "check" or (isinstance(r, ast.Name) and (r.id in typed or r.id == "dict")):
            if isinstance(r, ast.Name) and r.id in typed:          # an aggregate: one row of what it declares (d15.md §3.3)
                w = {f.target.id: _ann(f.annotation, f"{r.id}.{f.target.id}") for f in typed[r.id].body if isinstance(f, ast.AnnAssign)}
            elif isinstance(r, ast.Name) and r.id == "dict" and isinstance(b.get("writes"), dict):
                w = _typed_map(b["writes"], 'BITT "writes"')
            else:
                raise ValueError(f"a table-scope {kind} across rows writes one row: return a TypedDict (`-> Rate`), or `-> dict` with "
                                 'BITT "writes" {column: type}')
            if not w or any(k.startswith("bitt_") for k in w):
                raise ValueError("an aggregate writes at least one column, and bitt_* names are bitt's")
            if inputs:
                raise ValueError("an aggregate reads one input (rows: list); named inputs are for a table derive")
            return {"scope": "table", "reads": breads, "writes": w, "params": params, "returns": "row"}
        w = b.get("writes")
        if inputs and w == "selection":
            raise ValueError("a select picks rows of one input (rows: list); named inputs are for a table derive")
        if w != "selection" and (not isinstance(w, dict) or not w or any(t not in TYPES for t in w.values())):
            raise ValueError('a table-scope derive names what it writes: BITT "writes" {column: type}, or "selection" (a select)')
        if isinstance(w, dict) and any(k.startswith("bitt_") for k in w):
            raise ValueError("bitt_* names are bitt's: a module may not write them")
        return {"scope": "table", "reads": breads, "writes": w, "params": params, "returns": "rows", **({"inputs": inputs} if inputs else {})}
    reads = {x.arg.replace("__", "."): _ann(x.annotation, f"column {x.arg}") for x in pos}
    if not reads:
        raise ValueError(f"{fn.name} reads no column: its positional arguments are the columns it reads")
    r = fn.returns
    if isinstance(r, ast.Name) and r.id in typed:
        writes = {f.target.id: _ann(f.annotation, f"{r.id}.{f.target.id}") for f in typed[r.id].body if isinstance(f, ast.AnnAssign)}
        returns = "fields"
    else:
        writes, returns = {fn.name: _ann(r, f"what {fn.name} returns")}, "value"
    if any(k.startswith("bitt_") for k in writes):
        raise ValueError("bitt_* names are bitt's: a module may not write them")
    return {"scope": "row", "reads": list(reads), "types": reads, "writes": writes, "params": params, "returns": returns}


def _typed_map(m, what):
    if not isinstance(m, dict) or any(not isinstance(k, str) or t not in TYPES for k, t in m.items()):
        raise ValueError(f"{what} is {{name: type}} with types from {list(TYPES)}")
    return dict(m)


def steps(fn):
    """The names a pipeline's steps write as text: each `b.run("<name>", …, with_="<name>")` (what its recipe pins)."""
    out = []
    for n in ast.walk(fn):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "run":
            vals = n.args[:1] + [k.value for k in n.keywords if k.arg == "with_"]
            out += [v.value for v in vals if isinstance(v, ast.Constant) and isinstance(v.value, str) and v.value not in out]
    return out


def _loops(fn):
    """A pipeline orders steps; it never loops on its own results (foundation.md §K)."""
    for n in ast.walk(fn):
        if isinstance(n, ast.While):
            return "a pipeline has no `while` (a fixed list of steps, each a `b.run(...)`; a loop over a list is a `for`)"
    return None


def contract_of(h):
    """What a new major is judged on: everything but the function's name and its sentence."""
    return {k: v for k, v in (h or {}).items() if k not in ("fn", "does")}
