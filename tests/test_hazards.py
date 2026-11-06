"""The hazard register: every hazard a review, probe or incident found, and every kernel rule no replay reaches, each pinned by a test
that fails without it (conformance/mutate.py `SRC` switches each off; this file must then fail).

Add every new hazard here, in the same commit as its fix: `test_<source>_<id>_<what it guarantees>` (rb4_x1 = read-back 4 finding X1,
rb5_s2_4 = read-back 5 issue S2-4). Ported to the rebuilt tools on 2026-10-30 (the cut became a version tag, the verbs one run)."""
import datetime as _dt
import json
import sys

import pytest
import yaml

from notecard import note_package

from bitt import Failed, Kernel, Package, Refused, names, sets, tables
from bitt.builtins import SHIPPED
from bitt.hashing import canonical, h, in_hash, norm_value, normalize, out_hash, raw_hash, text_hash
from bitt.record.memory import MemoryRecord
from bitt.tools import envs, packages
from bitt.tools.run import land

USR, A = "usr", "agent:t"
SRC = {"path": "mods/x.py", "repo": "x", "commit": "abc123"}
SPLIT = (b'"""Every third question id is test."""\nBITT = {"kind": "derive", "writes": "selection", "reads": ["qid"]}\n\n\n'
         b'def split(rows: list) -> list:\n    return [(i, "test" if int(r["qid"][1:]) % 3 == 0 else "train") for i, r in enumerate(rows)]\n')
UPPER = b'"""Upper-case a question."""\nBITT = {"kind": "derive"}\n\n\ndef upper(q: str) -> str:\n    return q.upper()\n'
NOT_THREE = b'"""Is the smoke run kept?"""\nBITT = {"kind": "check"}\n\n\ndef smoke_kept(skip_smoke: str = "") -> bool:\n    return skip_smoke != "yes"\n'


@pytest.fixture(autouse=True)
def blobs(tmp_path, monkeypatch):
    monkeypatch.setenv("BITT_BLOBS", str(tmp_path / "blobs"))


def kernel(rec, extra=()):
    k = Kernel(rec, packages=[*packages(), note_package(), *extra])

    def c(card, actor=A, **a):
        return k.call(card, {{"in_": "in", "as_": "as"}.get(x, x): v for x, v in a.items()}, actor)
    return k, c


def rows(n, start=0):
    return [{"qid": f"Q{i}", "q": f"question {i}"} for i in range(start, start + n)]


def load(c, n=5, line="qs", **a):
    return c("data.load", bytes=json.dumps(rows(n)), origin=f"file:{line}.json", sensitivity="internal", does="synthetic rows for a test", line=line, **a)["raw"]


def module(k, c, cyc, name, code, **a):
    """`name` on the shelf (once), then a recipe of it in `cyc`."""
    if not names.binding(k, "lib", name):
        c("module.define", in_=cyc, code=code, name=name, source=SRC)
    return c("recipe.make", in_=cyc, module=name, **a)["recipe"]


def split_recipe(k, c, cyc):
    return module(k, c, cyc, "split", SPLIT, cols={"qid": "qid"})


def data_cycle(k, c, goal, name, approve_by=USR):
    """A working data cycle in JUDGE: one dataset made and approved, a conclusion, ready to tag."""
    w = c("control.cycle.open", in_=goal, question=f"build {name}", level="working", because=[goal])["cycle"]
    sk = c("control.want", in_=w, want_kind="dataset", name=name, contract={})["want"]
    c("control.plan", USR, in_=w, arms=[sk], win="tag it", judged_by="person")
    raw = load(c, line=f"{name}_rows")
    d = c("run.go", in_=w, recipe=split_recipe(k, c, w), on=[raw], as_="dataset", fills=sk)["set"]
    v = c("control.validate", approve_by, in_=w, subject=d, verdict="approve")["validation"]
    f = c("control.log.finding", in_=w, text="ok", evidence=[v], finding_kind="conclusion")["finding"]
    return w, d, f


def version(c, w, d, f, actor=A):
    return c("tag.make", actor, in_=w, target=d, tag="version", because=[f])


def working(c, t, want_kind="dataset", name="qa", actor=USR, contract=None):
    w = c("control.cycle.open", in_=t, question="build", level="working", because=[t])["cycle"]
    sk = c("control.want", in_=w, want_kind=want_kind, name=name, contract=contract or {})["want"]
    plan = c("control.plan", actor, in_=w, arms=[sk], win="a person approves it", judged_by="person")["plan"]
    return w, sk, plan


# ---------------------------------------------------------------- read-back 4: approvals, judgments, names
def test_rb4_x1_x3_approval_is_judged_in_the_tagging_task(opener):
    k, c = kernel(opener())
    both = [USR, "usr:bob"]                                    # same people in both tasks: only the task filter can tell them apart
    ta = c("control.goal.open_root", USR, problem="A", name="ta", authority=both)["goal"]
    tb = c("control.goal.open_root", "usr:bob", problem="B", name="tb", authority=both)["goal"]
    wa, da, fa = data_cycle(k, c, ta, "shared")
    wb = c("control.cycle.open", in_=tb, question="adopt A's dataset", level="working", because=[tb])["cycle"]
    c("control.plan", USR, in_=wb, arms=[da], win="tag it here", judged_by="person")
    vb = c("control.validate", "usr:bob", in_=wb, subject=da, verdict="pass")["validation"]
    fb = c("control.log.finding", in_=wb, text="ok", evidence=[vb], finding_kind="conclusion")["finding"]
    with pytest.raises(Refused, match="control.approval"):
        version(c, wb, da, fb)                                 # X1: A's approval does not open B's gate
    c("control.validate", "usr:bob", in_=wb, subject=da, verdict="reject")
    assert version(c, wa, da, fa)["bump"] == "major", "X3: B's reject does not close A's gate"


