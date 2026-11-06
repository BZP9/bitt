"""The workflow's own rules (foundation.md §A): who may do what, and when, on every backend."""
import pytest

from bitt import Kernel, Refused

USR, A = "usr", "agent:t"


def kernel(rec):
    k = Kernel(rec)

    def c(card, actor=A, **a):
        return k.call(card, {{"in_": "in"}.get(x, x): v for x, v in a.items()}, actor)
    return k, c


def test_a_task_name_is_checked_and_unique(opener):
    k, c = kernel(opener())
    c("control.goal.open_root", USR, problem="x", name="support")
    with pytest.raises(Refused, match="is not a name"):
        c("control.goal.open_root", USR, problem="y", name="y'; DROP TABLE x; --")
    with pytest.raises(Refused, match="unique_task_name"):
        c("control.goal.open_root", USR, problem="y", name="support")
    with pytest.raises(Refused, match="has_authority"):
        c("control.goal.open_root", A, problem="an agent's task names no person", name="other")
    assert c("control.goal.open_root", A, problem="y", name="other", authority=[USR])["goal"]


def test_goals_grants_and_approvals_are_a_persons(opener):
    k, c = kernel(opener())
    t = c("control.goal.open_root", USR, problem="x", name="t")["goal"]
    with pytest.raises(Refused, match="human_actor"):
        c("control.goal.open", A, in_=t, problem="an agent's goal")
    g = c("control.goal.open", USR, in_=t, problem="g")["goal"]
    with pytest.raises(Refused, match="human_actor"):
        c("control.grant", A, in_=g, to=A, acts=["close"], reason="me")
    with pytest.raises(Refused, match="grant_shape"):
        c("control.grant", USR, in_=g, to=A, acts=["approve"], reason="approve stays a person's")
    d = c("control.goal.open", USR, in_=t, problem="ship it")["goal"]
    with pytest.raises(Refused, match="can_approve"):
        c("control.validate", "usr:bob", in_=t, subject=d, verdict="approve")       # bob has no authority in t
    with pytest.raises(Refused, match="can_approve"):
        c("control.validate", A, in_=t, subject=d, verdict="approve")
    assert c("control.validate", USR, in_=t, subject=d, verdict="approve")["validation"]


def test_judgments_stay_in_their_task(opener):
    k, c = kernel(opener())
    ta = c("control.goal.open_root", USR, problem="A", name="ta", authority=[USR, "usr:bob"])["goal"]
    tb = c("control.goal.open_root", "usr:bob", problem="B", name="tb", authority=[USR, "usr:bob"])["goal"]
    d = c("control.validate", USR, in_=ta, subject=ta, verdict="pass")["validation"]      # a judgment made in A (not A's intent)
    with pytest.raises(Refused, match="same_task"):
        c("control.validate", "usr:bob", in_=tb, subject=d, verdict="approve")
    with pytest.raises(Refused, match="same_task"):
        c("control.ack", "usr:bob", in_=tb, subject=d, rule="run.leak")


def test_a_cycle_closes_only_where_its_state_allows(opener):
    k, c = kernel(opener())
    t = c("control.goal.open_root", USR, problem="x", name="t")["goal"]
    x = c("control.cycle.open", in_=t, question="try", level="explore", because=[t])["cycle"]
    assert k.cstate(x) == "EXPLORE"
    w = c("control.cycle.open", in_=t, question="decide", level="working", because=[t])["cycle"]
    assert k.cstate(w) == "FRAME", "a working cycle without a plan is framing"
    with pytest.raises(Refused, match="act_allowed"):
        c("control.act", USR, in_=w, outcome="close")
    with pytest.raises(Refused, match="plan_has_eval"):
        c("control.plan", USR, in_=w, arms=[c("control.want", in_=w, want_kind="recipe", contract={})["want"]], win="x")
    c("control.act", in_=x, outcome="park", reason="later")
    assert k.cstate(x) == "PARKED"
    with pytest.raises(Refused, match="locked in PARKED"):
        c("control.want", in_=x, want_kind="recipe", contract={})
    c("control.act", in_=x, outcome="resume")
    c("control.act", in_=x, outcome="close")
    assert k.cstate(x) == "CLOSED"
    c("control.act", USR, in_=t, outcome="close")
    assert k.cstate(w) == "CLOSED", "a closed task closes every cycle under it"
