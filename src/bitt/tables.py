"""The data tables (docs/v2/db.md): their shapes, the fixed `bitt.*` operation / registry tables, and their DDL.

A table spec is a dict:
  {schema, name, shape, sources: {role: "schema.table"}, columns: [{name, type, kind, origin, null}],
   pk: [col], fks: [([col], "schema.table", [col])], indexes: [[col]], append_only: bool}

Every data table is built from its shape (`shape_spec`), so the `bitt_*` columns, keys, foreign keys and indexes are never hand-written.
The DDL is generated here for Postgres. (The SECURITY DEFINER wrappers that let a non-owner role call it are 1.x, with the roles.)
"""
import re

from .errors import Refused

NAME = re.compile(r"[a-z][a-z0-9]*(_[a-z0-9]+)*")
MAX_NAME = 40
TYPES = ("text", "int", "bigint", "numeric", "boolean", "date", "timestamptz", "jsonb")
DATA_SCHEMAS = ("raw", "made")          # raw imports; made rows: one table per output contract, shared by every task (foundation §D1)
VIEW_SCHEMAS = ()
COLUMN_KINDS = ("source", "output", "parsed", "carried", "free", "bitt")
NODE = "bitt.node"


def check_name(name, what="line"):
    if not isinstance(name, str) or not NAME.fullmatch(name) or len(name) > MAX_NAME:
        raise Refused(f"{what} name {name!r}: use [a-z][a-z0-9]* words joined by single underscores, at most {MAX_NAME} characters "
                      "(`__` is reserved for bitt's suffixes)")


SUFFIX = {"raw": "", "output": "", "src": "__src", "sets": "__sets"}


def _line_of(shape, name):
    """(line, suffix) of a table name: the line is everything before bitt's suffix for that shape."""
    m = re.fullmatch(r"(.*?)(" + SUFFIX.get(shape, "") + ")", name) if SUFFIX.get(shape) else None
    return (m.group(1), m.group(2)) if m else (name, "")


RESERVED_SCHEMAS = ("bitt", "public", "information_schema", "data", "lib") + DATA_SCHEMAS + VIEW_SCHEMAS


def is_task_schema(schema):
    return bool(NAME.fullmatch(schema or "")) and schema not in RESERVED_SCHEMAS and not schema.startswith("pg_")


def ident(s):
    """A task's schema name for the views: lower-case [a-z0-9_]."""
    s = re.sub(r"[^a-z0-9_]+", "_", str(s).lower()).strip("_")
    return s if s and not s[0].isdigit() else f"t_{s}"


def check_type(t):
    if t in TYPES or re.fullmatch(r"vector\(([1-9][0-9]{0,4})\)", str(t)):
        return t
    raise Refused(f"column type {t!r} is not one of {', '.join(TYPES)}, vector(<dim>)")


def col(name, type_, kind="bitt", null=False, origin=None):
    return {"name": name, "type": type_, "kind": kind, "origin": origin or {}, "null": null}


def fq(schema, name):
    return f"{schema}.{name}"


def split_fq(t):
    s, n = t.split(".", 1)
    return s, n