def test_rb4_x1_an_approver_needs_authority_where_the_validation_is_written(opener):
    k, c = kernel(opener())
    ta = c("control.goal.open_root", USR, problem="A", name="ta")["goal"]
    tb = c("control.goal.open_root", "usr:bob", problem="B", name="tb")["goal"]
    _, da, _ = data_cycle(k, c, ta, "shared")
    wb = c("control.cycle.open", in_=tb, question="adopt", level="working", because=[tb])["cycle"]
    c("control.plan", "usr:bob", in_=wb, arms=[da], win="x", judged_by="person")
    assert c("control.validate", "usr:bob", in_=wb, subject=da, verdict="approve")["validation"], "bob has authority in B"
    with pytest.raises(Refused, match="can_approve"):
        c("control.validate", "usr:bob", in_=ta, subject=da, verdict="approve")


def test_rb4_x1_a_later_reject_revokes_an_approval(opener):
    k, c = kernel(opener())
    t = c("control.goal.open_root", USR, problem="x", name="t")["goal"]
    w, d, f = data_cycle(k, c, t, "qa")
    x = c("control.cycle.open", in_=t, question="x", level="explore", because=[t])["cycle"]
    c("control.validate", USR, in_=x, subject=d, verdict="reject")
    with pytest.raises(Refused, match="control.approval"):                 # the gate reads the latest approve / reject in the task
        version(c, x, d, f)


def test_rb4_x2_a_version_is_set_once(opener):
    k, c = kernel(opener())
    t = c("control.goal.open_root", USR, problem="x", name="t")["goal"]
    w, d, f = data_cycle(k, c, t, "twice")
    version(c, w, d, f)
    with pytest.raises(Refused, match="tag.once"):
        version(c, w, d, f)


def test_rb4_x4_judgments_and_acks_in_another_task_do_not_count_here(opener):
    rec = opener()
    k, c = kernel(rec)
    both = [USR, "usr:bob"]
    ta = c("control.goal.open_root", USR, problem="A", name="ta", authority=both)["goal"]
    tb = c("control.goal.open_root", "usr:bob", problem="B", name="tb", authority=both)["goal"]
    wa, sk, _ = working(c, ta)
    d = c("run.go", in_=wa, recipe=split_recipe(k, c, wa), on=[load(c)], as_="dataset", fills=sk)["set"]
    wb = c("control.cycle.open", in_=tb, question="adopt", level="working", because=[tb])["cycle"]
    c("control.plan", USR, in_=wb, arms=[d], win="x", judged_by="person")
    c("control.validate", "usr:bob", in_=wb, subject=d, verdict="approve")
    assert k.arm_state(sk, k.latest_plan(wa)) == "filled", "a validation written in B does not measure A's arm"
    c("control.validate", USR, in_=wa, subject=d, verdict="approve")
    assert k.arm_state(sk, k.latest_plan(wa)) == "measured", "A's own does"
    ev = rec.nodes[d]["links"]["event"]
    stamp = {"tool": "control", "card": "control.ack", "contract": "2.0", "actor": USR}
    rec.put("ack", {"rule": "run.leak"}, {"in": wb, "subject": d, "event": ev}, stamp)
    rec.commit()
    assert not k._acked(d, "run.leak", task=ta), "an ack written in B does not count in A"
    rec.put("ack", {"rule": "run.leak"}, {"in": wa, "subject": d, "event": ev}, stamp)
    rec.commit()
    assert k._acked(d, "run.leak", task=ta), "A's own ack does"


def test_rb4_y5_x7_names(opener):
    k, c = kernel(opener())
    t = c("control.goal.open_root", USR, problem="x", name="t")["goal"]
    with pytest.raises(Refused, match="is not a name"):
        c("control.goal.open_root", USR, problem="y", name="y'; DROP TABLE x; --")
    w = c("control.cycle.open", in_=t, question="q", level="working", because=[t])["cycle"]
    with pytest.raises(Refused, match="does not match"):
        c("control.want", in_=w, want_kind="dataset", name="TB/data", contract={})
    c("control.want", in_=w, want_kind="dataset", name="future", contract={})
    w2, d, f = data_cycle(k, c, t, "other")
    version(c, w2, d, f)
    with pytest.raises(Refused, match="an alias is a name"):
        c("tag.make", USR, in_=w2, target=d, tag="alias", value="9")       # an alias is never a version
    c("tag.make", USR, in_=w2, target=d, tag="alias", value="future")      # a want's name is no clash: aliases sit after @


def test_rb4_d2_unstorable_values_are_refused_and_the_kernel_stays_usable(opener):
    rec = opener()
    k, c = kernel(rec)
    t = c("control.goal.open_root", USR, problem="x", name="t")["goal"]
    for bad in ("nul\x00here", float("nan")):
        with pytest.raises(Failed, match="NUL|NaN"):
            c("control.test_note", USR, in_=t, text=bad)
        assert not rec.proposal and k.depth == 0
    n = len(rec.journal())
    c("control.test_note", USR, in_=t, text="fine", because=None)
    assert len(rec.journal()) == n + 2


