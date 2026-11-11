"""The Record (kernel-contract §2): append-only nodes, child → parent links, a journal, proposals.

MemoryRecord keeps the graph in memory with a reverse index and a kind index. The SQL backends subclass it: they load the graph on open
and persist each committed proposal in one transaction (the database refuses UPDATE / DELETE by trigger).

Node = {id, seq, kind, payload, links, stamp, spec_h, task, name, state}
  id     = h("node", kind, payload, links, stamp)   stamp = {tool, card, contract, actor, at}   (seq is NOT hashed: it is DB-local)
  spec_h = what the node IS (docs/v2/db.md): kind + payload minus volatile fields + its lineage parents' spec_h
"""
import datetime
import time
from collections import Counter, defaultdict

from .. import tables
from ..errors import Refused
from ..hashing import canonical, h, norm_value, normalize

VOLATILE = {"state", "version", "version_alias", "line", "task", "bump", "bump_reasons", "test_flag", "actor", "why",
            "out", "samples", "sample_rows"}                            # samples: a recipe asks N times, row i of sample j is the same work for any N                                       # not what it *is* (a recipe's table is where it lives, not what it computes)
HISTORY_ROLES = {"parent", "prev"}               # version history, not build input: never part of what a node is
NO_SPEC = {"event", "ruling", "refusal", "flag", "warning", "outcome", "validation", "ack",
           "alias_binding", "vote", "job"}
PER_WRITE_ROLES = {"event", "job", "caller_event"}       # unique per write: never part of what a node *is*