# ---------------------------------------------------------------- the fixed bitt.* tables (docs/v2/db.md)
FIXED = {
    "bitt.table": {"columns": [col("schema", "text"), col("name", "text"), col("kind", "text"), col("node", "text"),
                               col("task", "text", null=True), col("sources", "jsonb"), col("bitt_at", "timestamptz")],
                   "pk": ["schema", "name"], "fks": [(["node"], NODE, ["id"])]},
    "bitt.column": {"columns": [col("schema", "text"), col("tbl", "text"), col("name", "text"), col("type", "text"), col("kind", "text"),
                                col("origin", "jsonb"), col("ord", "int"), col("node", "text"), col("bitt_at", "timestamptz")],
                    "pk": ["schema", "tbl", "name"], "fks": [(["node"], NODE, ["id"]), (["schema", "tbl"], "bitt.table", ["schema", "name"])]},
    # one table per output contract (a module's writes, a prompt's gives): which table holds the rows of that contract
    "bitt.writer": {"columns": [col("contract_hash", "text"), col("tbl", "text"), col("line", "text"), col("node", "text"),
                                col("bitt_at", "timestamptz")],
                    "pk": ["contract_hash"], "uniques": [["tbl"]], "fks": [(["node"], NODE, ["id"])]},
    # one shape for every run (foundation §D1): its recipe's work, its kind, what it read, the units it started from (d15.md), where it ran
    "bitt.run": {"columns": [col("bitt_run_hash", "text"), col("bitt_recipe_hash", "text"), col("kind", "text"), col("task", "text", null=True),
                             col("input", "text", null=True), col("units", "text", null=True), col("rung", "int", null=True),
                             col("n_samples", "int"),
                             col("env", "text", null=True), col("traced", "text", null=True), col("untraced_why", "text", null=True),
                             col("started_at", "timestamptz")],
                 "pk": ["bitt_run_hash"], "fks": [(["bitt_run_hash"], NODE, ["id"])]},
    "bitt.run_end": {"columns": [col("bitt_run_hash", "text"), col("rows_total", "int"), col("made", "int"), col("reused", "int"),
                                 col("failed", "int"), col("outputs_made", "int"), col("calls", "int"), col("status", "text"),
                                 col("finished_at", "timestamptz"), col("out_set", "text", null=True)],
                     "pk": ["bitt_run_hash"], "fks": [(["bitt_run_hash"], "bitt.run", ["bitt_run_hash"])]},
    "bitt.run_error": {"columns": [col("bitt_run_hash", "text"), col("bitt_in_hash", "text"), col("src", "jsonb"), col("error", "text"),
                                   col("seq", "int"), col("bitt_at", "timestamptz")],
                       "pk": ["bitt_run_hash", "seq"], "fks": [(["bitt_run_hash"], "bitt.run", ["bitt_run_hash"])]},
    # a set = an ordered membership over one table (an import, a dataset, an evalset, a run's input / output, a ladder rung)
    "bitt.set": {"columns": [col("bitt_set_hash", "text"), col("tbl", "text"), col("kind", "text"), col("node", "text"), col("n", "int"),
                             col("parent", "text", null=True), col("k", "int", null=True), col("test_hash", "text", null=True),
                             col("bitt_at", "timestamptz")],
                 "pk": ["bitt_set_hash"], "fks": [(["node"], NODE, ["id"]), (["parent"], "bitt.set", ["bitt_set_hash"])]},
}
for _t, _s in FIXED.items():
    _s.update(schema=_t.split(".")[0], name=_t.split(".")[1], shape="fixed", sources={}, append_only=True,
              indexes=_s.get("indexes", []), uniques=_s.get("uniques", []))


# ---------------------------------------------------------------- data table shapes (docs/v2/db.md)
OUTPUT_BITT = [col("bitt_row_hash", "text"), col("bitt_in_hash", "text"), col("bitt_recipe_hash", "text"), col("bitt_run_hash", "text"),
               col("bitt_sample", "int"), col("bitt_part", "int"), col("bitt_parts", "int"),
               col("bitt_parse_error", "text", null=True), col("bitt_elapsed_ms", "int", null=True),
               col("bitt_tokens_in", "int", null=True), col("bitt_tokens_out", "int", null=True),
               col("bitt_extra", "jsonb", null=True),            # what a module returned beyond its declared columns (A11): kept, warned, never bound
               col("bitt_at", "timestamptz")]


def shape_spec(shape, schema, name, sources, data_columns, registry=None):
    """The full spec of a data table of one of the §2 shapes. `sources` = {role: "schema.table"}; `data_columns` = [{name, type, kind, origin}].
    `registry` (fq → spec) resolves the primary keys that foreign keys point at."""
    if schema not in DATA_SCHEMAS:
        raise Refused(f"data tables live in raw (loaded) or made (made by runs), not {schema!r}")
    base, suffix = _line_of(shape, name)
    check_name(base)
    if not re.fullmatch(SUFFIX.get(shape, ""), suffix):
        raise Refused(f"table {name!r}: a {shape} table is <line>{SUFFIX.get(shape) or ''} (`__` is reserved for bitt's suffixes)")
    data = []
    for c in data_columns:
        check_name(c["name"], "column")
        if c["name"].startswith("bitt_"):
            raise Refused(f"column {c['name']!r}: `bitt_*` columns are bitt's")
        if c.get("kind") not in COLUMN_KINDS or c["kind"] == "bitt":
            raise Refused(f"column {c['name']!r}: kind must be one of {COLUMN_KINDS[:-1]}")
        data.append(col(c["name"], check_type(c["type"]), c["kind"], True, c.get("origin")))
    regs = registry or {}

    def pk_of(t):
        if t == NODE:
            return ["id"]
        if t in FIXED:
            return FIXED[t]["pk"]
        if t not in regs:
            raise Refused(f"source table {t} is not registered")
        return regs[t]["pk"]

    if shape == "raw":
        cols, pk, fks = [col("bitt_row_hash", "text")] + data + [col("bitt_at", "timestamptz")], ["bitt_row_hash"], []
    elif shape == "output":
        if schema != "made":
            raise Refused(f"made rows live in `made` (one table per output contract), not {schema!r}")
        cols = list(OUTPUT_BITT[:-1]) + data + [OUTPUT_BITT[-1]]
        pk = ["bitt_row_hash"]
        fks = [(["bitt_run_hash"], "bitt.run", ["bitt_run_hash"])]
    elif shape == "src":                              # v2 lineage: an output row's input → the source rows (one per role)
        targets = set(sources.values())
        cols = [col("bitt_in_hash", "text"), col("role", "text"), col("bitt_src_hash", "text"), col("bitt_at", "timestamptz")]
        pk = ["bitt_in_hash", "role", "bitt_src_hash"]
        (only,) = targets if len(targets) == 1 else (None,)
        fks = [(["bitt_src_hash"], only, pk_of(only))] if only else []   # roles over several tables: the kernel checks (db.md §3)
    elif shape == "sets":                             # v2 memberships over one table (db.md §4)
        (rows,) = sources.values()
        cols = [col("bitt_set_hash", "text"), col("ord", "bigint"), col("bitt_row_hash", "text"), col("split", "text", null=True),
                col("src", "bigint", null=True), col("bitt_at", "timestamptz")]       # src: the input entry a run's entry came from
        pk = ["bitt_set_hash", "ord"]
        fks = [(["bitt_set_hash"], "bitt.set", ["bitt_set_hash"]), (["bitt_row_hash"], rows, pk_of(rows))]
    else:
        raise Refused(f"unknown table shape {shape!r}")
    idx = []
    if shape == "output":
        idx = [["bitt_in_hash", "bitt_recipe_hash"]]
    elif shape == "src":
        idx = [["bitt_src_hash"]]
    elif shape == "sets":
        idx = [["bitt_row_hash"]]
    return {"schema": schema, "name": name, "shape": shape, "sources": dict(sources), "columns": cols, "pk": pk, "fks": fks,
            "uniques": [["bitt_row_hash", "bitt_recipe_hash"]] if shape == "output" else [], "indexes": idx, "append_only": True}