def node_id(n):
    return h("node", canonical({"kind": n["kind"], "payload": n["payload"], "links": n["links"], "stamp": n["stamp"]}))


def test_rb4_numbers_round_trip_and_ids_re_verify(opener):
    rec = opener()
    k, c = kernel(rec)
    t = c("control.goal.open_root", USR, problem="x", name="t")["goal"]
    g = c("control.goal.open", USR, in_=t, problem="big numbers", contract={"x": 1e16, "y": 2.0, "z": 0.5})["goal"]
    if opener.kind == "memory":
        return
    rec.close()
    again = opener(same=True)
    assert node_id(again.nodes[g]) == g, "integral floats are stored as ints everywhere, so the id re-verifies"


def small_world(k, c):
    """A load, a derive (made.upper + __src + __sets) and a dataset: two recipes, three runs' tables."""
    t = c("control.goal.open_root", USR, problem="x", name="t")["goal"]
    x = c("control.cycle.open", in_=t, question="x", level="explore", because=[t])["cycle"]
    raw = load(c, n=3, line="rows")
    run = c("run.go", in_=x, recipe=module(k, c, x, "upper", UPPER, cols={"q": "q"}), on=[raw], full="yes")["run"]
    c("run.go", in_=x, recipe=split_recipe(k, c, x), on=[raw], as_="dataset", line="qa")
    return t, x, raw, run


def test_rb4_d1_append_only_at_the_sql_level(opener):
    rec = opener()
    k, c = kernel(rec)
    small_world(k, c)
    if opener.kind == "postgres":
        import psycopg
        for sql in ("TRUNCATE raw.rows CASCADE", "TRUNCATE made.upper CASCADE", "TRUNCATE bitt.run CASCADE",
                    "TRUNCATE bitt.refusal_log", "TRUNCATE bitt.node CASCADE"):
            with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
                rec.db.execute(sql)
            rec.db.rollback()


def test_rb4_y1_to_y4_the_kernel_enforces_plugin_rules():
    k, c = kernel(None)
    t = c("control.goal.open_root", USR, problem="x", name="t")["goal"]
    seen = {}

    def nests_as_usr(eng, e, ctx, refs):          # Y1: an impl run for an agent tries to act as usr
        out = eng.call("exec.job.submit", {"caller_event": ctx["_event"], "needs": {}}, actor="usr", caller=None)
        seen["actor"] = eng.node(out["job"])["stamp"]["actor"]
        return {"note": eng.make("note", ctx, refs)}
    k.impls["control.test_note"] = nests_as_usr
    k.eff["control.test_note"]["calls"] = ["exec.job.submit"]
    c("control.test_note", in_=t, text="x")
    assert seen["actor"] == A, "a nested call carries the caller's actor, whatever the impl passes"

    def bad_links(eng, e, ctx, refs):              # Y3
        return {"note": eng.make("note", ctx, refs, _links={"in": t})}
    k.impls["control.test_note"] = bad_links
    with pytest.raises(Failed, match="impl roles"):
        c("control.test_note", in_=t, text="x")

    def old_output(eng, e, ctx, refs):             # Y4
        return {"note": t}
    k.impls["control.test_note"] = old_output
    with pytest.raises(Failed, match="not a node this call created"):
        c("control.test_note", in_=t, text="x")

    def against_dag(eng, e, ctx, refs):            # Y2: data → control is against the DAG, even with caller=None
        eng.call("control.test_note", {"in": t, "text": "x"}, actor="usr", caller=None)
        return {"raw": eng.make("raw", ctx, refs)}
    k.impls["data.load"] = against_dag
    k.eff["data.load"]["calls"] = ["control.test_note"]
    n = len(k.rec.journal())
    with pytest.raises(Failed, match="against the DAG"):
        c("data.load", **LOAD_ARGS)
    new = [k.rec.nodes[x]["kind"] for x in k.rec.journal()[n:]]
    assert k.depth == 0 and new == [] and not k.rec.proposal, "the nested note is not recorded"
    assert "against the DAG" in k.rec.refusals[-1]["reason"], "the refusal is (in the log: data.load has no `in`)"


LOAD_ARGS = {"bytes": "[]", "origin": "f", "sensitivity": "public", "line": "x", "does": "a test"}


def train_world(k, c, want="artifact", contract=None):
    """A dataset, a working cycle whose plan wants a model, a train recipe (nb_train) and its eval."""
    t = c("control.goal.open_root", USR, problem="x", name="t")["goal"]
    x = c("control.cycle.open", in_=t, question="data", level="explore", because=[t])["cycle"]
    raw = c("data.load", bytes=json.dumps([{"qid": f"Q{i}", "q": f"word{i % 2} text", "y": f"y{i % 2}"} for i in range(6)]),
            origin="file:q.json", sensitivity="internal", does="synthetic rows for a test", line="qs")["raw"]
    ds = c("run.go", in_=x, recipe=split_recipe(k, c, x), on=[raw], as_="dataset", line="qa")["set"]
    w, sk, _ = working(c, t, want_kind=want, name="m", contract=contract)
    for n in ("nb_train", "nb_predict", "exact_match"):
        if not names.binding(k, "lib", n):
            c("module.define", in_=w, code=SHIPPED[n].read_bytes(), name=n)
    tr = c("recipe.make", in_=w, module="nb_train", cols={"text": "q", "label": "y"})["recipe"]
    ev = c("recipe.make", in_=w, module="exact_match", cols={"a": "pred", "b": "qs.y"})["recipe"]
    go = lambda: c("run.go", in_=w, recipe=tr, on=[ds], fills=sk, evals=[ev], endpoint="nb_predict")  # noqa: E731
    return t, w, sk, go


