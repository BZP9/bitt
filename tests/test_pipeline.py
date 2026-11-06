"""Pipeline modules (foundation.md §C3, §K): steps are runs of their own recipes, pinned at recipe time; the ladder goes through the
steps; an eval's one rule makes a decision; a plan's eval measures its arms. On every backend."""
import json

import pytest

from bitt import Refused
from bitt.tools.run import status_of
from test_run import recipe, world

USR = "usr"
POLISH = (b'"""Summarize a ticket, then polish the summary."""\nBITT = {"kind": "pipeline"}\n\n\n'
          b'def polish(b, on, *, model: str = "echo"):\n'
          b'    s = b.run("summarize", on=on, with_=model, cols={"title": "title"})\n'
          b'    return b.run("beautify", on=s, with_=model, cols={"draft": "summarize"})\n')
EVAL = (b'"""Judge an arm: most of its outputs are not blank."""\nBITT = {"kind": "pipeline", "win": "lo >= 0.5"}\n\n\n'
        b'def judge(b, on, *, col: str = "clean"):\n    v = b.run("nonempty", on=on, cols={"value": col})\n'
        b'    return b.run("rate", on=v, cols={"x": "nonempty"})\n')


def prompt(name, text):
    return json.dumps({"bitt": {"does": f"The {name} step."}, "messages": [{"role": "user", "content": text}]})


def setup(k, c, x):
    c("artifact.add", in_=x, content=prompt("summarize", "S: {title}"), artifact_kind="prompt", name="summarize")
    c("artifact.add", in_=x, content=prompt("beautify", "B: {draft}"), artifact_kind="prompt", name="beautify")
    c("module.define", in_=x, code=POLISH, name="polish")
    c("module.define", in_=x, code=(EVAL), name="judge_nonempty")
    from bitt.builtins import SHIPPED
    c("module.define", in_=x, code=SHIPPED["nonempty"].read_bytes(), name="nonempty")


def made(k, run):
    return [k.rec.get_row("bitt.run_end", (s,))["made"] for s in k.node(run)["links"]["steps"]]


def test_two_prompts_in_a_row(opener):
    k, c, t, x, raw = world(opener())
    setup(k, c, x)
    p = recipe(c, x, "polish")
    pins = k.node(p)["payload"]["pins"]
    assert set(pins) == {"summarize", "beautify", "echo"}, "every name its steps write, pinned now"
    first = c("run.go", in_=x, recipe=p, on=[raw])["run"]
    assert made(k, first) == [9, 9], "the ladder goes through the steps: each climbs smoke → its sample (1 + 9), step 2 over what step 1 made"
    second = c("run.go", in_=x, recipe=p, on=[raw])["run"]
    assert made(k, second) == [2, 2] and status_of(k.rec, second) == "done", "the next rung (all): only the new rows, in both steps"
    out = k.rec.table_rows("made.beautify")
    assert sorted(r["beautify"] for r in out)[0] == "B: S:   Title 0 ", "step 2 read step 1's output"
    c("artifact.add", in_=x, content=prompt("beautify", "Better: {draft}"), artifact_kind="prompt", name="beautify")
    assert made(k, c("run.go", in_=x, recipe=p, on=[raw])["run"]) == [0, 0], "a newer beautify changes nothing until a new recipe (C11)"
    p2 = recipe(c, x, "polish", why="the new beautify")
    assert k.node(p2)["spec_h"] != k.node(p)["spec_h"], "a new recipe pins the new version: another work"


def test_an_eval_decides_and_keeps_what_it_read(opener):
    k, c, t, x, raw = world(opener())
    setup(k, c, x)
    arm = c("run.go", in_=x, recipe=recipe(c, x, "clean", cols={"text": "title"}), on=[raw], full="yes")["run"]
    out = c("run.go", in_=x, recipe=recipe(c, x, "judge_nonempty"), on=[arm])
    d = k.node(out["decision"])
    assert d["payload"]["won"] and d["payload"]["rule"] == "lo >= 0.5" and d["payload"]["row"]["n"] == 12, "it keeps the row it read"
    assert d["links"]["subject"] == [arm] and not out.get("warnings"), "over a builtin check: clean"
    with pytest.raises(Refused, match="did not pin"):
        c("module.define", in_=x, code=EVAL.replace(b'b.run("nonempty"', b'b.run(col').replace(b'"clean"', b'"no_such"'), name="judge_loose")
        c("run.go", in_=x, recipe=recipe(c, x, "judge_loose"), on=[arm])


