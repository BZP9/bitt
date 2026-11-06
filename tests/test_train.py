"""A train (foundation.md §B, E11): a run in an env, in the background, smoke first; its model is an artifact made by the run, served
by an endpoint wrap; its reported numbers are rows of its report table (never trusted). On every backend."""
import json

import pytest

from bitt import Refused, names
from bitt.builtins import SHIPPED
from bitt.tools.run import land, one_row, status_of
from test_run import out_rows, recipe, world

SPLIT = (b'"""Every fourth row is test."""\nBITT = {"kind": "derive", "writes": "selection", "reads": ["n"]}\n\n\n'
         b'def split(rows: list) -> list:\n    return [(i, "test" if i % 4 == 0 else "train") for i, r in enumerate(rows)]\n')

TEST_ONLY = (b'"""Keep the test side."""\nBITT = {"kind": "derive", "writes": "selection"}\n\n\n'
             b'def test_only(rows: list) -> list:\n    return [(i, "test") for i, r in enumerate(rows) if r["bitt_split"] == "test"]\n')


def setup(k, c, x, raw):
    c("module.define", in_=x, code=SPLIT, name="every_fourth")
    ds = c("run.go", in_=x, recipe=recipe(c, x, "every_fourth", cols={"n": "qid"}), on=[raw], as_="dataset", line="labelled")["set"]
    for n in ("nb_train", "nb_predict"):
        c("module.define", in_=x, code=SHIPPED[n].read_bytes(), name=n)
    tr = recipe(c, x, "nb_train", cols={"text": "title", "label": "qid"})
    ev = recipe(c, x, "exact_match", cols={"a": "pred", "b": "tickets.qid"})
    return ds, tr, ev


def test_a_train_is_smoke_first_then_lands_a_model(opener):
    k, c, t, x, raw = world(opener())
    ds, tr, ev = setup(k, c, x, raw)
    with pytest.raises(Refused, match="run.has_eval → fail"):
        c("run.go", in_=x, recipe=tr, on=[ds])
    smoke = c("run.go", in_=x, recipe=tr, on=[ds], evals=[ev], endpoint="nb_predict", line="clf")
    assert k.node(smoke["run"])["payload"]["smoke"] and k.node(smoke["run"])["payload"]["of"] == 2, "one row per split"
    assert land(k, smoke["job"]) == {"run": smoke["run"]} and status_of(k.rec, smoke["run"]) == "done", "a smoke run makes no model"
    full = c("run.go", in_=x, recipe=tr, on=[ds], evals=[ev], endpoint="nb_predict", line="clf")
    assert not k.node(full["run"])["payload"]["smoke"]
    made = land(k, full["job"])
    m = k.node(made["model"])
    assert m["kind"] == "artifact" and m["payload"]["artifact_kind"] == "model" and m["links"]["run"] == full["run"]
    assert names.label(k, made["model"]) == "t/clf", "a made model is its task's (foundation §B)"
    (rep,) = k.rec.table_rows("made.nb_train_report", bitt_run_hash=full["run"])
    assert rep["step"] == 1 and rep["train_acc"] is not None, "the script's own numbers: rows of its report table, never a check"
    ep = made["endpoint"]
    assert k.node(ep)["links"]["wraps"] == k.resolve("nb_predict", t)[0] and k.node(ep)["payload"]["fixed"]["artifacts"] == {"file": m["id"]}
    pred = c("run.go", in_=x, recipe=recipe(c, x, "clf_endpoint", cols={"text": "title"}), on=[ds], full="yes")["run"]
    assert {r["pred"] for r in out_rows(k, pred)[1]} <= {"Q0", "Q1", "Q2", "Q3"}, "the endpoint serves the model it was made with"
    with pytest.raises(Refused, match="run.contamination"):
        c("run.go", in_=x, recipe=ev, on=[pred])                                   # it trained on 9 of these rows (test_judge.py)
    c("module.define", in_=x, code=TEST_ONLY, name="test_only")
    test_side = c("run.go", in_=x, recipe=recipe(c, x, "test_only"), on=[ds], as_="evalset", line="held_out")
    held = c("run.go", in_=x, recipe=recipe(c, x, "clf_endpoint", cols={"text": "title"}), on=[test_side["set"]], full="yes")["run"]
    scored = c("run.go", in_=x, recipe=ev, on=[held])["run"]
    assert one_row(k, c("run.go", in_=x, recipe=recipe(c, x, "rate", cols={"x": "exact_match"}), on=[scored])["run"])["n"] == 3, \
        "scored on rows it never saw"


def test_a_failed_train_is_never_a_model(opener):
    k, c, t, x, raw = world(opener())
    ds, tr, ev = setup(k, c, x, raw)
    bad = recipe(c, x, "nb_train", cols={"text": "title", "label": "body"}, params={"alpha": 0})
    c("run.go", in_=x, recipe=bad, on=[ds], evals=[ev], skip_smoke="yes")
    assert any("without a passed smoke run" in w["payload"]["detail"] for w in k.rec.find("warning")), "skip_smoke is never silent"
    k2 = c("run.go", in_=x, recipe=bad, on=[ds], evals=[ev], skip_smoke="yes")
    made = land(k, k2["job"])
    assert "model" not in made and status_of(k.rec, k2["run"]) == "failed" and k.job_status(k2["job"]) == "failed"


def test_the_full_train_reports_its_own_numbers(opener):
    """H5 (10-30): a smoke run (one row per split) and the full train share a recipe and a dataset; the smoke's numbers once took the
    full run's place (the old metric was keyed by recipe + set, and the first write won). Each run's report rows are its own. The
    train job gets every split; nb_train learns from train and reports each split it was given."""
    k, c, t, x, _ = world(opener())
    rows = [{"n": i, "text": ("refund money card" if i % 2 else "login password reset") + f" t{i}",
             "label": "billing" if i % 2 else "account"} for i in range(40)]
    tix = c("data.load", bytes=json.dumps(rows), origin="file:tix.json", sensitivity="internal", does="synthetic rows for a test", line="tix")["raw"]
    c("module.define", in_=x, code=SPLIT, name="every_fourth")
    ds = c("run.go", in_=x, recipe=recipe(c, x, "every_fourth", cols={"n": "n"}), on=[tix], as_="dataset", line="tix_split")["set"]
    c("module.define", in_=x, code=SHIPPED["nb_train"].read_bytes(), name="nb_train")
    tr = recipe(c, x, "nb_train", cols={"text": "text", "label": "label"})
    ev = recipe(c, x, "exact_match", cols={"a": "text", "b": "label"})
    runs = []
    for _ in range(2):                                           # the smoke run, then the full train
        got = c("run.go", in_=x, recipe=tr, on=[ds], evals=[ev])
        land(k, got["job"])
        runs.append(got["run"])
    smoke, full = ({r["step"]: r for r in k.rec.table_rows("made.nb_train_report", bitt_run_hash=run)}[1] for run in runs)
    assert (float(smoke["train_acc"]), float(smoke["test_acc"])) == (1.0, 0.0), "the smoke run: one train row, one test row"
    assert (float(full["train_acc"]), float(full["test_acc"])) == (1.0, 1.0), "the full train reports its own test accuracy"