def test_rb4_y6_a_broken_finish_handler_fails_the_job():
    k, c = kernel(None)
    t, w, sk, go = train_world(k, c)
    land(k, go()["job"])                                          # the smoke run
    job = go()["job"]
    k.finish["run.go"] = lambda *a: 1 / 0
    land(k, job)
    assert k.job_status(job) == "failed" and k.arm_state(sk, k.latest_plan(w)) == "failed"


def test_rb4_y6_a_refused_landing_rejects_the_job_and_fails_its_arm():
    k, c = kernel(None)
    t, w, sk, go = train_world(k, c, contract={"must_link": ["rubric"]})   # the model it lands links no `rubric`: its fill is refused
    land(k, go()["job"])
    job = go()["job"]
    land(k, job)
    assert k.job_status(job) == "rejected" and k.arm_state(sk, k.latest_plan(w)) == "failed"


def test_kernel_a_running_job_holds_its_arm_and_a_job_finishes_once():
    k, c = kernel(None)
    t, w, sk, go = train_world(k, c)
    smoke = go()["job"]
    assert k.arm_state(sk, k.latest_plan(w)) == "running", "more is landing: not judged until every job is in"
    land(k, smoke)
    assert k.job_status(smoke) == "done"
    with pytest.raises(Refused, match="already finished"):
        k.call("exec.job.finish", {"job": smoke, "outputs": []}, "system")


def test_rb4_x8_a_caught_nested_refusal_is_not_committed():
    k, c = kernel(None)
    t = c("control.goal.open_root", USR, problem="x", name="t")["goal"]
    ran = []

    def stages_then_refuses(eng, e, ctx, refs):
        ran.append(eng.make("raw", ctx, refs))
        raise Refused("the nested call changed its mind")

    def catches(eng, e, ctx, refs):
        try:
            eng.call("data.load", LOAD_ARGS, actor=A)
        except Refused:
            pass
        return {"note": eng.make("note", ctx, refs)}
    k.impls["data.load"] = stages_then_refuses
    k.impls["control.test_note"] = catches
    k.eff["control.test_note"]["calls"] = ["data.load"]
    c("control.test_note", in_=t, text="x")
    assert ran, "the nested call ran (staged a node) and refused"
    assert not k.rec.find("raw"), "the outer call succeeded; the nested call's staged node did not come with it"
    assert k.rec.find("note")


# ---------------------------------------------------------------- read-back 5 (storage)
def test_rb5_s1_1_a_table_name_is_a_checked_line_plus_bitts_suffix(opener):
    with pytest.raises(Refused, match="line name"):
        tables.shape_spec("raw", "raw", "qa__x", {}, [])
    with pytest.raises(Refused, match="line name"):
        tables.shape_spec("raw", "raw", "q" * 41, {}, [])
    with pytest.raises(Refused, match="a sets table is <line>__sets"):
        tables.shape_spec("sets", "raw", "qa", {"rows": "raw.qa"}, [], {"raw.qa": {"pk": ["bitt_row_hash"]}})
    k, c = kernel(opener())
    c("control.goal.open_root", USR, problem="x", name="t")
    with pytest.raises(Refused, match="at most 40"):       # Postgres would cut it to 63 bytes and two lines would share a table
        c("data.load", bytes=json.dumps(rows(2)), origin="f", sensitivity="public", does="synthetic rows for a test", line="a" * 70)


def test_rb5_s2_3_big_numbers_and_column_ranges(opener):
    assert normalize(1e22) == 10 ** 22 and isinstance(normalize(1.5e300), int)
    rec = opener()
    k, c = kernel(rec)
    t = c("control.goal.open_root", USR, problem="x", name="t")["goal"]
    rec.put("finding", {"text": "t", "big": 1e22, "huge": 1.5e300}, {"in": t}, {"actor": A, "contract": "2.0"})
    rec.commit()
    if opener.kind != "memory":
        rec.close()
        again = opener(same=True)
        assert all(node_id(n) == n["id"] for n in again.nodes.values()), "every id re-verifies after a round trip"
    for v, ty in ((2 ** 31, "int"), (-2 ** 31 - 1, "int"), (2 ** 63, "bigint"), ([1.0, 2.0], "vector(3)"),
                  ("2026-01-01T00:00:00.1234567+00:00", "timestamptz"), (_dt.datetime(2026, 1, 1, 5), "date")):
        with pytest.raises(ValueError):
            norm_value(v, ty)
    assert norm_value(2 ** 31 - 1, "int") == 2 ** 31 - 1 and norm_value(2 ** 40, "bigint") == 2 ** 40


def test_rb5_s2_4_a_column_is_declared_once_by_whoever_owns_it(opener):
    rec = opener()
    k, c = kernel(rec)
    t, x, raw, run = small_world(k, c)
    for spec, expect in [({"name": "q", "type": "bigint", "kind": "source"}, "never retyped"),
                         ({"name": "q", "type": "text", "kind": "free", "origin": {"reason": "r"}}, "never retyped or re-kinded"),
                         ({"name": "y", "type": "text", "kind": "free"}, "needs a reason"),
                         ({"name": "y", "type": "varchar", "kind": "source"}, "column type")]:
        with pytest.raises(Refused, match=expect):
            rec.add_column("raw.rows", spec, raw)
        rec.drop_proposal()
    with pytest.raises(Refused, match="never retyped"):     # a later import whose column changed type is refused, not retyped
        c("data.load", bytes=json.dumps([{"qid": "Q9", "q": 8}]), origin="f2", sensitivity="internal", does="synthetic rows for a test", line="rows")


