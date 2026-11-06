"""The kernel's call path on every backend: ids, append-only, refusals, nested calls, the rules a tool package cannot break."""
import pytest
import yaml

from notecard import note_package

from bitt import Failed, Kernel, Package, Refused
from bitt.hashing import canonical, h
from bitt.record.memory import MemoryRecord

USR, A = "usr", "agent:t"


def probe_package(tmp_path):
    """A root card of the `data` tool (right of control in the DAG), for the nested-call rules."""
    doc = {"tool": "data", "roots": ["data.probe"], "cards": [
        {"id": "data.probe", "kind": "maneuver", "extends": "base.root", "in": {"min": {"text": {"type": "text"}}},
         "out": {"min": {"probe": {"ref_out": "probe"}}}},
        {"id": "control.test_warned", "kind": "maneuver", "extends": "base.write", "tool": "control",
         "in": {"min": {"text": {"type": "text"}}}, "out": {"min": {"note": {"ref_out": "note"}}},
         "requires": [{"rule": "control.test_never", "subject": "in", "on_fail": "warn"}]},
        {"id": "control.test_never", "kind": "rule", "tool": "control", "summary": "always fails (a test)", "next": "nothing"}]}
    f = tmp_path / "probe.yaml"
    f.write_text(yaml.safe_dump(doc))
    return Package(name="probe", cards=[f],
                   impls={"data.probe": lambda eng, e, ctx, refs: {"probe": eng.make("probe", ctx, refs)},
                          "control.test_warned": lambda eng, e, ctx, refs: {"note": eng.make("note", ctx, refs)}},
                   rules={"control.test_never": lambda eng, s, scope: ("fail", "never")})


def kernel(rec, extra=()):
    k = Kernel(rec, packages=[note_package(), *extra])

    def c(card, actor=A, **a):
        return k.call(card, {{"in_": "in"}.get(x, x): v for x, v in a.items()}, actor)
    return k, c


def task(c, name="t"):
    return c("control.goal.open_root", USR, problem="x", name=name)["goal"]


def node_id(n):
    return h("node", canonical({"kind": n["kind"], "payload": n["payload"], "links": n["links"], "stamp": n["stamp"]}))


def test_ids_are_verifiable_and_survive_reopen(opener):
    rec = opener()
    k, c = kernel(rec)
    t = task(c)
    g = c("control.goal.open", USR, in_=t, problem="big numbers", contract={"x": 1e16, "y": 2.0, "z": 0.5})["goal"]
    c("control.cycle.open", in_=g, question="q", level="explore", because=[g])
    assert all(node_id(n) == i for i, n in rec.nodes.items()), "every node id is the hash of its body"
    if opener.kind == "memory":
        return
    snapshot = {i: (n["kind"], n["payload"], n["links"], n["spec_h"], n["task"]) for i, n in rec.nodes.items()}
    journal = rec.journal()
    rec.close()
    again = opener(same=True)
    assert again.journal() == journal
    assert {i: (n["kind"], n["payload"], n["links"], n["spec_h"], n["task"]) for i, n in again.nodes.items()} == snapshot
    assert node_id(again.nodes[g]) == g, "integral floats are stored as ints everywhere, so the id re-verifies"


def test_append_only_at_the_sql_level(opener):
    rec = opener()
    k, c = kernel(rec)
    t = task(c)
    with pytest.raises(Refused):
        c("control.test_note", in_="nothing-here", text="x")         # a refusal with no `in`: the refusal log
    c("control.test_note", USR, in_=t, text="kept")
    if opener.kind == "memory":
        return
    import psycopg
    for sql in ("TRUNCATE bitt.refusal_log", "TRUNCATE bitt.node CASCADE", "DELETE FROM bitt.node", "UPDATE bitt.node SET kind = 'x'"):
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            rec.db.execute(sql)
        rec.db.rollback()


def test_unstorable_values_are_refused_and_the_kernel_stays_usable(opener):
    rec = opener()
    k, c = kernel(rec)
    t = task(c)
    for bad in ("nul\x00here", float("nan")):
        with pytest.raises(Failed, match="NUL|NaN"):
            c("control.test_note", USR, in_=t, text=bad)
        assert not rec.proposal and k.depth == 0
    n = len(rec.journal())
    c("control.test_note", USR, in_=t, text="fine")
    assert len(rec.journal()) == n + 2, "the note and its event"


def test_inputs_follow_the_card(opener):
    rec = opener()
    k, c = kernel(rec)
    t = task(c)
    with pytest.raises(Refused, match="input `bogus` is not in the contract"):
        c("control.test_note", USR, in_=t, text="x", bogus=1)
    with pytest.raises(Refused, match="takes one ref, got a list"):
        c("control.test_note", USR, in_=[t], text="x")
    with pytest.raises(Refused, match="not callable"):
        c("base.write", USR, in_=t)
    with pytest.raises(Refused, match="is not one of usr"):
        c("control.test_note", "root", in_=t, text="x")
    assert not rec.find("note"), "nothing was written"
    assert [r["payload"]["card"] for r in rec.find("refusal")][-1] == "control.test_note", "each refusal is recorded in the task"


