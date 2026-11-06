"""The walker (docs/v2/walk.md): the one way to walk the record. Read only.

Two graphs and a bridge: the node graph (records and their links, each role of one class: base.yaml `roles`), the row graph (made rows
and the rows they were made from, `<table>__src`) and the bridge (a run, set, dataset, evalset or raw import and its rows, in unit order).
Lineage = every role class but story; story = why / where / judged by. A role no card classifies counts as lineage (lint and
tests/test_walk.py keep every role classified).
"""
from . import cards as lint
from . import sets
from .util import as_list

DATA = ("raw", "selection", "dataset", "evalset")
DATA_PATH = ("units", "reads")                      # the classes a row's data came through (walk.up(x, via=DATA_PATH))
ABOUT = ("subject", "target", "judged")             # story links that point at what they are about


class Nodes:
    """Node ids in walk order (nearest first), with filters."""

    def __init__(self, eng, ids):
        self.eng, self.order = eng, list(dict.fromkeys(ids))

    def __iter__(self):
        return iter(self.order)

    def __contains__(self, nid):
        return nid in self.order

    def __len__(self):
        return len(self.order)

    def ids(self):
        return set(self.order)

    def of(self, *kinds):
        return [x for x in self.order if self.eng.node(x)["kind"] in kinds]

    def runs(self, kind=None):
        """The runs, or those whose module is of `kind` (derive, check, generate, train, pipeline, join)."""
        return [x for x in self.of("run") if kind is None or self.eng.node(x)["payload"].get("kind") == kind]

    def data(self):
        """The dataset and evalset versions."""
        return self.of("dataset", "evalset")

    def raw(self):
        return self.of("raw")

    def models(self):
        """The model artifacts (made by a train run, or added)."""
        return [x for x in self.of("artifact") if self.eng.node(x)["payload"].get("artifact_kind") == "model"]