def test_rb5_s2_6_labels_never_change_what_rows_are(opener):
    """The same rows from another file or sensitivity are the same rows and the same set (content identity); the import nodes differ,
    so a check on an import's labels (run.sensitivity) is never served from another import's cached verdict."""
    rec = opener()
    k, c = kernel(rec)
    c("control.goal.open_root", USR, problem="x", name="t")
    a = c("data.load", bytes=json.dumps(rows(3)), origin="file:a.json", sensitivity="internal", does="synthetic rows for a test", line="qs")["raw"]
    b = c("data.load", bytes=json.dumps(rows(3)), origin="file:b.json", sensitivity="company", does="synthetic rows for a test", line="qs")["raw"]
    assert rec.nodes[a]["payload"]["set"] == rec.nodes[b]["payload"]["set"] and len(rec.table_rows("raw.qs")) == 3
    assert rec.nodes[a]["spec_h"] != rec.nodes[b]["spec_h"], "another sensitivity is another import (its checks are its own)"


@pytest.mark.parametrize("name, expect", [("pg_stats", "Postgres"), ("raw", "reserved"), ("data", "reserved"), ("made", "reserved"),
                                          ("bitt", "reserved"), ("Bitt", "is not a name"), ("my_task", "taken")])
def test_rb5_s2_8_a_task_name_gets_a_view_schema_of_its_own(opener, name, expect):
    k, c = kernel(opener())
    c("control.goal.open_root", USR, problem="x", name="my_task")
    with pytest.raises(Refused, match=expect):
        c("control.goal.open_root", USR, problem="y", name=name)


def test_rb5_s2_9_a_store_that_refuses_the_refusal_too_still_raises_failed():
    rec = MemoryRecord()
    k, c = kernel(rec)
    t = c("control.goal.open_root", USR, problem="x", name="t")["goal"]
    real = rec._persist

    def down(*a):
        raise ConnectionError("the database went away")
    rec._persist = down
    with pytest.raises(Failed, match="refused the commit"):
        c("control.test_note", USR, in_=t, text="lost")
    assert rec.refusals and rec.refusals[-1].get("unrecorded"), "the refusal is kept in memory, marked unrecorded"
    rec._persist = real
    c("control.test_note", USR, in_=t, text="the kernel is usable")


def test_rb5_s2_12_table_shapes_and_keys(opener):
    rec = opener()
    k, c = kernel(rec)
    t, x, raw, run = small_world(k, c)
    with pytest.raises(Refused, match="points at no row"):                 # a set member must be a row of its table
        rec.insert("raw.rows__sets", {"bitt_set_hash": rec.nodes[raw]["payload"]["set"], "ord": 99, "bitt_row_hash": "f" * 64})
    rec.drop_proposal()
    o = rec.table_rows("made.upper")[0]
    with pytest.raises(Refused, match="points at no row"):                 # a made row names a run that exists
        rec.insert("made.upper", dict({k_: v for k_, v in o.items() if k_ != "bitt_at"}, bitt_row_hash="a" * 64, bitt_run_hash="b" * 64))
    rec.drop_proposal()


def test_rb5_s2_12_samples_and_parts_are_in_the_key():
    assert len({out_hash("r", "i", s, p) for s in range(2) for p in range(2)}) == 4, "each sample and part is its own output row"


def test_rb5_s2_12_canonical_values():
    assert raw_hash({"a": 1, "b": None}) == raw_hash({"a": 1}), "a NULL column is no key: adding an empty column changes no row"
    assert in_hash({"src": {"a": 1, "b": None}}) == in_hash({"src": {"a": 1}})
    assert norm_value("é\r\n") == "é\n", "text is NFC with \\n line ends"
    assert raw_hash({"q": norm_value("Café")}) == raw_hash({"q": norm_value("Café")})


def test_rb5_s3_small_things(opener):
    from backend import _same_server
    assert _same_server("postgresql://a@localhost:5432/x", "postgresql://b@127.0.0.1/y")
    assert not _same_server("postgresql://a@localhost:55432/x", "postgresql://b@127.0.0.1/y")
    rec = opener()
    k, c = kernel(rec)
    t = c("control.goal.open_root", USR, problem="x", name="t")["goal"]      # exactly one run: a pattern would match it
    x = c("control.cycle.open", in_=t, question="x", level="explore", because=[t])["cycle"]
    c("run.go", in_=x, recipe=split_recipe(k, c, x), on=[load(c, n=2, line="rows")], as_="dataset", line="qa")
    assert len(rec.table_rows("bitt.run")) == 1
    if opener.kind == "postgres":
        with rec.db.cursor() as cur:
            cur.execute("SELECT bitt.run('%%%%%%%%'), bitt.run('________'), bitt.id('%%%%%%%%')")
            assert cur.fetchone() == (None, None, None), "a prefix is a prefix, never a LIKE pattern"
        rec.db.commit()