# ---------------------------------------------------------------- DDL
PG_TYPES = {"text": "text", "int": "integer", "bigint": "bigint", "numeric": "numeric", "boolean": "boolean", "date": "date",
            "timestamptz": "timestamptz", "jsonb": "jsonb"}


def ddl(spec, has_vector=True):
    """Postgres CREATE TABLE (+ indexes, append-only triggers) for one spec, as a list of statements."""
    from psycopg import sql
    ident = sql.Identifier(spec["schema"], spec["name"])

    def typ(c):
        if c["type"].startswith("vector"):
            return sql.SQL(c["type"] if has_vector else "real[]")
        return sql.SQL(PG_TYPES[c["type"]])
    parts = [sql.SQL("{} {}{}").format(sql.Identifier(c["name"]), typ(c),
                                       sql.SQL("" if c["null"] else " NOT NULL") +
                                       sql.SQL(" DEFAULT now()" if c["name"] in ("bitt_at", "started_at", "finished_at") else ""))
             for c in spec["columns"]]
    ids = lambda cols: sql.SQL(", ").join(map(sql.Identifier, cols))   # noqa: E731
    parts.append(sql.SQL("PRIMARY KEY ({})").format(ids(spec["pk"])))
    parts += [sql.SQL("UNIQUE ({})").format(ids(u)) for u in spec["uniques"]]
    parts += [sql.SQL("FOREIGN KEY ({}) REFERENCES {} ({})").format(ids(a), sql.Identifier(*split_fq(tt)), ids(b))
              for a, tt, b in spec["fks"]]
    out = [sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(spec["schema"])),
           sql.SQL("CREATE TABLE IF NOT EXISTS {} ({})").format(ident, sql.SQL(", ").join(parts))]
    out += [sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {} ({})").format(
        sql.Identifier(f"{spec['name']}__{'_'.join(i)}"[:63]), ident, ids(i)) for i in spec["indexes"]]
    if spec["append_only"]:
        out += [sql.SQL("DROP TRIGGER IF EXISTS no_change ON {}").format(ident),
                sql.SQL("CREATE TRIGGER no_change BEFORE UPDATE OR DELETE ON {} FOR EACH ROW EXECUTE FUNCTION bitt.refuse_change()").format(ident),
                sql.SQL("DROP TRIGGER IF EXISTS no_truncate ON {}").format(ident),
                sql.SQL("CREATE TRIGGER no_truncate BEFORE TRUNCATE ON {} FOR EACH STATEMENT EXECUTE FUNCTION bitt.refuse_change()").format(ident),
                sql.SQL("DROP TRIGGER IF EXISTS no_direct ON {}").format(ident),     # an INSERT that is not bitt's (sql/postgres.sql)
                sql.SQL("CREATE TRIGGER no_direct BEFORE INSERT ON {} FOR EACH ROW EXECUTE FUNCTION bitt.refuse_direct()").format(ident)]
    return out
