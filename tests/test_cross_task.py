"""Reading another task's data (#4): a version of its dataset is read in full and pinned, and makes nothing in that task; anything
else from another task warns at the run (it may change), and what is made from it cannot be versioned. On every backend."""
import pytest

from bitt import Refused
from test_run import A, USR, recipe, world


def version(c, x, target):
    v = c("control.validate", USR, in_=x, subject=target, verdict="approve")["validation"]
    f = c("control.log.finding", in_=x, text="it holds", evidence=[v])["finding"]
    return c("tag.make", in_=x, target=target, tag="version", because=[f])


def other(c):
    u = c("control.goal.open_root", USR, problem="route", name="u")["goal"]
    return u, c("control.cycle.open", in_=u, question="reuse t's split", level="explore", because=[u])["cycle"]


def test_another_tasks_version_is_read_pinned_and_makes_nothing_there(opener):
    k, c, t, x, raw = world(opener())
    ds = c("run.go", in_=x, recipe=recipe(c, x, "split", cols={"qid": "qid"}), on=[raw], as_="dataset", line="qa")["set"]
    version(c, x, ds)
    u, y = other(c)
    before = {n for n in k.rec.nodes if k.task_of(n) == t}
    got = c("run.go", in_=y, recipe=recipe(c, y, "clean", cols={"text": "title"}), on=["t/qa@1.0"], full="yes")
    assert not [w for w in got.get("warnings", []) if "not a version" in w], got.get("warnings")
    assert k.node(got["run"])["payload"]["input_set"] == k.node(ds)["payload"]["set"], "the run pins the version it read"
    assert {n for n in k.rec.nodes if k.task_of(n) == t} == before, "nothing is made in the other task"
    assert k.task_of(got["run"]) == u


def test_another_tasks_unversioned_data_warns_and_what_is_made_from_it_is_never_versioned(opener):
    """A plain selection of another task passed the old rule (it checked only datasets and evalsets upstream)."""
    k, c, t, x, raw = world(opener())
    picked = c("run.go", in_=x, recipe=recipe(c, x, "split", cols={"qid": "qid"}), on=[raw], as_="selection")["set"]
    u, y = other(c)
    got = c("run.go", in_=y, recipe=recipe(c, y, "split", cols={"qid": "qid"}), on=[picked], as_="evalset", line="mine")
    assert any("is task t's and not a version" in w for w in got.get("warnings", [])), got.get("warnings")
    with pytest.raises(Refused, match="tag.upstream_tagged → fail \\(made from .* of task t, which is not a version"):
        version(c, y, got["set"])
    ds = c("run.go", in_=x, recipe=recipe(c, x, "split", cols={"qid": "qid"}), on=[raw], as_="dataset", line="qa")["set"]
    version(c, x, ds)                                             # t versions a dataset; u remakes from the version
    again = c("run.go", in_=y, recipe=recipe(c, y, "split", cols={"qid": "qid"}), on=["t/qa@1.0"], as_="evalset", line="mine2")
    assert not [w for w in again.get("warnings", []) if "not a version" in w]
    assert version(c, y, again["set"])["tagged"]