# ---------------------------------------------------------------- the kernel's inputs
def test_data1_a_file_input_is_stored_as_the_hash_of_its_bytes(opener):
    """A `type: bytes` input given as a file's bytes is hashed as those bytes, not as their Python repr."""
    rec = opener()
    k, c = kernel(rec)
    c("control.goal.open_root", USR, problem="x", name="t")
    blob = json.dumps([{"q": "café ☃"}]).encode()
    raw = c("data.load", bytes=blob, origin="file:w.json", sensitivity="public", does="synthetic rows for a test", line="qs")["raw"]
    assert rec.nodes[raw]["payload"]["bytes"] == {"bytes_h": text_hash(blob), "n": len(blob)}


# ---------------------------------------------------------------- independence (bitt depends on no other tool, 2026-10-21)
def test_indep1_tests_only_touch_a_throwaway_cluster(monkeypatch):
    """The guard is bitt's own rule (no other tool's env vars): a local Postgres on a non-default port, not in $BITT_PROTECTED_DSNS."""
    from backend import throwaway_problem
    monkeypatch.delenv("BITT_PROTECTED_DSNS", raising=False)
    assert throwaway_problem("postgresql://bitt@localhost:55432/postgres") is None
    assert "5432" in throwaway_problem("postgresql://me@localhost/postgres")
    assert "not this machine" in throwaway_problem("postgresql://me@db.example:55432/x")
    monkeypatch.setenv("BITT_PROTECTED_DSNS", "postgresql://x@127.0.0.1:55432/live")
    assert "BITT_PROTECTED_DSNS" in throwaway_problem("postgresql://bitt@localhost:55432/postgres")


# ---------------------------------------------------------------- building the tools
def test_tools1_a_tool_package_never_shadows_a_kernel_rule():
    """Packages load after the kernel's checks and would replace them: a placeholder guard that always fails would refuse every call."""
    from bitt.kernel import KERNEL_RULES
    for p in packages():
        shadow = set(p.rules) & set(KERNEL_RULES)
        assert not shadow, f"{p.name} shadows kernel checks {sorted(shadow)}"


# ---------------------------------------------------------------- kernel rules no replay reaches
def test_kernel1_inputs_follow_the_card(opener):
    rec = opener()
    k, c = kernel(rec)
    t = c("control.goal.open_root", USR, problem="x", name="t")["goal"]
    with pytest.raises(Refused, match="input `bogus` is not in the contract"):
        c("control.test_note", USR, in_=t, text="x", bogus=1)
    with pytest.raises(Refused, match="takes one ref, got a list"):
        c("control.test_note", USR, in_=[t], text="x")
    with pytest.raises(Refused, match="not callable"):
        c("base.write", USR, in_=t)
    with pytest.raises(Refused, match="is internal"):
        c("exec.job.submit", USR, caller_event=t, needs={})
    with pytest.raises(Refused, match="is not one of usr"):
        c("control.test_note", "root", in_=t, text="x")
    assert not rec.find("note"), "nothing was written"


def _warn_package(tmp_path):
    cards = {"tool": "control", "cards": [
        {"id": "control.test_warned", "kind": "maneuver", "extends": "base.write", "in": {"min": {"text": {"type": "text"}}},
         "out": {"min": {"note": {"ref_out": "note"}}}, "requires": [{"rule": "control.test_never", "subject": "in", "on_fail": "warn"}]},
        {"id": "control.test_never", "kind": "rule", "summary": "always fails (a test)"}]}
    f = tmp_path / "warned.yaml"
    f.write_text(yaml.safe_dump(cards))
    return Package(name="warned", cards=[f], impls={"control.test_warned": lambda eng, e, ctx, refs: {"note": eng.make("note", ctx, refs)}},
                   rules={"control.test_never": lambda eng, s, scope: ("fail", "never")})


def test_kernel2_a_warning_points_at_what_it_is_about(tmp_path):
    k, c = kernel(None, extra=[_warn_package(tmp_path)])
    t = c("control.goal.open_root", USR, problem="x", name="t")["goal"]
    d = c("control.test_warned", in_=t, text="x")["note"]
    (w,) = k.rec.find("warning")
    assert w["links"]["subject"] == t and w["links"]["subject"] != d, "a warning is on its subject (the task here), not the new output"


def test_kernel3_a_retired_policy_no_longer_applies(opener):
    k, c = kernel(opener())
    t = c("control.goal.open_root", USR, problem="x", name="t")["goal"]
    x = c("control.cycle.open", in_=t, question="x", level="explore", because=[t])["cycle"]
    raw = load(c)
    p = c("control.policy", USR, in_=t, on_event="run.go", rule=module(k, c, x, "smoke_kept", NOT_THREE, cols={"skip_smoke": "skip_smoke"}))["policy"]
    up = module(k, c, x, "upper", UPPER, cols={"q": "q"})
    with pytest.raises(Refused, match="smoke_kept"):
        c("run.go", in_=x, recipe=up, on=[raw], skip_smoke="yes")
    c("control.policy_retire", USR, in_=t, policy=p, reason="skipping the smoke is fine now")
    assert c("run.go", in_=x, recipe=up, on=[raw], skip_smoke="yes")["run"]