def test_a_plans_eval_measures_its_arm(opener):
    k, c, t, x, raw = world(opener())
    setup(k, c, x)
    w = c("control.cycle.open", in_=t, question="is clean good enough?", level="working", because=[t])["cycle"]
    arm = recipe(c, x, "clean", cols={"text": "title"})
    c("control.plan", USR, in_=w, arms=[arm], win="most outputs are not blank", pipeline="judge_nonempty")
    assert k.cstate(w) == "WORK"
    with pytest.raises(Refused, match="run.arm_on_version → fail .*runs on raw/tickets, which is not a version"):
        c("run.go", in_=w, recipe=arm, on=[raw], full="yes")       # a working verdict is a result: on named data only
    assert not k.rec.find("decision")
    from test_tag import qa
    c("run.go", in_=w, recipe=arm, on=[qa(c, x, raw)], full="yes")
    assert k.arm_state(arm, k.latest_plan(w)) == "measured" and k.cstate(w) == "JUDGE", "the plan's eval ran on the arm and decided"
    (d,) = k.rec.find("decision")
    assert d["stamp"]["actor"].startswith("pipeline:")


def test_a_person_judged_arm_runs_on_anything(opener):
    """run.arm_on_version binds a plan an eval judges (its verdict is a machine's result); a plan a person judges, and every
    explore cycle (no plans there), stay free: an agent works on drafts, a person versions later."""
    k, c, t, x, raw = world(opener())
    w = c("control.cycle.open", USR, in_=t, question="are clean titles readable?", level="working", because=[t])["cycle"]
    arm = recipe(c, w, "clean", cols={"text": "title"})
    c("control.plan", in_=w, arms=[arm], win="titles read well", judged_by="person")
    assert c("run.go", in_=w, recipe=arm, on=[raw], full="yes")["run"]


def test_an_agents_plan_is_judged_only_once_a_person_approves_it(opener):
    """Owner 11-04 (SOP Q1): an agent may fill the arms of the plan it proposed, but the plan's eval waits for the approve (nothing is
    judged on a proposal, so no decision sits in the record looking like a result); the approve runs it on every arm already filled."""
    from test_tag import qa
    k, c, t, x, raw = world(opener())
    setup(k, c, x)
    ag = "agent:t"
    w = c("control.cycle.open", USR, in_=t, question="is clean good enough?", level="working", because=[t])["cycle"]
    arm = recipe(c, w, "clean", cols={"text": "title"})
    plan = c("control.plan", ag, in_=w, arms=[arm], win="most outputs are not blank", pipeline="judge_nonempty")["plan"]
    on = qa(c, x, raw)
    c("run.go", ag, in_=w, recipe=arm, on=[on], full="yes")
    assert not k.rec.find("decision") and k.arm_state(arm, k.latest_plan(w)) == "filled", "a proposal: filled, never judged"
    c("control.validate", USR, in_=w, subject=plan, verdict="approve")
    (d,) = k.rec.find("decision")
    assert d["stamp"]["actor"].startswith("pipeline:") and k.arm_state(arm, k.latest_plan(w)) == "measured" and k.cstate(w) == "JUDGE"


def test_a_check_outside_the_plans_eval_is_warned_a_hint(opener):
    """Owner 11-04 (SOP Q5): in a working cycle the plan's eval judges; a check run by hand there is allowed, warned, and a hint.
    The eval's own steps are not warned, and an explore cycle is free."""
    from test_tag import qa
    k, c, t, x, raw = world(opener())
    setup(k, c, x)
    w = c("control.cycle.open", USR, in_=t, question="is clean good enough?", level="working", because=[t])["cycle"]
    arm = recipe(c, w, "clean", cols={"text": "title"})
    c("control.plan", USR, in_=w, arms=[arm], win="most outputs are not blank", pipeline="judge_nonempty")
    out = c("run.go", in_=w, recipe=arm, on=[qa(c, x, raw)], full="yes")
    assert not [m for m in out.get("warnings", []) if "outside the plan's eval" in m], "the plan's eval and its steps: not warned"
    by_hand = c("run.go", in_=w, recipe=recipe(c, w, "nonempty", cols={"value": "clean"}), on=[out["run"]], full="yes")
    assert [m for m in by_hand.get("warnings", []) if "outside the plan's eval: its verdicts are a hint" in m]
    free = c("run.go", in_=x, recipe=recipe(c, x, "nonempty", cols={"value": "title"}), on=[raw], full="yes")
    assert not [m for m in free.get("warnings", []) if "outside the plan's eval" in m], "explore: free"
