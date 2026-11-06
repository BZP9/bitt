"""The data tool (spec/cards/data.yaml): loaded rows. A file or table snapshot lands in raw.<line> once (distinct rows, keyed by their
values) with the import as a set of its rows in file order (tools/files.py reads the formats)."""
from pathlib import Path

from .. import names, sets, tables
from ..errors import Refused
from ..hashing import norm_value, raw_hash
from ..kernel import Package
from ..walk import Walk
from . import files

CARDS = Path(__file__).resolve().parents[3] / "spec" / "cards"


def infer_type(values):
    vals = [v for v in values if v is not None and v != ""]
    if not vals:
        return "text"
    if all(isinstance(v, bool) for v in vals):
        return "boolean"
    if all(isinstance(v, int) and not isinstance(v, bool) for v in vals):
        return "bigint"
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals):
        return "numeric"
    if all(isinstance(v, (dict, list)) for v in vals):
        return "jsonb"
    return "text"


def propose_map(rows):
    """A load map from the rows: every header becomes a column with an ASCII-safe name and an inferred type (edit it before loading)."""
    headers = []
    for r in rows:
        headers += [k for k in r if k not in headers]
    out = []
    for i, hd in enumerate(headers):
        name = "".join(ch if ch.isascii() and ch.isalnum() else "_" for ch in str(hd).lower()).strip("_")
        while "__" in name:
            name = name.replace("__", "_")
        name = name if name and name[0].isalpha() else f"col_{i + 1}{('_' + name) if name else ''}"
        while name in {c["name"] for c in out}:
            name += "_x"
        out.append({"header": hd, "name": name, "type": infer_type([r.get(hd) for r in rows])})
    return out


def plan_raw(rec, line, rows, columns=None, rename=None):
    """Hash every line before anything is written, so the import node can carry its counts. Returns (plan, stats)."""
    tables.check_name(line)
    cmap = columns or propose_map(rows)
    if rename:
        unknown = [h for h in rename if h not in {str(c["header"]) for c in cmap}]
        if unknown:
            raise Refused(f"data.load: rename names headers the file does not have: {unknown}. next: use the headers as the file spells "
                          f"them: {[str(c['header']) for c in cmap]}")
        cmap = [{**c, "name": rename.get(str(c["header"]), c["name"])} for c in cmap]
    load = [c for c in cmap if not c.get("skip")]
    for c in load:
        tables.check_name(c["name"], "column")
        tables.check_type(c["type"])
    t = f"raw.{line}"
    existing = {r["bitt_row_hash"] for r in rec.table_rows(t)} if rec.spec(t) else set()
    lines, seen, skipped = [], set(), 0
    for i, r in enumerate(rows, start=1):
        values = {}
        for c in load:
            v = r.get(c["header"], None)
            v = None if v == "" else v
            if c.get("true") is not None and v is not None:
                v = (v == c["true"])
            try:
                values[c["name"]] = norm_value(v, c["type"])
            except (ValueError, TypeError, ArithmeticError) as e:
                raise Refused(f"line {i}, column {c['name']!r}: {e}") from None
        if all(v is None for v in values.values()):
            skipped += 1
            continue
        lines.append((i, raw_hash(values), values))
        seen.add(lines[-1][1])
    new = len(seen - existing)
    stats = {"n_rows": len(lines), "new_rows": new, "skipped_empty": skipped,
             "skipped_columns": [c["header"] for c in cmap if c.get("skip")]}
    return {"line": line, "columns": load, "lines": lines}, stats