def test_kernel4_a_verdict_counts_only_after_every_arm_is_measured(opener):
    k, c = kernel(opener())
    t = c("control.goal.open_root", USR, problem="x", name="t")["goal"]
    w, sk, _ = working(c, t)
    d = c("run.go", in_=w, recipe=split_recipe(k, c, w), on=[load(c)], as_="dataset", fills=sk)["set"]
    early = c("control.validate", USR, in_=w, subject=d, verdict="reject")["validation"]
    c("control.log.finding", in_=w, text="too early", evidence=[early], finding_kind="conclusion")
    v = c("control.validate", USR, in_=w, subject=d, verdict="approve")["validation"]
    assert k.cstate(w) == "JUDGE", "a verdict written before the arm was measured does not move the cycle"
    c("control.log.finding", in_=w, text="ok", evidence=[v], finding_kind="conclusion")
    assert k.cstate(w) == "ACT"


def test_kernel4_the_latest_validation_decides_an_arm(opener):
    k, c = kernel(opener())
    t = c("control.goal.open_root", USR, problem="x", name="t")["goal"]
    w, sk, plan = working(c, t)
    d = c("run.go", in_=w, recipe=split_recipe(k, c, w), on=[load(c)], as_="dataset", fills=sk)["set"]
    c("control.validate", USR, in_=w, subject=d, verdict="pass")
    assert k.arm_state(sk, k.node(plan)) == "measured"
    c("control.validate", USR, in_=w, subject=d, verdict="fail")
    assert k.arm_state(sk, k.node(plan)) == "filled", "a later fail un-measures it"


def test_kernel4_an_agents_plan_measures_nothing_until_a_person_confirms_it(opener):
    k, c = kernel(opener())
    t = c("control.goal.open_root", USR, problem="x", name="t")["goal"]
    w, sk, plan = working(c, t, actor=A)
    d = c("run.go", in_=w, recipe=split_recipe(k, c, w), on=[load(c)], as_="dataset", fills=sk)["set"]
    c("control.validate", USR, in_=w, subject=d, verdict="pass")
    assert k.arm_state(sk, k.node(plan)) == "filled", "an agent's plan is a proposal"
    c("control.validate", USR, in_=w, subject=plan, verdict="approve")
    assert k.arm_state(sk, k.node(plan)) == "measured"
    c("control.validate", USR, in_=w, subject=plan, verdict="reject")
    assert k.arm_state(sk, k.node(plan)) == "filled", "a later reject takes the confirmation back"


def test_kernel5_a_line_holds_one_kind(opener):
    k, c = kernel(opener())
    t = c("control.goal.open_root", USR, problem="x", name="t")["goal"]
    w, d, f = data_cycle(k, c, t, "qa")
    x = c("control.cycle.open", in_=t, question="x", level="explore", because=[t])["cycle"]
    with pytest.raises(Refused, match="names a dataset"):
        c("run.go", in_=x, recipe=split_recipe(k, c, x), on=[d], as_="evalset", line="qa")
    with pytest.raises(Refused, match="names a module, not one of"):     # a name of the wrong kind is refused by the resolver
        c("run.go", in_=x, recipe=split_recipe(k, c, x), on=["split"])


def test_kernel6_a_short_name_never_reaches_another_task(opener):
    k, c = kernel(opener())
    ta = c("control.goal.open_root", USR, problem="A", name="ta")["goal"]
    tb = c("control.goal.open_root", USR, problem="B", name="tb")["goal"]
    data_cycle(k, c, ta, "qa")
    assert k.resolve("qa")[0], "with no task, the one task that has it"
    with pytest.raises(Refused, match="no name `qa` in task 'tb'"):
        k.resolve("qa", tb)
    assert k.resolve("ta/qa", tb)[0], "written in full, it does"


def test_kernel7_grants_count_from_when_they_are_made_until_revoked(opener):
    k, c = kernel(opener())
    t = c("control.goal.open_root", USR, problem="x", name="t")["goal"]
    w, sk, plan = working(c, t)
    d = c("run.go", in_=w, recipe=split_recipe(k, c, w), on=[load(c)], as_="dataset", fills=sk)["set"]
    c("control.validate", A, in_=w, subject=d, verdict="pass")
    assert k.arm_state(sk, k.node(plan)) == "filled", "an ungranted agent's pass measures nothing"
    g = c("control.grant", USR, in_=t, to=A, acts=["validate_pass", "earlystop"], reason="routine")["grant"]
    assert k.arm_state(sk, k.node(plan)) == "filled", "a grant does not reach back to a pass made before it"
    c("control.validate", A, in_=w, subject=d, verdict="pass")
    assert k.arm_state(sk, k.node(plan)) == "measured"
    c("control.revoke", USR, in_=t, grant=g, reason="no more")
    w2, _, _ = working(c, t, name="qb")
    with pytest.raises(Refused, match="act_allowed"):
        c("control.act", in_=w2, outcome="earlystop", reason="x")           # revoked: earlystopping a working cycle is a person's again


# ---------------------------------------------------------------- data rules no replay reaches
UNITS = (b'"""One unit per question, keeping its id."""\nBITT = {"kind": "derive", "writes": {"qid": "text"}, "reads": ["qid"]}\n\n\n'
         b'def units(rows: list) -> list:\n    return [{"qid": r["qid"]} for r in rows]\n')
BY_GROUP = (b'"""Odd ids are test."""\nBITT = {"kind": "derive", "writes": "selection", "reads": ["group"]}\n\n\n'
            b'def by_group(rows: list) -> list:\n    return [(i, "test" if int(r["group"][1:]) % 2 else "train") for i, r in enumerate(rows)]\n')


