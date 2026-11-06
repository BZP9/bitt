"""Every run counts per unit, a derive / check is per row, and anything across rows is a module that writes its own row (d15.md, D15):
no default aggregate, a win reads one row, a train reports what it declares. On every backend."""
import json
import subprocess
from pathlib import Path

import pytest

from bitt import Refused, sets, tables
from bitt.builtins import SHIPPED
from bitt.tools.run import land, one_row, status_of
from test_run import out_rows, recipe, world
from test_train import setup as train_setup

PRED = json.dumps({"bitt": {"does": "Say the text back."}, "messages": [{"role": "user", "content": "{text}"}]})
BILLING = b'"""Predict billing, always."""\nBITT = {"kind": "derive"}\n\n\ndef guess(text: str) -> str:\n    return "billing"\n'
LONGEST = (b'"""The longest text of the rows."""\nfrom typing import TypedDict\n\nBITT = {"kind": "check", "scope": "table", "reads": ["x"]}\n\n\n'
           b'class Longest(TypedDict):\n    longest: str\n\n\n'
           b'def longest(rows: list) -> Longest:\n    return {"longest": max((str(r["x"]) for r in rows), key=len)}\n')
EVAL = (b'"""Is the guess right for most tickets?"""\nBITT = {"kind": "pipeline", "win": "lo >= 0.1"}\n\n\n'
        b'def right(b, on):\n    v = b.run("exact_match", on=on, cols={"a": "guess", "b": "tix.label"})\n'
        b'    return b.run("rate", on=v, cols={"x": "exact_match"})\n')
BAD_TRAIN = (b'"""Train nothing, and report a number nobody declared."""\n'
             b'BITT = {"kind": "train", "reads": ["text"], "reports": {"acc": "number"}}\n\n\n'
             b'def train(job):\n    (job.output / "m.txt").write_text("x")\n    job.report(step=1, loss=0.5)\n')


def load(c, x, rows, line="tix"):
    return c("data.load", bytes=json.dumps(rows), origin=f"file:{line}.json", sensitivity="internal", does="synthetic rows for a test", line=line)["raw"]


def entries(k, run):
    return sets.entries(k.rec, k.rec.get_row("bitt.run_end", (run,))["out_set"])


def rate_of(k, c, x, check_run, col):
    return one_row(k, c("run.go", in_=x, recipe=recipe(c, x, "rate", cols={"x": col}), on=[check_run])["run"])


def echo(k, c, x, samples=1):
    c("artifact.add", in_=x, content=PRED, artifact_kind="prompt", name="pred")
    return recipe(c, x, "echo", artifacts={"prompt": "pred"}, cols={"text": "text"}, samples=samples)


def test_per_unit_stored_once(opener):
    k, c, t, x, _ = world(opener())
    raw = load(c, x, [{"id": i, "text": ["refund please", "reset login"][i % 2], "label": ["refund please", "reset login"][i % 2]}
                      for i in range(8)])
    gen = c("run.go", in_=x, recipe=echo(k, c, x), on=[raw], full="yes")["run"]
    assert len(k.rec.table_rows("made.pred")) == 2 and len(entries(k, gen)) == 8, "2 stored rows, one entry per unit"
    chk = c("run.go", in_=x, recipe=recipe(c, x, "exact_match", cols={"a": "pred", "b": "tix.label"}), on=[gen])["run"]
    r = rate_of(k, c, x, chk, "exact_match")
    assert (r["rate"], r["n"], r["hi"]) == (1.0, 8, 1.0) and 0.6 < r["lo"] < 0.7, "n counts units (Wilson 95% over 8)"


def test_same_text_different_labels(opener):
    k, c, t, x, _ = world(opener())
    raw = load(c, x, [{"id": 1, "text": "refund please", "label": "billing"}, {"id": 2, "text": "refund please", "label": "account"}])
    c("module.define", in_=x, code=BILLING, name="guess")
    pred = c("run.go", in_=x, recipe=recipe(c, x, "guess", cols={"text": "text"}), on=[raw], full="yes")["run"]
    chk = c("run.go", in_=x, recipe=recipe(c, x, "exact_match", cols={"a": "guess", "b": "tix.label"}), on=[pred])["run"]
    t_, rows = out_rows(k, chk)
    assert sorted(r["exact_match"] for r in rows) == [False, True], "each ticket's verdict against its own label"
    assert rate_of(k, c, x, chk, "exact_match")["rate"] == 0.5
    (p,) = k.rec.table_rows("made.guess")
    tickets = set()
    for r in rows:
        src = sets.sources_of(k.rec, t_, r["bitt_in_hash"])
        assert src["made.guess"] == [p["bitt_row_hash"]] and len(src["raw.tix"]) == 1, "a verdict links its prediction and its ticket"
        tickets |= set(src["raw.tix"])
    assert len(tickets) == 2, "each verdict row links its own ticket"


def test_samples_count_per_unit(opener):
    k, c, t, x, _ = world(opener())
    raw = load(c, x, [{"text": f"text {i}"} for i in range(4)])
    gen = c("run.go", in_=x, recipe=echo(k, c, x, samples=3), on=[raw], full="yes")["run"]
    assert [s for _, _, s in entries(k, gen)] == [0, 0, 0, 1, 1, 1, 2, 2, 2, 3, 3, 3], "unit i's samples follow it"
    c("module.define", in_=x, code=SHIPPED["nonempty"].read_bytes(), name="nonempty")
    chk = c("run.go", in_=x, recipe=recipe(c, x, "nonempty", cols={"value": "pred"}), on=[gen])["run"]
    assert rate_of(k, c, x, chk, "nonempty")["n"] == 12