class MemoryRecord:
    def __init__(self):
        self.nodes = {}                      # id -> node, in seq order (includes the open proposal)
        self.proposal = []                   # ids put by the running call; nothing persists before commit
        self.reads = Counter()
        self._journal = []                   # committed ids, in order
        self._kids = defaultdict(list)       # parent id -> [(child id, role)]
        self._by_kind = defaultdict(list)    # kind -> [id]
        self._last_at = 0
        self.kernel = None
        self.refusals = []                   # refusals with no resolvable `in`
        self.specs = {t: s for t, s in tables.FIXED.items()}      # table → spec (the fixed bitt.* tables + every data table)
        self.data = {t: {} for t in self.specs}                   # table → {primary key: row}
        self._ops = []                        # staged writes: (proposal position, "ddl" | "alter" | "insert", table, value)
        self._staged_rows = {}                # table → {primary key: row} of the open proposal

    # ------------------------------------------------------------------ wiring
    def bind(self, kernel):
        self.kernel = kernel

    def _context_roles(self):
        return self.kernel.story_roles if self.kernel else set()

    # ------------------------------------------------------------------ writes (into the proposal)
    def put(self, kind, payload, links, stamp, root=False):
        if not any(links.values()) and not root:
            raise ValueError(f"record.put: {kind} has no parent link")
        at = max(time.time_ns(), self._last_at + 1)
        self._last_at = at
        stamp = {k: v for k, v in stamp.items() if k != "seq"} | {"at": at}
        body = normalize({"kind": kind, "payload": payload, "links": links, "stamp": stamp})
        nid = h("node", canonical(body))
        node = {"id": nid, "seq": len(self.nodes), **body}
        node.update(self._derive(node))
        self._index(node)
        self.proposal.append(nid)
        return nid

    def _derive(self, node):
        """spec_h, task, name, state: computed once at write time, stored for navigation and caching."""
        p, links = node["payload"], node["links"]
        ctx = self._context_roles()
        task = None
        if links.get("in"):
            parent = self.nodes[links["in"]]
            task = parent["task"] or (parent["id"] if parent["kind"] == "goal" else None)
        elif node["kind"] == "goal":
            task = None                       # a root goal is its own task (task_of returns its id)
        spec = None
        if node["kind"] not in NO_SPEC:
            body = {k: v for k, v in p.items() if k not in VOLATILE}
            parents = []
            for role, v in sorted(links.items()):
                if role in ctx or role in PER_WRITE_ROLES or role in HISTORY_ROLES:
                    continue
                for pid in (v if isinstance(v, list) else [v]):
                    if pid:
                        parents.append((role, self.nodes[pid].get("spec_h") or pid))
            spec = h("spec", canonical({"kind": node["kind"], "payload": body, "parents": parents}))
        text = p.get("question") or p.get("problem") or p.get("origin") or p.get("code") or p.get("text") \
            or p.get("target_block") or p.get("impl") or p.get("method") or p.get("win") or p.get("card")
        name = p.get("name") or p.get("alias") or (str(text)[:80] if text else None)   # a display hint; names live in the registry
        return {"spec_h": spec, "task": task, "name": name, "state": p.get("state")}

    def _index(self, node):
        nid = node["id"]
        self.nodes[nid] = node
        self._by_kind[node["kind"]].append(nid)
        for role, v in node["links"].items():
            for pid in (v if isinstance(v, list) else [v]):
                if pid:
                    self._kids[pid].append((nid, role))

    def _unindex(self, nid):
        node = self.nodes.pop(nid)
        self._by_kind[node["kind"]].remove(nid)
        for role, v in node["links"].items():
            for pid in (v if isinstance(v, list) else [v]):
                if pid:
                    self._kids[pid].remove((nid, role))

    # ------------------------------------------------------------------ reads
    def get(self, nid):
        self.reads["get"] += 1
        return self.nodes[nid]

    def parents(self, nid):
        out = []
        for v in self.nodes[nid]["links"].values():
            out += v if isinstance(v, list) else ([v] if v else [])
        return out

    def children(self, nid, role=None, kind=None):
        """The computed reverse index."""
        self.reads["children"] += 1
        seen, out = set(), []
        for cid, r in self._kids.get(nid, ()):
            if (role is None or r == role) and cid not in seen:
                n = self.nodes[cid]
                if kind is None or n["kind"] == kind:
                    seen.add(cid)
                    out.append(n)
        return sorted(out, key=lambda n: n["seq"])

    def find(self, kind=None, **payload):
        self.reads["find:" + (kind or "*")] += 1
        ids = self._by_kind.get(kind, []) if kind else list(self.nodes)
        return [self.nodes[i] for i in ids if all(self.nodes[i]["payload"].get(k) == v for k, v in payload.items())]

    def by_prefix(self, prefix):
        hits = [i for i in self.nodes if i.startswith(prefix)]
        return hits[0] if len(hits) == 1 else None

    def journal(self):
        return list(self._journal)

    def persisted_ids(self):
        """Ids durable in the backing store (memory: the journal)."""
        return set(self._journal)

    def mark(self):
        return len(self.nodes)

    # ------------------------------------------------------------------ commit / drop
    def commit(self):
        """The call passed every check: its proposal becomes record. Append-only; nothing is ever deleted."""
        ops = [op for op in self._ops]
        if self.proposal or ops:
            self._persist([self.nodes[i] for i in self.proposal], ops)
            self._journal += self.proposal
        self._commit_content()
        self.proposal = []

    def _persist(self, nodes, ops):
        pass                                  # memory: nothing to do (SQL backends: one transaction)

    def drop_since(self, mark):
        """Drop the uncommitted proposal entries added since `mark` (a nested sub-proposal; nothing durable is touched)."""
        for nid in reversed(self.proposal[mark:]):
            self._unindex(nid)
        self.proposal = self.proposal[:mark]
        dropped = [op for op in self._ops if op[0] >= mark]
        self._ops = [op for op in self._ops if op[0] < mark]
        for _, op, t, v in reversed(dropped):
            if op == "insert":
                self._staged_rows.get(t, {}).pop(v[0], None)
            elif op == "alter":
                self.specs[t]["columns"] = [c for c in self.specs[t]["columns"] if c["name"] != v["name"]]

    def drop_proposal(self):
        """The call was refused: its proposal was never written, so it is simply not kept (not a rollback)."""
        self.drop_since(0)

    # ------------------------------------------------------------------ data tables (docs/v2/db.md)
    # Table creation and row writes are staged in the proposal with the nodes, and commit (or drop) with them.
    def spec(self, t):
        """The spec of table `t` ("schema.name"), committed or staged in the open proposal; None if there is none."""
        return self.specs.get(t) or self._staged_specs().get(t)

    def all_specs(self):
        return {**self.specs, **self._staged_specs()}

    def make_table(self, shape, schema, name, sources, columns, node, task=None):
        """Create a data table of a §2 shape and register it and every column in bitt.table / bitt.column (one node did it)."""
        t = tables.fq(schema, name)
        old = self.spec(t)
        if old:
            if old["shape"] != shape or old["sources"] != dict(sources):
                raise Refused(f"table {t} exists as a {old['shape']} over {old['sources']}; a line's shape and sources are fixed")
            return t
        spec = tables.shape_spec(shape, schema, name, sources, columns, self.all_specs())
        self._ops.append((len(self.proposal), "ddl", t, spec))
        self.insert("bitt.table", {"schema": schema, "name": name, "kind": shape, "node": node, "task": task, "sources": dict(sources)})
        for i, c in enumerate(spec["columns"]):
            self._register_column(t, c, i, node)
        return t

    def add_column(self, t, c, node):
        """Add one column to a data table (NULL in every older row), or, for kind `carried`, register it for the views only."""
        spec = self.spec(t)
        if spec is None:
            raise Refused(f"no table {t}")
        old = next((x for x in spec["columns"] + spec.get("view_columns", []) if x["name"] == c["name"]), None)
        if old is not None:
            if (old["type"], old["kind"]) != (c["type"], c.get("kind", "free")):
                raise Refused(f"{t}.{c['name']} is a {old['kind']} {old['type']} column; a column is never retyped or re-kinded (use a new name)")
            return t
        new = tables.shape_spec("raw", "raw", "x", {}, [c])["columns"][1]      # validates name, type and kind the same way
        new["origin"] = c.get("origin") or {}
        if new["kind"] == "free" and not new["origin"].get("reason"):
            raise Refused(f"{t}.{c['name']}: a free column needs a reason")
        ordinal = len(spec["columns"]) + len(spec.get("view_columns", []))
        if new["kind"] == "carried":
            spec.setdefault("view_columns", []).append(new)
        else:
            self._ops.append((len(self.proposal), "alter", t, new))
            spec["columns"].append(new)
        self._register_column(t, new, ordinal, node)
        return t

    def _register_column(self, t, c, ordinal, node):
        s, n = tables.split_fq(t)
        self.insert("bitt.column", {"schema": s, "tbl": n, "name": c["name"], "type": c["type"], "kind": c["kind"],
                                    "origin": c.get("origin") or {}, "ord": ordinal, "node": node})

    def insert(self, t, row):
        """Insert one row (INSERT … ON CONFLICT DO NOTHING). Returns (primary key, inserted?). Refuses an unregistered column, a missing
        NOT NULL value, a bad value and a foreign key whose parent does not exist."""
        spec = self.spec(t)
        if spec is None:
            raise Refused(f"no table {t}: tables are made by make_table, never by a write")
        cols = {c["name"]: c for c in spec["columns"]}
        extra = set(row) - set(cols)
        if extra:
            raise Refused(f"{t}: column(s) {sorted(extra)} are not registered (bitt.column): a column comes from the table's spec or its module's header")
        out = {}
        for name, c in cols.items():
            v = row.get(name)
            if v is None and name in ("bitt_at", "started_at", "finished_at"):
                v = self._now()
            try:
                v = norm_value(v, c["type"])
            except (ValueError, TypeError, ArithmeticError) as e:
                raise Refused(f"{t}.{name}: {e}") from None
            if v is None and not c["null"]:
                raise Refused(f"{t}.{name} is required")
            out[name] = v
        pk = tuple(out[c] for c in spec["pk"])
        if self.get_row(t, pk) is not None:
            return pk, False
        for a, target, b in spec["fks"]:
            vals = [out[c] for c in a]
            if any(v is None for v in vals):
                continue
            if not self._exists(target, dict(zip(b, vals))):
                raise Refused(f"{t}: {dict(zip(a, vals))} points at no row of {target}")
        self._ops.append((len(self.proposal), "insert", t, (pk, out)))
        self._staged_rows.setdefault(t, {})[pk] = out
        return pk, True

    def _exists(self, target, eq):
        if target == tables.NODE:
            return eq["id"] in self.nodes
        spec = self.spec(target)
        if spec is None:
            return False
        if set(spec["pk"]) <= set(eq):
            r = self.get_row(target, tuple(eq[c] for c in spec["pk"]))
            return r is not None and all(r[k] == v for k, v in eq.items())
        return any(all(r[k] == v for k, v in eq.items()) for r in self.table_rows(target))

    def get_row(self, t, pk):
        pk = tuple(pk)
        return self.data.get(t, {}).get(pk) or self._staged_rows.get(t, {}).get(pk)

    def table_rows(self, t, **eq):
        """Every row of `t` (committed, then staged), optionally filtered by equality."""
        rows = list(self.data.get(t, {}).values()) + [r for k, r in self._staged_rows.get(t, {}).items() if k not in self.data.get(t, {})]
        return [r for r in rows if all(r.get(k) == v for k, v in eq.items())] if eq else rows

    def _now(self):
        return norm_value(datetime.datetime.now(datetime.timezone.utc), "timestamptz")

    def _rebuild_specs(self, table_rows, column_rows):
        """The data-table specs from the registry rows (on open): every spec is rebuilt from its shape, so the DB never holds a second copy."""
        cols = {}
        for c in sorted(column_rows, key=lambda c: c["ord"]):
            cols.setdefault((c["schema"], c["tbl"]), []).append(c)
        todo = {tables.fq(t["schema"], t["name"]): t for t in table_rows}
        while todo:
            ready = [t for t, r in todo.items() if all(s in self.specs or s in (tables.NODE, "any") for s in r["sources"].values())]
            if not ready:
                raise ValueError(f"bitt: registry has tables whose sources are missing: {sorted(todo)}")
            for t in ready:
                r = todo.pop(t)
                mine = cols.get((r["schema"], r["name"]), [])
                spec = tables.shape_spec(r["kind"], r["schema"], r["name"], r["sources"], [], self.specs)
                shape_cols = {c["name"]: c for c in spec["columns"]}
                spec["columns"] = [shape_cols.get(c["name"]) or tables.col(c["name"], c["type"], c["kind"], True, c["origin"])
                                   for c in mine if c["kind"] != "carried"]             # the registry's order = the order they were added
                spec["view_columns"] = [tables.col(c["name"], c["type"], "carried", True, c["origin"]) for c in mine if c["kind"] == "carried"]
                self.specs[t] = spec
                self.data.setdefault(t, {})

    def _staged_specs(self):
        return {t: v for _, op, t, v in self._ops if op == "ddl"}

    def _commit_content(self):
        for _, op, t, v in self._ops:
            if op == "ddl":
                self.specs[t] = v
                self.data.setdefault(t, {})
            elif op == "alter":
                for row in self.data.get(t, {}).values():
                    row.setdefault(v["name"], None)                    # a new column is NULL in every older row
            elif op == "insert":
                pk, row = v
                self.data.setdefault(t, {}).setdefault(pk, row)        # append-only: an existing key is never overwritten
        ops, self._ops, self._staged_rows = self._ops, [], {}
        return ops

    def log_refusal(self, entry):
        """A refusal with no resolvable upstream can't be a node (it would be an orphan)."""
        self.refusals.append(entry)
        self._persist_refusal(entry)

    def _persist_refusal(self, entry):
        pass