def test_guard1_a_group_key_is_read_through_lineage(opener):
    """A table derive's rows come from its whole input set: the group guard walks that lineage down to raw (it may over-flag, never
    miss: db.md §3), so a split whose unit rows look clean is still refused when their raw rows put a group on both sides."""
    k, c = kernel(opener())
    t = c("control.goal.open_root", USR, problem="x", name="t")["goal"]
    x = c("control.cycle.open", in_=t, question="x", level="explore", because=[t])["cycle"]
    units = c("run.go", in_=x, recipe=module(k, c, x, "units", UNITS, cols={"qid": "qid"}), on=[load(c, n=6)], full="yes")["run"]
    with pytest.raises(Refused, match="run.group_leak"):
        c("run.go", in_=x, recipe=module(k, c, x, "by_group", BY_GROUP, cols={"group": "qid"}), on=[units], as_="dataset", line="u")


# ---------------------------------------------------------------- sets (db.md §4)
def test_sets1_a_set_is_its_members_in_order_stored_once(opener):
    rec = opener()
    k, c = kernel(rec)
    c("control.goal.open_root", USR, problem="x", name="t")
    raw = c("data.load", bytes=json.dumps([{"id": f"r{i}", "q": f"question {i}"} for i in range(12)]), origin="t", sensitivity="internal",
            does="synthetic rows for a test", line="qs")["raw"]
    rs = [r["bitt_row_hash"] for r in sorted(rec.table_rows("raw.qs"), key=lambda r: r["q"])]
    m = [(r, "train" if i % 4 else "test") for i, r in enumerate(rs)]
    a = sets.write_set(rec, "raw.qs", m, "dataset", raw)
    assert sets.write_set(rec, "raw.qs", m, "dataset", raw) == a, "the same members = the same set"
    assert sets.write_set(rec, "raw.qs", m[::-1], "dataset", raw) != a, "order is part of a set (a prefix depends on it)"
    assert sets.members(rec, a) == m
    with pytest.raises(Refused, match="twice"):
        sets.write_set(rec, "raw.qs", [m[0], m[0]], "dataset", raw)
    assert sets.write_set(rec, "raw.qs", [(rs[0], None, 0), (rs[0], None, 1)], "run_out", raw), "a run's entries follow its units"
    full = sets.write_set(rec, "raw.qs", [(r, None) for r in rs], "selection", raw)
    rung5 = sets.prefix_set(rec, full, 5, raw)
    assert sets.prefix_set(rec, rung5, 1, raw) == sets.prefix_set(rec, full, 1, raw), "a prefix of a prefix is a prefix of the root"
    rec.drop_proposal()


def test_sets2_links_over_several_tables_are_checked(opener):
    rec = opener()
    k, c = kernel(rec)
    c("control.goal.open_root", USR, problem="x", name="t")
    raw = load(c, n=3)
    rs = [r["bitt_row_hash"] for r in rec.table_rows("raw.qs")]
    rec.make_table("output", "made", "pairs", {}, [{"name": "x", "type": "text", "kind": "output"}], raw)
    sets.src_table(rec, "made.pairs", {"q": "raw.qs", "set": "bitt.set"}, raw)
    with pytest.raises(Refused, match="points at no row"):
        sets.link(rec, "made.pairs", "j" * 64, "q", "0" * 64)              # roles over several tables: the kernel checks
    sets.link(rec, "made.pairs", "j" * 64, "q", rs[0])
    rec.drop_proposal()


# ---------------------------------------------------------------- envs
def ssh_env(tmp_path, **c):
    """The ssh adapter in local-shell mode (`host: ""`): the same commands, on this machine, in `workdir`."""
    return envs.SSHEnv({"name": "box", "type": "ssh", "host": "", "workdir": str(tmp_path / "remote"), "python": sys.executable, **c})


def test_env1_an_env_takes_only_the_data_it_may_and_never_launches_beside_a_shared_mps_server(tmp_path, monkeypatch):
    box = ssh_env(tmp_path, max_sensitivity="internal", mps_guard=True)
    with pytest.raises(Refused, match="takes data up to 'internal'"):
        envs.check_sensitivity(box, "company")
    envs.check_sensitivity(box, "internal")
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "nvidia-cuda-mps-control").write_text("#!/bin/sh\necho 4242\n")
    (fake / "nvidia-cuda-mps-control").chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake}:{__import__('os').environ['PATH']}")
    assert "MPS server" in box.guard(), "a shared MPS server on the host refuses the launch"
    (fake / "nvidia-cuda-mps-control").unlink()
    assert box.guard() is None


def test_env2_a_module_job_runs_over_ssh_detached_and_comes_back(tmp_path, monkeypatch):
    import time
    monkeypatch.setenv("BITT_JOBS", str(tmp_path / "jobs"))
    box = ssh_env(tmp_path)
    envs.write_module_job(box.local_dir("j1"), {"kind": "derive", "scope": "row", "fn": "upper", "reads": ["q"], "params": {}, "writes": {"upper": "text"}}, UPPER,
                          [{"q": " a "}], sys.executable)
    box.launch("j1")                                    # setsid where it exists, plain nohup elsewhere (macOS has no setsid)
    for _ in range(100):
        if box.status("j1") == "done" or box.status("j1").startswith("failed"):
            break
        time.sleep(0.1)
    assert box.status("j1") == "done", "the job ran in the env's workdir"
    out = json.loads((box.fetch("j1") / "output" / "rows.jsonl").read_text().splitlines()[0])
    assert out["upper"] == " A ", "and its output came back"
