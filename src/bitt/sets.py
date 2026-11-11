"""Storage (foundation §D1): sets and lineage links, over the generic data tables of the record.

  sets        an ordered membership over one table: `<t>__sets` (one row per member, FK to the rows) + a `bitt.set` row. The hash covers the
              members in order with their splits (and, in a run's output set, the input entry each came from), so the same rows in the
              same order = the same set, stored once. A prefix set = the first k members of a parent: a `bitt.set` row with parent + k, no
              member rows (ladder rungs, smoke runs). A run's output set (`run_out`, d15.md §3.1) is aligned with its units: entry i names
              the entry of the run's input it came from (`src`), and may list a row many times (units that read the same values share it).
  links       `<t>__src (bitt_in_hash, role, bitt_src_hash)`: an output's input → its source rows, one per role. `role = set` links a whole
              input set (a table module that did not say which inputs made which row).
Every write goes through the record's insert (registered columns, FKs, append-only); the tables are made the first time they are needed.
"""
from . import tables
from .errors import Refused
from .hashing import canonical, h

KINDS = ("import", "dataset", "evalset", "selection", "run_out")
REPEATS = ("run_out",)                                     # a run's entries follow its units: one row may serve many


def sets_table(rec, t, node, task=None):
    """`<t>__sets` for table `t` (made on first use)."""
    s, n = tables.split_fq(t)
    if rec.spec(t) is None:
        raise Refused(f"no table {t}")
    return rec.make_table("sets", s, f"{n}__sets", {"rows": t}, [], node, task)


def set_hash(members):
    """members = [(row_hash, split)] or [(row_hash, split, src)] in order."""
    return h("set", canonical([list(m) for m in members]))


def write_set(rec, t, members, kind, node, task=None, test_hash=None):
    """A set over table `t` (members = [(row_hash, split or None[, src])] in order). Returns its hash; the same members again = the same
    set. Only a run's output set may list a row twice."""
    if kind not in KINDS:
        raise Refused(f"a set is one of {KINDS}, not {kind!r}")
    if not members:
        raise Refused(f"a set over {t} needs at least one member")
    if kind not in REPEATS and len({m[0] for m in members}) != len(members):
        raise Refused(f"a set over {t} lists a row twice")
    sh = set_hash(members)
    old = rec.get_row("bitt.set", (sh,))
    if old:
        if old["tbl"] != t:
            raise Refused(f"set {sh[:12]} is over {old['tbl']}, not {t}")
        return sh
    st = sets_table(rec, t, node, task)
    rec.insert("bitt.set", {"bitt_set_hash": sh, "tbl": t, "kind": kind, "node": node, "n": len(members), "test_hash": test_hash})
    for i, m in enumerate(members):
        rec.insert(st, {"bitt_set_hash": sh, "ord": i, "bitt_row_hash": m[0], "split": m[1], "src": m[2] if len(m) > 2 else None})
    return sh


def prefix_set(rec, parent, k, node):
    """The first k members of `parent` (k ≥ the parent's size = the parent itself). No member rows are written."""
    p = rec.get_row("bitt.set", (parent,))
    if p is None:
        raise Refused(f"no set {parent[:12]}")
    if not isinstance(k, int) or k < 1:
        raise Refused(f"a prefix set takes k ≥ 1, not {k!r}")
    if k >= p["n"]:
        return parent
    root, offset = parent, k                                 # a prefix of a prefix is a prefix of the root
    while rec.get_row("bitt.set", (root,))["parent"]:
        root = rec.get_row("bitt.set", (root,))["parent"]
    sh = h("prefix", canonical({"parent": root, "k": offset}))
    if rec.get_row("bitt.set", (sh,)) is None:
        r = rec.get_row("bitt.set", (root,))
        rec.insert("bitt.set", {"bitt_set_hash": sh, "tbl": r["tbl"], "kind": r["kind"], "node": node, "n": k, "parent": root, "k": k})
    return sh


def task_rows(eng, task):
    """{table: {row hash}}: the rows a task's runs made or reused (A23: the members of their output sets; `<task>.<name>` views in
    Postgres read the same)."""
    mine = {}
    for r in eng.rec.find("run"):
        if eng.task_of(r["id"]) == task and (e := eng.rec.get_row("bitt.run_end", (r["id"],))) and e["out_set"]:
            t = eng.rec.get_row("bitt.set", (e["out_set"],))["tbl"]
            mine[t] = mine.get(t, set()) | {m for m, _ in members(eng.rec, e["out_set"])}
    return mine


def members(rec, sh):
    """[(row_hash, split)] of a set, in order (a prefix set reads its parent's first k)."""
    return [(r, sp) for r, sp, _ in entries(rec, sh)]


def entries(rec, sh):
    """[(row_hash, split, src)] of a set, in order: src = the entry of the run's input it came from (a run's output set), else None."""
    s = rec.get_row("bitt.set", (sh,))
    if s is None:
        raise Refused(f"no set {sh[:12]}")
    root = s["parent"] or sh
    t = tables.fq(*tables.split_fq(s["tbl"])) + "__sets"
    rows = sorted(rec.table_rows(t, bitt_set_hash=root), key=lambda r: r["ord"])
    return [(r["bitt_row_hash"], r["split"], r.get("src")) for r in rows[: s["k"] or len(rows)]]


def src_table(rec, t, sources, node, task=None):
    """`<t>__src` for output table `t`; `sources` = {role: "schema.table"} (a whole-input-set link uses role `set` → bitt.set)."""
    s, n = tables.split_fq(t)
    return rec.make_table("src", s, f"{n}__src", sources, [], node, task)


def link(rec, t, in_hash, role, src_hash):
    st = f"{t}__src"
    spec = rec.spec(st)
    if spec is None:
        raise Refused(f"no {st}: make it with src_table first")
    target = spec["sources"].get(role)
    if target is None and "." in role and rec.spec(role) is not None and "src" in spec["sources"]:
        target = role                                        # a row output's link names its source table (db.md §3)
    if target is None:
        raise Refused(f"{st}: role {role!r} is not one of {sorted(spec['sources'])}")
    if not spec["fks"]:                                      # roles over several tables: the kernel checks the parent (db.md §3)
        key = (src_hash,)
        if (target == "bitt.set" and rec.get_row("bitt.set", key) is None) or \
                (target != "bitt.set" and rec.get_row(target, key) is None):
            raise Refused(f"{st}: {role} {src_hash[:12]} points at no row of {target}")
    rec.insert(st, {"bitt_in_hash": in_hash, "role": role, "bitt_src_hash": src_hash})


def sources_of(rec, t, in_hash):
    """{role: [source row hashes]} of one input of output table `t`."""
    out = {}
    for r in rec.table_rows(f"{t}__src", bitt_in_hash=in_hash):
        out.setdefault(r["role"], []).append(r["bitt_src_hash"])
    return out

