"""Rules the replays do not reach, each pinned by a test that fails when the rule is switched off (conformance/mutate.py)."""
import re

import pytest

from bitt import Refused
from test_run import USR, recipe, world


def finding(c, x, ev):
    return c("control.log.finding", in_=x, text="seen", evidence=[ev])["finding"]


def working(c, t, want_kind):
    w = c("control.cycle.open", in_=t, question="decide", level="working", because=[t])["cycle"]
    sk = c("control.want", in_=w, want_kind=want_kind, name="out", contract={})["want"]
    c("control.plan", USR, in_=w, arms=[sk], win="a person approves it", judged_by="person")
    return w, sk


def test_the_root_task_is_never_superseded(opener):
    k, c, t, x, raw = world(opener())
    f = finding(c, x, c("run.go", in_=x, recipe=recipe(c, x, "clean", cols={"text": "title"}), on=[raw])["run"])
    with pytest.raises(Refused, match="control.not_root"):
        c("control.goal.open", USR, in_=t, problem="y", supersedes=[t], because=[f])


def test_an_input_built_under_an_old_goal_is_warned(opener):
    k, c, t, x, raw = world(opener())
    g1 = c("control.goal.open", USR, in_=t, problem="route tickets", contract={"acc": 0.8})["goal"]
    x1 = c("control.cycle.open", in_=g1, question="q", level="explore", because=[g1])["cycle"]
    old = c("run.go", in_=x1, recipe=recipe(c, x1, "clean", cols={"text": "title"}), on=[raw], full="yes")["run"]
    f = finding(c, x1, old)
    g2 = c("control.goal.open", USR, in_=t, problem="route tickets", contract={"acc": 0.9}, supersedes=[g1], because=[f])
    assert g2["bump"] == "major"
    x2 = c("control.cycle.open", in_=g2["goal"], question="q", level="explore", because=[g2["goal"]])["cycle"]
    out = c("run.go", in_=x2, recipe=recipe(c, x2, "words", cols={"text": "clean"}), on=[old], full="yes")
    assert any("was built under goal" in w for w in out.get("warnings", [])), out.get("warnings")


def test_a_policys_rule_applies_to_one_maneuver(opener):
    k, c, t, x, raw = world(opener())
    rule = recipe(c, x, "length", cols={"text": "title"})
    with pytest.raises(Refused, match="control.policy_shape"):
        c("control.policy", USR, in_=t, on_event="run.nope", rule=rule)
    c("control.policy", USR, in_=t, on_event="run.go", rule=rule)


def test_a_fill_is_the_kind_its_want_wants(opener):
    k, c, t, x, raw = world(opener())
    w, sk = working(c, t, "dataset")
    with pytest.raises(Refused, match="control.fills"):
        c("run.go", in_=w, recipe=recipe(c, w, "clean", cols={"text": "title"}), on=[raw], fills=sk)


def test_a_working_cycle_makes_only_what_its_plan_wants(opener):
    k, c, t, x, raw = world(opener())
    w, _ = working(c, t, "artifact")
    with pytest.raises(Refused, match="control.plan_wants"):
        c("run.go", in_=w, recipe=recipe(c, w, "split", cols={"qid": "qid"}), on=[raw], as_="dataset", line="loose")


def test_a_module_that_reaches_outside_its_job_is_warned_untraced(opener):
    k, c, t, x, raw = world(opener())
    c("module.define", in_=x, code=b'"""Ask a server."""\nBITT = {"kind": "derive"}\nimport socket\n\n\n'
      b'def host(text: str) -> str:\n    return socket.gethostname()[:0] + text\n', name="host")
    out = c("run.go", in_=x, recipe=recipe(c, x, "host", cols={"text": "title"}), on=[raw], full="yes")
    assert any("untraced: the module imports socket" in w for w in out.get("warnings", [])), out.get("warnings")


def test_a_valid_check_gives_the_same_verdicts_twice(opener):
    k, c, t, x, raw = world(opener())
    coin = c("module.define", in_=x, code=b'"""A coin, not a check."""\nBITT = {"kind": "check"}\nimport random\n\n\n'
             b'def coin(text: str) -> float:\n    return random.random()\n', name="coin",
             source={"path": "mods/coin.py", "repo": "x", "commit": "abc123"})["module"]
    verdicts = c("run.go", in_=x, recipe=recipe(c, x, "coin", cols={"text": "title"}), on=[raw])["run"]
    agree = c("run.go", in_=x, recipe=recipe(c, x, "agreement", cols={"a": "coin", "b": "tickets.qid"}), on=[verdicts])["run"]
    c("control.validate", USR, in_=x, subject=coin, verdict="approve")
    with pytest.raises(Refused, match="tag.deterministic → fail"):
        c("tag.make", USR, in_=x, target=coin, tag="trust", value="trusted", because=[finding(c, x, agree)], agreement=agree)


def test_every_task_name_can_be_its_own_view_schema():
    """A task's name is its views' schema, so a name never reaches a schema bitt or Postgres owns, nor Postgres's 63-byte limit."""
    from bitt import names, tables
    assert set(tables.RESERVED_SCHEMAS) <= names.RESERVED and names.MAX <= 63
    assert all(names.problem(s) for s in tables.RESERVED_SCHEMAS + ("pg_x",))


def test_an_unknown_name_points_at_commands_that_exist(opener):
    """The refusal's next: names only real commands (an agent runs what it is told)."""
    from bitt import cli
    k, c, t, x, raw = world(opener())
    with pytest.raises(Refused) as e:
        k.resolve("no_such_thing", t)
    hint = str(e.value).split("next:")[1]
    cmds = re.findall(r"`bitt ([a-z]+) ([a-z]+)`", hint)
    assert cmds and "bitt names" not in hint
    for noun, verb in cmds:                                    # `-h` exits 0 on a command, 2 on an unknown one
        with pytest.raises(SystemExit) as ex:
            cli.main([noun, verb, "-h"])
        assert ex.value.code == 0, f"bitt {noun} {verb} is not a command"
