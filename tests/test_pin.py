"""A wrap may pin data (owner 11-04): `on` = the only units it walks, another role = a fixed read; a changed pin is a major. An eval is
a wrap of an eval pipeline that pins what it judges: every arm runs on exactly that. Samples are the recipe's, never the run's.
On every backend."""
import pytest

from bitt import Refused
from test_pipeline import setup
from test_run import recipe, world
from test_tag import qa

USR = "usr"


def wrap(c, x, module, name, **pin):
    return c("module.wrap", in_=x, module=module, name=name, does=f"{module}, pinned", pin=pin)["wrap"]


def test_a_wrap_walks_only_the_data_it_pins(opener):
    k, c, t, x, raw = world(opener())
    ds = qa(c, x, raw)
    other = c("run.go", in_=x, recipe=recipe(c, x, "split", cols={"qid": "qid"}), on=[raw], as_="evalset", line="other")["set"]
    w = wrap(c, x, "clean", "clean_qa", on=ds)
    r = recipe(c, x, "clean_qa", cols={"text": "title"})
    with pytest.raises(Refused, match=r"run.pinned → fail \(its wrap pins t/qa: it walks that and nothing else"):
        c("run.go", in_=x, recipe=r, on=[other], full="yes")
    with pytest.raises(Refused, match="run.pinned"):
        c("run.go", in_=x, recipe=r, on=[raw], full="yes")
    done = c("run.go", in_=x, recipe=r, on=[ds], full="yes")["run"]
    words = wrap(c, x, "words", "words_qa", on=ds)
    assert c("run.go", in_=x, recipe=recipe(c, x, "words_qa", cols={"text": "clean"}), on=[done], full="yes")["run"], \
        "a run made from the pinned units stands on them"
    with pytest.raises(Refused, match="already pins \\['on'\\]: a pin never moves"):
        wrap(c, x, "clean_qa", "clean_other", on=other)
    assert ds in k.lineage(w), "a pin is lineage: versioning the wrap needs its data versioned (tag.upstream_tagged)"


def test_a_changed_pin_is_a_major(opener):
    from test_tag import SRC
    from test_run import CLEAN
    k, c, t, x, raw = world(opener())
    ds = qa(c, x, raw)
    c("module.define", in_=x, code=CLEAN, name="clean", source=SRC)
    w1 = wrap(c, x, "clean", "clean_on", on=ds)
    f = c("control.log.finding", in_=x, text="runs", evidence=[c("run.go", in_=x, recipe=recipe(c, x, "clean_on", cols={"text": "title"}),
                                                                  on=[ds])["run"]])["finding"]
    assert c("tag.make", in_=x, target=w1, tag="version", because=[f])["bump"] == "first"
    ev = c("run.go", in_=x, recipe=recipe(c, x, "split", cols={"qid": "qid"}), on=[raw], as_="evalset", line="later")["set"]
    v = c("control.validate", USR, in_=x, subject=ev, verdict="approve")["validation"]
    c("tag.make", in_=x, target=ev, tag="version", because=[c("control.log.finding", in_=x, text="ok", evidence=[v])["finding"]])
    w2 = wrap(c, x, "clean", "clean_on", on=ev)
    with pytest.raises(Refused, match="control.approval"):
        c("tag.make", in_=x, target=w2, tag="version", because=[f])            # other data: a major, a person's


def test_an_eval_that_pins_its_evalset_judges_every_arm_on_it(opener):
    """B2: an eval is a wrap of an eval pipeline that pins what it judges; an arm on other data is refused (for other data, another
    eval: a wrap without that pin)."""
    k, c, t, x, raw = world(opener())
    setup(k, c, x)
    ds = qa(c, x, raw)
    other = c("run.go", in_=x, recipe=recipe(c, x, "split", cols={"qid": "qid"}), on=[raw], as_="evalset", line="other")["set"]
    v = c("control.validate", USR, in_=x, subject=other, verdict="approve")["validation"]
    c("tag.make", in_=x, target=other, tag="version", because=[c("control.log.finding", in_=x, text="ok", evidence=[v])["finding"]])
    wrap(c, x, "judge_nonempty", "judge_qa", on=ds)
    w = c("control.cycle.open", USR, in_=t, question="is clean good enough on qa?", level="working", because=[t])["cycle"]
    arm = recipe(c, w, "clean", cols={"text": "title"})
    c("control.plan", USR, in_=w, arms=[arm], win="most outputs are not blank", pipeline="judge_qa")
    with pytest.raises(Refused, match=r"run.arm_on_version → fail \(this plan's eval judges t/qa only"):
        c("run.go", in_=w, recipe=arm, on=[other], full="yes")                # a version, but not the eval's
    c("run.go", in_=w, recipe=arm, on=[ds], full="yes")
    assert k.arm_state(arm, k.latest_plan(w)) == "measured", "the eval ran on the arm (its units: the pinned evalset)"


def test_samples_are_the_recipes(opener):
    """The same recipe always asks the same number of times; the run has no say. Asking more reuses the asks already made (D8)."""
    from test_units import echo, load
    k, c, t, x, _ = world(opener())
    raw = load(c, x, [{"text": f"text {i}"} for i in range(12)])
    two = echo(k, c, x, samples=2)
    three = recipe(c, x, "echo", artifacts={"prompt": "pred"}, cols={"text": "text"}, samples=3)      # the same prompt version
    from bitt.tools import recipe as recipes
    assert recipes.label(k, two).endswith("x2") and recipes.label(k, three).endswith("x3") and two != three
    r2s = c("run.go", in_=x, recipe=two, on=[raw], full="yes")["runs"]
    r3s = c("run.go", in_=x, recipe=three, on=[raw], full="yes")["runs"]
    end = lambda r: k.rec.get_row("bitt.run_end", (r,))  # noqa: E731
    tot = lambda rs, f: sum(end(r)[f] for r in rs)  # noqa: E731 — the smoke rung, then all
    assert (tot(r2s, "made"), tot(r3s, "made")) == (24, 12), [end(r) for r in r2s + r3s]
    assert end(r3s[-1])["made"] + end(r3s[-1])["reused"] == 36, "3 asks of 12 rows: only the third is new, the 24 earlier reused"
    with pytest.raises(Refused, match="n_samples"):
        c("run.go", in_=x, recipe=two, on=[raw], n_samples=5)