def test_the_kernel_enforces_plugin_rules(tmp_path):
    k, c = kernel(None, extra=[probe_package(tmp_path)])
    t = task(c)
    seen = {}

    def nests_as_usr(eng, e, ctx, refs):          # an impl run for an agent tries to act as usr
        out = eng.call("exec.job.submit", {"caller_event": ctx["_event"], "needs": {}}, actor="usr", caller=None)
        seen["actor"] = eng.node(out["job"])["stamp"]["actor"]
        return {"note": eng.make("note", ctx, refs)}
    k.impls["control.test_note"] = nests_as_usr
    k.eff["control.test_note"]["calls"] = ["exec.job.submit"]
    c("control.test_note", in_=t, text="x")
    assert seen["actor"] == A, "a nested call carries the caller's actor, whatever the impl passes"

    k.impls["control.test_note"] = lambda eng, e, ctx, refs: {"note": eng.make("note", ctx, refs, _links={"in": t})}
    with pytest.raises(Failed, match="impl roles"):
        c("control.test_note", in_=t, text="x")

    k.impls["control.test_note"] = lambda eng, e, ctx, refs: {"note": t}
    with pytest.raises(Failed, match="not a node this call created"):
        c("control.test_note", in_=t, text="x")

    def against_dag(eng, e, ctx, refs):            # data → control is against the DAG, even with caller=None
        eng.call("control.test_note", {"in": t, "text": "x"}, actor="usr", caller=None)
        return {"probe": eng.make("probe", ctx, refs)}
    k.impls["data.probe"] = against_dag
    k.eff["data.probe"]["calls"] = ["control.test_note"]
    n = len(k.rec.journal())
    with pytest.raises(Failed, match="against the DAG"):
        c("data.probe", text="x")
    assert k.depth == 0 and k.rec.journal()[n:] == [] and not k.rec.proposal, "the nested note is not recorded"
    assert "against the DAG" in k.rec.refusals[-1]["reason"], "the refusal is (in the log: a root has no `in`)"


def test_a_caught_nested_refusal_is_not_committed(tmp_path):
    k, c = kernel(None, extra=[probe_package(tmp_path)])
    t = task(c)
    ran = []

    def stages_then_refuses(eng, e, ctx, refs):
        ran.append(eng.make("probe", ctx, refs))
        raise Refused("the nested call changed its mind")

    def catches(eng, e, ctx, refs):
        try:
            eng.call("data.probe", {"text": "x"}, actor=A)
        except Refused:
            pass
        return {"note": eng.make("note", ctx, refs)}
    k.impls["data.probe"] = stages_then_refuses
    k.impls["control.test_note"] = catches
    k.eff["control.test_note"]["calls"] = ["data.probe"]
    c("control.test_note", in_=t, text="x")
    assert ran, "the nested call ran (staged a node) and refused"
    assert not k.rec.find("probe"), "the outer call succeeded; the nested call's staged node did not come with it"
    assert k.rec.find("note")


def test_a_store_that_refuses_the_refusal_too_still_raises_failed():
    rec = MemoryRecord()
    k, c = kernel(rec)
    t = task(c)
    real = rec._persist

    def down(*a):
        raise ConnectionError("the database went away")
    rec._persist = down
    with pytest.raises(Failed, match="refused the commit"):
        c("control.test_note", USR, in_=t, text="lost")
    assert rec.refusals and rec.refusals[-1].get("unrecorded"), "the refusal is kept in memory, marked unrecorded"
    rec._persist = real
    c("control.test_note", USR, in_=t, text="the kernel is usable")


def test_a_warning_points_at_what_it_is_about(tmp_path):
    k, c = kernel(None, extra=[probe_package(tmp_path)])
    t = task(c)
    d = c("control.test_warned", in_=t, text="x")["note"]
    (w,) = k.rec.find("warning")
    assert w["links"]["subject"] == t and w["links"]["subject"] != d, "a warning is on its subject (the task here), not the new output"


def test_tests_only_touch_a_throwaway_cluster(monkeypatch):
    """The guard is bitt's own rule: a local Postgres on a non-default port, not in $BITT_PROTECTED_DSNS."""
    from backend import throwaway_problem
    monkeypatch.delenv("BITT_PROTECTED_DSNS", raising=False)
    assert throwaway_problem("postgresql://bitt@localhost:55432/postgres") is None
    assert "5432" in throwaway_problem("postgresql://me@localhost/postgres")
    assert "not this machine" in throwaway_problem("postgresql://me@db.example:55432/x")
    monkeypatch.setenv("BITT_PROTECTED_DSNS", "postgresql://x@127.0.0.1:55432/live")
    assert "BITT_PROTECTED_DSNS" in throwaway_problem("postgresql://bitt@localhost:55432/postgres")


def test_a_tool_package_never_shadows_a_kernel_rule():
    from bitt.kernel import KERNEL_RULES
    from bitt.tools import packages
    for p in packages():
        shadow = set(p.rules) & set(KERNEL_RULES)
        assert not shadow, f"{p.name} shadows kernel checks {sorted(shadow)}"
