"""Postgres Record: the main DB (docs/v2/db.md). Loads the graph and the data tables on open; each commit is one transaction.

The schema is created idempotently: sql/postgres.sql (schemas, the graph, append-only), the bitt.* tables from src/bitt/tables.py, then
sql/postgres_nav.sql (functions, views). Data rows use INSERT … ON CONFLICT DO NOTHING (dedup); triggers refuse UPDATE / DELETE / TRUNCATE.
"""
import datetime
import decimal
import json
from importlib import resources

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from .. import tables
from ..hashing import norm_value
from .memory import MemoryRecord


class PostgresRecord(MemoryRecord):
    def __init__(self, dsn, init=True):
        super().__init__()
        self.dsn = dsn
        self.db = psycopg.connect(dsn, autocommit=False)
        if init:
            with self.db.transaction():
                self.db.execute(resources.files("bitt").joinpath("sql/postgres.sql").read_text())
                for spec in tables.FIXED.values():
                    for stmt in tables.ddl(spec, self._has_vector()):
                        self.db.execute(stmt)
                self.db.execute(resources.files("bitt").joinpath("sql/postgres_nav.sql").read_text())
        self._load()

    def _has_vector(self):
        if not hasattr(self, "_vector"):
            self._vector = bool(self.db.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'").fetchone())
        return self._vector

    # ------------------------------------------------------------------ load
    def _select(self, t):
        spec = self.specs[t]
        names = [c["name"] for c in spec["columns"]]
        q = sql.SQL("SELECT {} FROM {}").format(sql.SQL(", ").join(map(sql.Identifier, names)), sql.Identifier(*tables.split_fq(t)))
        return [{n: self._from_db(v, c["type"]) for n, v, c in zip(names, r, spec["columns"])} for r in self.db.execute(q)]

    @staticmethod
    def _from_db(v, type_):
        if v is None:
            return None
        if type_.startswith("vector"):
            return [float(x) for x in (json.loads(v) if isinstance(v, str) else v)]
        if type_ in ("timestamptz", "date", "numeric") or isinstance(v, (datetime.date, decimal.Decimal)):
            return norm_value(v, type_)
        return v

    def _to_db(self, v, type_):
        if v is None:
            return None
        if type_ == "jsonb":
            return Jsonb(v)
        if type_.startswith("vector"):
            return str(v) if self._has_vector() else v
        return v

    def _load(self):
        cur = self.db.execute("SELECT id, seq, kind, spec_h, task, name, state, payload, links, stamp FROM bitt.node ORDER BY seq")
        for (nid, seq, kind, spec, task, name, state, payload, links, stamp) in cur:
            self._index({"id": nid, "seq": seq, "kind": kind, "payload": payload, "links": links, "stamp": stamp,
                         "spec_h": spec, "task": task, "name": name, "state": state})
            self._journal.append(nid)
        for e, in self.db.execute("SELECT entry FROM bitt.refusal_log ORDER BY seq"):
            self.refusals.append(e)
        for t in tables.FIXED:
            self.data[t] = {tuple(r[c] for c in self.specs[t]["pk"]): r for r in self._select(t)}
        self._rebuild_specs(self.data["bitt.table"].values(), self.data["bitt.column"].values())
        for t, spec in self.specs.items():
            if t not in tables.FIXED:
                self.data[t] = {tuple(r[c] for c in spec["pk"]): r for r in self._select(t)}
        self.db.commit()

    # ------------------------------------------------------------------ persist (one transaction per commit)
    def _persist(self, nodes, ops):
        ctx = self._context_roles()
        base = len(self._journal)
        with self.db.transaction():
            self.db.execute("SET LOCAL bitt.writer = 'kernel'")     # bitt's own write (the no_direct triggers let only these through)
            for i, n in enumerate(nodes):
                n["seq"] = base + i
                self.db.execute("INSERT INTO bitt.node (id, seq, kind, spec_h, task, name, state, payload, links, stamp) "
                                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                                (n["id"], n["seq"], n["kind"], n["spec_h"], n["task"], n["name"], n["state"],
                                 Jsonb(n["payload"]), Jsonb(n["links"]), Jsonb(n["stamp"])))
                rows = []
                for role, v in n["links"].items():
                    if isinstance(v, list):
                        rows += [(n["id"], role, k + 1, p, role not in ctx) for k, p in enumerate(v) if p]
                    elif v:
                        rows.append((n["id"], role, 0, v, role not in ctx))
                if rows:
                    with self.db.cursor() as c:
                        c.executemany("INSERT INTO bitt.link (child, role, ord, parent, lineage) VALUES (%s,%s,%s,%s,%s)", rows)
            for _, op, t, v in ops:
                if op == "ddl":
                    for stmt in tables.ddl(v, self._has_vector()):
                        self.db.execute(stmt)
                elif op == "alter":
                    typ = sql.SQL(v["type"] if v["type"].startswith("vector") and self._has_vector() else
                                  "real[]" if v["type"].startswith("vector") else tables.PG_TYPES[v["type"]])
                    self.db.execute(sql.SQL("ALTER TABLE {} ADD COLUMN {} {}").format(
                        sql.Identifier(*tables.split_fq(t)), sql.Identifier(v["name"]), typ))
                else:
                    _, row = v
                    types = {c["name"]: c["type"] for c in self.spec(t)["columns"]}
                    names = list(row)
                    self.db.execute(sql.SQL("INSERT INTO {} ({}) VALUES ({}) ON CONFLICT DO NOTHING").format(
                        sql.Identifier(*tables.split_fq(t)), sql.SQL(", ").join(map(sql.Identifier, names)),
                        sql.SQL(", ").join([sql.Placeholder()] * len(names))), [self._to_db(row[n], types[n]) for n in names])
            if any(n["kind"] == "name" and n["payload"]["ns"] == "" for n in nodes) or \
                    any(op in ("ddl", "alter") and t.startswith("made.") for _, op, t, _ in ops):
                self.db.execute("SELECT bitt.task_views()")          # a task named, a made table made: its `<task>.<name>` views (A23)

    def _persist_refusal(self, entry):
        with self.db.transaction():
            self.db.execute("SET LOCAL bitt.writer = 'kernel'")
            self.db.execute("INSERT INTO bitt.refusal_log (entry) VALUES (%s)", (Jsonb(entry),))

    def persisted_ids(self):
        ids = {r[0] for r in self.db.execute("SELECT id FROM bitt.node")}
        self.db.commit()
        return ids

    def journal(self):
        ids = [r[0] for r in self.db.execute("SELECT id FROM bitt.node ORDER BY seq")]
        self.db.commit()
        return ids

    def close(self):
        self.db.close()