class Walk:
    def __init__(self, eng, open_run=None):
        """`open_run(run) -> (table, set hash) | None`: how an open run's rows so far are found (the run tool passes a person run's
        answers so far); without it an open run has no rows here."""
        self.eng, self.rec, self._entries, self.open_run = eng, eng.rec, {}, open_run

    # ---------------------------------------------------------------- the node graph
    def _follow(self, nid, story, via=None):
        n = self.eng.node(nid)
        for role, v in n["links"].items():
            if (role in lint.STORY_ROLES) == story and (via is None or lint.role_class(role) in via):
                yield from (x for x in as_list(v) if x)

    def up(self, x, via=None):
        """x and everything it was made from (lineage roles; `via`: only those role classes, e.g. DATA_PATH), nearest first."""
        out, todo = [], [x]
        while todo:
            n = todo.pop(0)
            if n in out:
                continue
            out.append(n)
            todo += [p for p in self._follow(n, story=False, via=via) if p not in out]
        return Nodes(self.eng, out)

    def frontier(self, x):
        """The data x stands on: up its data path (a run's `on` and `read`), the nearest dataset, evalset, selection or raw import on
        each way, never past one. A run over a dataset version stands on that version; one over a raw import stands on the import."""
        out, todo, seen = [], [x], set()
        while todo:
            n = todo.pop(0)
            if n in seen:
                continue
            seen.add(n)
            if self.eng.node(n)["kind"] == "run":
                todo += self.links(n, "on") + self.links(n, "read")
            elif self.eng.node(n)["kind"] in ("dataset", "evalset", "selection", "raw"):
                out.append(n)
        return Nodes(self.eng, out)

    def frontier_of(self, xs):
        return [d for x in xs for d in self.frontier(x)]

    def links(self, x, role):
        """The nodes x links in one role (a run's `recipe`, a set's `run`, a version's `parent`), in order."""
        return [p for p in as_list(self.eng.node(x)["links"].get(role)) if p]

    def down(self, x):
        """x and everything made from it, nearest first."""
        out, todo = [], [x]
        while todo:
            n = todo.pop(0)
            if n in out:
                continue
            out.append(n)
            todo += [k["id"] for k in self.rec.children(n) if k["id"] not in out
                     and any(n in as_list(v) and role not in lint.STORY_ROLES for role, v in k["links"].items())]
        return Nodes(self.eng, out)

    def story(self, x):
        """Why x exists: its cycle and goals, its because and evidence, and what was said about it (decisions, tags, validations,
        checks), nearest first."""
        out, todo = [], [x]
        while todo:
            n = todo.pop(0)
            if n in out:
                continue
            out.append(n)
            todo += [p for p in self._follow(n, story=True) if p not in out]
        about = [k["id"] for k in self.rec.children(x) if any(x in as_list(k["links"].get(r)) for r in ABOUT)]
        return Nodes(self.eng, [*out, *about])

    def inputs(self, run):
        """{on: [refs], read: {role: ref}, recipe, module, artifacts: {role: ref}} of a run: every input, uniformly."""
        n = self.eng.node(run)
        recipe = n["links"].get("recipe")
        r = self.eng.node(recipe) if recipe else None
        return {"on": as_list(n["links"].get("on")), "read": dict(n["payload"].get("read") or {}), "recipe": recipe,
                "module": r["links"]["module"] if r else None, "artifacts": dict((r["payload"].get("artifacts") or {}) if r else {})}

    # ---------------------------------------------------------------- the bridge
    def resolved(self, x):
        """A pipeline run reads as the step it returned."""
        while self.eng.node(x)["kind"] == "run" and self.eng.node(x)["payload"].get("kind") == "pipeline" \
                and self.eng.node(x)["payload"].get("result"):
            x = self.eng.node(x)["payload"]["result"]
        return x

    def entries(self, x):
        """(table, set hash, [(row, split, src)]) of a data node or a run (src: the entry of the run's own input it came from; None: a
        unit); (None, None, []) for a run with no rows yet."""
        x = self.resolved(x)
        if x not in self._entries:
            n = self.eng.node(x)
            if n["kind"] in DATA:
                t, sh = n["payload"]["table"], n["payload"]["set"]
            else:
                e = self.rec.get_row("bitt.run_end", (x,))
                got = (e["out_set"] if e else None) or None
                if got is None and not e and self.open_run:
                    t, sh = self.open_run(x) or (None, None)
                else:
                    sh = got
                    t = self.rec.get_row("bitt.set", (sh,))["tbl"] if sh else None
            self._entries[x] = (t, sh, sets.entries(self.rec, sh) if sh else [])
        return self._entries[x]

    def _table_entries(self, x):
        t, _, es = self.entries(x)
        return t, es

    def chain(self, x, i):
        """[(table, row)] of entry i of x, then the entry of the run's own input it came from, … down to its unit row: nearest first."""
        out = []
        while True:
            x = self.resolved(x)
            t, _, es = self.entries(x)
            row, _, src = es[i]
            out.append((t, row))
            if src is None or self.eng.node(x)["kind"] != "run":
                return out
            x, i = self.links(x, "on")[0], src

    def unit(self, x, i):
        """The unit row of entry i of x."""
        return self.chain(x, i)[-1][1]

    def units_of(self, x):
        """The unit set x's entries belong to: the set itself, or (a run) the units of what it walked; a run whose rows are new units
        (a table derive, an aggregate) is its own unit set."""
        while True:
            x = self.resolved(x)
            _, sh, es = self.entries(x)
            if self.eng.node(x)["kind"] != "run" or not es or es[0][2] is None:
                return sh
            x = self.links(x, "on")[0]

    def set_rows(self, sh, skip_test=False):
        """[(table, row, split)] of a set by its hash, in order (`skip_test`: never its test members)."""
        t = self.rec.get_row("bitt.set", (sh,))["tbl"]
        return [(t, m, sp) for m, sp in sets.members(self.rec, sh) if not (skip_test and sp == "test")]

    def seen(self, artifact):
        """{(table, row)}: the rows an artifact was made from, down to raw. A model a train run made saw that run's input set, its
        train side only (never its test members); an artifact a select made (W4) saw the rows it picked, test side included; an artifact no run made saw nothing bitt knows of."""
        out, p = set(), self.eng.node(artifact)["payload"]
        if p.get("set") and self.links(artifact, "run"):         # made from data (W4): exactly the rows picked, any split
            for t, m, _ in self.set_rows(p["set"]):
                out |= set(self.rows_up(t, m))
            return out
        for run in self.links(artifact, "run"):
            if sh := self.eng.node(run)["payload"].get("input_set"):
                for t, m, _ in self.set_rows(sh, skip_test=True):
                    out |= set(self.rows_up(t, m))
        return out

    def rows(self, x):
        """[(table, row, split, unit row)] of a data node or a run, in entry order."""
        t, es = self._table_entries(x)
        return [(t, m, sp, self.unit(x, i)) for i, (m, sp, _) in enumerate(es)]

    # ---------------------------------------------------------------- the row graph
    def rows_up(self, t, row, through_sets=True):
        """[(table, row)]: the row and every row it was made from, nearest first; a whole-set link (an aggregate's, a table derive's
        without bitt_from) stands for every member of that set (`through_sets=False`: it is not followed, as when a row reads a column
        above it)."""
        out, todo = [], [(t, row)]
        while todo:
            tt, r = todo.pop(0)
            if (tt, r) in out:
                continue
            out.append((tt, r))
            spec = self.rec.spec(tt)
            got = self.rec.get_row(tt, (r,)) if spec and spec["shape"] != "raw" else None
            if not got or "bitt_in_hash" not in got or self.rec.spec(f"{tt}__src") is None:
                continue
            for link in self.rec.table_rows(f"{tt}__src", bitt_in_hash=got["bitt_in_hash"]):
                if link["role"] == "set":
                    if through_sets:
                        st = self.rec.get_row("bitt.set", (link["bitt_src_hash"],))["tbl"]
                        todo += [(st, m) for m, _ in sets.members(self.rec, link["bitt_src_hash"])]
                else:
                    todo.append((link["role"], link["bitt_src_hash"]))
        return out

    def rows_down(self, t, row):
        """[(table, row)]: the row and every row made from it through row links, nearest first. (A whole-set link is followed up
        only, W1: docs/v2/walk.md.)"""
        srcs = [s for s in self.rec.all_specs() if s.endswith("__src")]
        out, todo = [], [(t, row)]
        while todo:
            tt, r = todo.pop(0)
            if (tt, r) in out:
                continue
            out.append((tt, r))
            for s in srcs:
                made = s.removesuffix("__src")
                for link in self.rec.table_rows(s, role=tt, bitt_src_hash=r):
                    todo += [(made, m["bitt_row_hash"]) for m in self.rec.table_rows(made, bitt_in_hash=link["bitt_in_hash"])]
        return out


def up(eng, x):
    return Walk(eng).up(x)