def test_no_default_aggregate(opener):
    k, c, t, x, raw = world(opener())
    before = set(k.rec.all_specs())
    chk = c("run.go", in_=x, recipe=recipe(c, x, "length", cols={"text": "title"}), on=[raw])["run"]
    assert set(k.rec.all_specs()) - before == {"made.length", "made.length__src", "made.length__sets"}, "verdict rows, nothing else"
    assert k.rec.get_row("bitt.run_end", (chk,))["made"] == 12 and "bitt.metric" not in tables.FIXED
    root = Path(__file__).resolve().parents[1]
    hits = subprocess.run(["git", "grep", "-n", r"metrics_of\|bitt\.metric\|aggregate\.", "--", "src"], cwd=root, capture_output=True,
                          text=True).stdout
    assert hits == "", hits


def test_an_aggregate_writes_any_columns(opener):
    k, c, t, x, raw = world(opener())
    c("module.define", in_=x, code=LONGEST, name="longest")
    run = c("run.go", in_=x, recipe=recipe(c, x, "longest", cols={"x": "body"}), on=[raw])["run"]
    assert one_row(k, run) == {"longest": " ".join(["w"] * 12)} and len(k.rec.table_rows("made.longest")) == 1
    c("module.define", in_=x, code=b'"""The longest body wins."""\nBITT = {"kind": "pipeline", "win": "longest > 3"}\n\n\n'
                                   b'def longest_wins(b, on):\n    return b.run("longest", on=on, cols={"x": "body"})\n', name="longest_wins")
    with pytest.raises(Refused, match="not a number"):
        c("run.go", in_=x, recipe=recipe(c, x, "longest_wins"), on=[raw])


def test_a_win_reads_one_row(opener):
    k, c, t, x, _ = world(opener())
    raw = load(c, x, [{"id": i, "text": f"refund {i}", "label": "billing" if i % 4 else "account"} for i in range(8)])
    c("module.define", in_=x, code=BILLING, name="guess")
    pred = c("run.go", in_=x, recipe=recipe(c, x, "guess", cols={"text": "text"}), on=[raw], full="yes")["run"]
    c("module.define", in_=x, code=EVAL.replace(b'    return b.run("rate", on=v, cols={"x": "exact_match"})\n', b'    return v\n'),
      name="wrong_eval")
    with pytest.raises(Refused, match="the win reads one row"):
        c("run.go", in_=x, recipe=recipe(c, x, "wrong_eval"), on=[pred])
    c("module.define", in_=x, code=EVAL, name="right")
    d = k.node(c("run.go", in_=x, recipe=recipe(c, x, "right"), on=[pred])["decision"])["payload"]
    assert d["won"] and set(d["row"]) == {"rate", "lo", "hi", "n"} and (d["row"]["rate"], d["row"]["n"]) == (0.75, 8), \
        "the decision keeps the whole row it read"


def test_an_aggregate_is_reused(opener):
    k, c, t, x, raw = world(opener())
    chk = c("run.go", in_=x, recipe=recipe(c, x, "length", cols={"text": "body"}, params={"max": 6}), on=[raw])["run"]
    ag = recipe(c, x, "rate", cols={"x": "length_ok"})
    first = c("run.go", in_=x, recipe=ag, on=[chk])["run"]
    again = c("run.go", in_=x, recipe=ag, on=[chk])["run"]
    assert k.rec.get_row("bitt.run_end", (again,))["made"] == 0 and entries(k, again) == entries(k, first), "the same row again"


def test_a_train_reports_what_it_declares(opener):
    k, c, t, x, raw = world(opener())
    ds, tr, ev = train_setup(k, c, x, raw)
    full = c("run.go", in_=x, recipe=tr, on=[ds], evals=[ev], skip_smoke="yes")
    land(k, full["job"])
    (rep,) = k.rec.table_rows("made.nb_train_report", bitt_run_hash=full["run"])
    assert rep["step"] == 1 and rep["train_acc"] is not None and rep["test_acc"] is not None, "one row per step, the names it declares"
    c("module.define", in_=x, code=BAD_TRAIN, name="bad_train")
    bad = c("run.go", in_=x, recipe=recipe(c, x, "bad_train", cols={"text": "title"}), on=[ds], evals=[ev], skip_smoke="yes")
    assert "model" not in land(k, bad["job"]) and k.job_status(bad["job"]) == "failed" and status_of(k.rec, bad["run"]) == "failed"
    (fin,) = [e for e in k.kids(bad["job"], role="job", kind="event") if e["payload"]["card"] == "exec.job.finish"]
    assert "['loss']" in fin["payload"]["args"]["reason"] and "BITT[\\\"reports\\\"]" in json.dumps(fin["payload"]["args"]["reason"])


def test_rungs_count_units(opener):
    k, c, t, x, _ = world(opener())
    raw = load(c, x, [{"text": f"Text {i}"} for i in range(12)])
    gen = c("run.go", in_=x, recipe=echo(k, c, x, samples=2), on=[raw], full="yes")["run"]
    cl = recipe(c, x, "clean", cols={"text": "pred"})
    r1, r5 = c("run.go", in_=x, recipe=cl, on=[gen])["runs"]
    assert (len(entries(k, r1)), k.node(r5)["payload"]["rung"], len(entries(k, r5))) == (2, 10, 20), "a rung is k units, all their entries"
    c("module.define", in_=x, code=SHIPPED["nonempty"].read_bytes(), name="nonempty")
    chk = c("run.go", in_=x, recipe=recipe(c, x, "nonempty", cols={"value": "clean"}), on=[r5])["run"]
    assert rate_of(k, c, x, chk, "nonempty")["n"] == 20, "the sample's aggregate: 10 units × 2 samples"