def load_table(eng, ctx, refs, rows):
    """A raw node for one import: its rows into raw.<line>, its set = the distinct rows in first-seen order."""
    rec = eng.rec
    root = names.join(eng, "raw", ctx["line"], "raw")            # the raw line (names.md §2): its table keeps its first name
    tname = names.born(eng, root) if root else ctx["line"]
    plan, stats = plan_raw(rec, tname, rows, ctx.get("columns"), ctx.get("rename"))
    order, seen = [], set()
    for _, rh, _ in plan["lines"]:
        if rh not in seen:
            seen.add(rh)
            order.append((rh, None))
    if not order:
        raise Refused(f"data.load: the file has no rows with a value ({stats['skipped_empty']} empty lines)")
    sh = sets.set_hash(order)
    rid = eng.make("raw", ctx, refs, **stats, set=sh, table=f"raw.{tname}", _links=names.line_link(root))
    names.settle(eng, ctx, "raw", ctx["line"], rid, root)
    t = f"raw.{tname}"
    cols = [{"name": c["name"], "type": c["type"], "kind": "source", "origin": {"header": str(c["header"])}} for c in plan["columns"]]
    if rec.spec(t) is None:
        rec.make_table("raw", "raw", tname, {}, cols, rid)
    else:
        have = {c["name"]: c for c in rec.spec(t)["columns"]}
        for c in cols:
            if c["name"] not in have:
                rec.add_column(t, c, rid)
            elif have[c["name"]]["type"] != c["type"]:
                raise Refused(f"{t}.{c['name']} is {have[c['name']]['type']}; a column is never retyped (use a new name)")
    for _, rh, values in plan["lines"]:
        rec.insert(t, {"bitt_row_hash": rh, **values})
    sets.write_set(rec, t, order, "import", rid)
    return rid


# ---------------------------------------------------------------- recipes
PY_CHECK = {"text": str, "int": int, "number": (int, float), "bool": bool, "json": (dict, list)}



def i_load(eng, e, ctx, refs):
    raw = ctx["bytes"]
    raw = raw.encode() if isinstance(raw, str) else raw
    if ctx.get("with"):
        return {"raw": load_table(eng, ctx, refs, loader_rows(eng, ctx, raw))}
    fmt = ctx.get("format") or files.guess_format(ctx["origin"]) or "json"
    return {"raw": load_table(eng, ctx, refs, files.read_rows(raw, fmt, ctx.get("sheet")))}


def loader_rows(eng, ctx, raw):
    """A loader module reads the file in a job (never inside bitt): its function gets the bytes and returns the rows."""
    import json
    from .module import code_of, fits
    from .run import job, job_spec
    h_ = eng.node(ctx["with"])["payload"]["header"]
    if h_["kind"] != "load":
        raise Refused(f"data.load: --with takes a loader (a module of kind load), not a {h_['kind']} module")
    params = {**{k: d["default"] for k, d in h_["params"].items() if "default" in d}, **(ctx.get("params") or {})}
    if p := fits(h_["params"], ctx.get("params") or {}, names.label(eng, ctx["with"]) or "the loader"):
        raise Refused(f"data.load: {p}")
    _, d = job(eng, ctx, job_spec(h_), code_of(eng, ctx["with"]), [], params, {}, files={"file": raw})
    rows = [json.loads(x) for x in (d / "output" / "rows.jsonl").read_text().splitlines() if x.strip()]
    if not all(isinstance(r, dict) for r in rows):
        raise Refused("data.load: a loader returns rows (a list of dicts)")
    return rows


def i_exclude(eng, e, ctx, refs):
    have = {m for _, m, _ in Walk(eng).set_rows(eng.node(ctx["set"])["payload"]["set"])}
    rows = [str(r) for r in (ctx["rows"] or [])]
    hits = {r: [m for m in have if m.startswith(r)] for r in rows}
    bad = [r for r, h_ in hits.items() if len(h_) != 1]
    if not rows or bad:
        raise Refused(f"data.exclude: {bad or 'no rows'} {'are not single rows' if bad else ''} of that set (row hashes or ≥8-character prefixes)")
    return {"mark": eng.make("excluded", {**ctx, "rows": sorted(h_[0] for h_ in hits.values())}, refs, _links={"subject": ctx["set"]})}


def package():
    return Package(name="data", impls={"data.load": i_load, "data.exclude": i_exclude})
