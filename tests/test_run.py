"""One run for every module kind (foundation.md §C1): the ladder, rows made once per what they read, one table per output contract,
lineage, aggregates, selects, connectors. On every backend."""
import json
from pathlib import Path

import pytest

from bitt import Kernel, Refused, sets
from bitt.builtins import SHIPPED
from bitt.tools import packages
from bitt.tools.run import one_row, status_of

USR, A = "usr", "agent:t"
CLEAN = (b'"""Lower-case and strip a text."""\nBITT = {"kind": "derive"}\n\n\n'
         b'def clean(text: str, *, fail_on: str = "") -> str:\n    if fail_on and fail_on in text:\n        raise ValueError("bad row")\n'
         b'    return text.strip().lower()\n')
WORDS = b'"""Count the words of a text."""\nBITT = {"kind": "derive"}\n\n\ndef words(text: str) -> int:\n    return len(text.split())\n'
SPLIT = (b'"""Split rows by question id: every third id is test."""\nBITT = {"kind": "derive", "writes": "selection", "reads": ["qid"]}\n\n\n'
         b'def split(rows: list) -> list:\n    ids = sorted({r["qid"] for r in rows})\n'
         b'    return [(i, "test" if ids.index(r["qid"]) % 3 == 0 else "train") for i, r in enumerate(rows)]\n')
PLAIN = json.dumps({"bitt": {"does": "Echo the title."}, "messages": [{"role": "user", "content": "{title}"}]})
JSONP = json.dumps({"bitt": {"does": "Ask for JSON."}, "gives": {"label": "text"}, "messages": [{"role": "user", "content": "{title}"}]})


@pytest.fixture(autouse=True)
def blobs(tmp_path, monkeypatch):
    monkeypatch.setenv("BITT_BLOBS", str(tmp_path / "blobs"))


def world(rec, n=12, sensitivity="internal"):
    k = Kernel(rec, packages=packages())

    def c(card, actor=A, **a):
        return k.call(card, {{"in_": "in", "as_": "as"}.get(x, x): v for x, v in a.items()}, actor)
    t = c("control.goal.open_root", USR, problem="x", name="t")["goal"]
    x = c("control.cycle.open", in_=t, question="q", level="explore", because=[t])["cycle"]
    rows = [{"qid": f"Q{i % 4}", "title": f"  Title {i} ", "body": " ".join(["w"] * (i + 1))} for i in range(n)]
    raw = c("data.load", bytes=json.dumps(rows), origin="file:t.json", sensitivity=sensitivity, does="synthetic rows for a test", line="tickets")["raw"]
    for name, code in (("clean", CLEAN), ("words", WORDS), ("split", SPLIT)):
        c("module.define", in_=x, code=code, name=name)
    for name in ("length", "echo", "agreement", "exact_match", "rate", "mean"):
        c("module.define", in_=x, code=SHIPPED[name].read_bytes(), name=name)
    return k, c, t, x, raw


def recipe(c, x, module, **a):
    return c("recipe.make", in_=x, module=module, **a)["recipe"]


def out_rows(k, run):
    e = k.rec.get_row("bitt.run_end", (run,))
    t = k.rec.get_row("bitt.set", (e["out_set"],))["tbl"]
    return t, [k.rec.get_row(t, (m,)) for m, _ in sets.members(k.rec, e["out_set"])]


def test_the_ladder_makes_each_row_once(opener):
    """Owner 11-04: smoke (1 row: is it wired right? the kernel judges) → the sample (default 10: are the outputs as predicted? a
    person or the plan's eval looks) → all. One call climbs by itself from the smoke to the sample and stops there."""
    k, c, t, x, raw = world(opener())
    r = recipe(c, x, "clean", cols={"text": "title"})
    rung = lambda run: (k.node(run)["payload"]["rung"], *(k.rec.get_row("bitt.run_end", (run,))[f] for f in ("made", "reused")))  # noqa: E731
    first = c("run.go", in_=x, recipe=r, on=[raw])
    assert [rung(x_) for x_ in first["runs"]] == [(1, 1, 0), (10, 9, 1)] and first["run"] == first["runs"][-1], "smoke, then the sample: one call"
    assert [rung(c("run.go", in_=x, recipe=r, on=[raw])["run"]) for _ in range(2)] == [(12, 2, 10), (12, 0, 12)], "then all, then nothing new"
    run = first["run"]
    tbl, rows = out_rows(k, c("run.go", in_=x, recipe=r, on=[raw])["run"])
    assert tbl == "made.clean" and sorted(r_["clean"] for r_ in rows)[:2] == ["title 0", "title 1"]
    assert k.node(run)["payload"]["kind"] == "derive" and k.rec.get_row("bitt.run", (run,))["kind"] == "derive"


def test_a_recipe_declares_its_sample_and_full_still_smokes_first(opener):
    k, c, t, x, raw = world(opener())
    r = c("recipe.make", in_=x, module="clean", cols={"text": "title"}, sample_rows=4)["recipe"]
    assert [k.node(x_)["payload"]["rung"] for x_ in c("run.go", in_=x, recipe=r, on=[raw])["runs"]] == [1, 4], "its own sample: 4"
    r2 = recipe(c, x, "clean", cols={"text": "body"})
    out = c("run.go", in_=x, recipe=r2, on=[raw], full="yes")
    assert [k.node(x_)["payload"]["rung"] for x_ in out["runs"]] == [1, 12], "full: the smoke rung first, then all"
    assert [w for w in out["warnings"] if "without its sample of 10 looked at first" in w], "full past the sample is said"
    assert k.node(r)["spec_h"] == k.node(c("recipe.make", in_=x, module="clean", cols={"text": "title"})["recipe"])["spec_h"], \
        "the sample size is not the recipe's work: the same rows either way"


def test_one_table_per_output_contract_rows_reused_across_tasks(opener):
    k, c, t, x, raw = world(opener())
    a = recipe(c, x, "clean", cols={"text": "title"})
    c("run.go", in_=x, recipe=a, on=[raw], full="yes")
    t2 = c("control.goal.open_root", USR, problem="y", name="t2")["goal"]
    x2 = c("control.cycle.open", in_=t2, question="q", level="explore", because=[t2])["cycle"]
    again = c("run.go", in_=x2, recipe=recipe(c, x2, "clean", cols={"text": "title"}), on=[raw], full="yes")["run"]
    assert k.rec.get_row("bitt.run_end", (again,))["reused"] == 12, "the same work in another task reuses every row"
    other = c("run.go", in_=x, recipe=recipe(c, x, "clean", cols={"text": "body"}), on=[raw], full="yes")["run"]
    assert out_rows(k, other)[0] == "made.clean", "another binding writes the same contract: the same table, other rows"
    assert len(k.rec.table_rows("made.clean")) == 24
    assert {t_: len(v) for t_, v in sets.task_rows(k, t2).items()} == {"made.clean": 12}, "a task's rows: those its runs made or reused"
    assert {t_: len(v) for t_, v in sets.task_rows(k, t).items()} == {"made.clean": 24}
    if hasattr(k.rec, "db"):                                   # Postgres: `<task>.<name>` views read the same rows (A23)
        n = {sc: k.rec.db.execute(f"SELECT count(*) FROM {sc}.clean").fetchone()[0] for sc in ("t", "t2")}
        k.rec.db.commit()
        assert n == {"t": 24, "t2": 12}, n
    assert any("without its sample of 10 looked at first" in w["payload"]["detail"] for w in k.rec.find("warning")), "full is never silent"


def test_a_run_reads_up_its_lineage(opener):
    k, c, t, x, raw = world(opener())
    cleaned = c("run.go", in_=x, recipe=recipe(c, x, "clean", cols={"text": "title"}), on=[raw], full="yes")["run"]
    w = c("run.go", in_=x, recipe=recipe(c, x, "words", cols={"text": "tickets.body"}), on=[cleaned], full="yes")["run"]
    assert sorted(r["words"] for r in out_rows(k, w)[1])[:3] == [1, 2, 3], "body read from the raw row above each cleaned row"
    with pytest.raises(Refused, match=r"run.input_fits → fail \(text ← nope: no column 'nope'"):
        c("run.go", in_=x, recipe=recipe(c, x, "words", cols={"text": "nope"}), on=[cleaned])
    with pytest.raises(Refused, match="input_fits.*--on"):
        c("run.go", in_=x, recipe=recipe(c, x, "words", cols={"text": "body"}))


def test_a_failed_row_is_a_failed_run(opener):
    k, c, t, x, raw = world(opener(), n=3)
    r = recipe(c, x, "clean", cols={"text": "title"}, params={"fail_on": "2"})
    run = c("run.go", in_=x, recipe=r, on=[raw], full="yes")["run"]
    e = k.rec.get_row("bitt.run_end", (run,))
    assert (status_of(k.rec, run), e["made"], e["reused"], e["failed"]) == ("failed", 1, 1, 1), "the smoke rung made row 0; the rest failed one"
    assert "bad row" in k.rec.table_rows("bitt.run_error", bitt_run_hash=run)[0]["error"]
    assert any("rung 3 failed" in w["payload"]["detail"] for w in k.rec.find("warning"))
    for _ in range(3):
        last = c("run.go", in_=x, recipe=r, on=[raw], full="yes")["run"]
    assert "skipped" in k.rec.find("warning")[-1]["payload"]["detail"], "a row that failed 3 times is not called again"
    assert k.rec.get_row("bitt.run_end", (last,))["calls"] == 0


def test_a_failed_smoke_rung_stops_the_climb(opener):
    """Owner 11-04: the smoke rung asks "is it wired right?"; when its row fails, bitt does not go on to the sample."""
    k, c, t, x, raw = world(opener(), n=12)
    out = c("run.go", in_=x, recipe=recipe(c, x, "clean", cols={"text": "title"}, params={"fail_on": "0"}), on=[raw])
    assert "runs" not in out and k.node(out["run"])["payload"]["rung"] == 1 and status_of(k.rec, out["run"]) == "failed"


def test_a_check_makes_verdicts_and_an_aggregate_adds_them_up(opener):
    k, c, t, x, raw = world(opener())
    chk = recipe(c, x, "length", cols={"text": "body"}, params={"max": 6})
    run = c("run.go", in_=x, recipe=chk, on=[raw])["run"]
    assert k.node(run)["payload"]["rung"] == 12, "a check judges every row (no ladder)"
    assert [r["length_ok"] for r in out_rows(k, run)[1]].count(True) == 6, "per-row verdicts, and nothing else"
    m = one_row(k, c("run.go", in_=x, recipe=recipe(c, x, "rate", cols={"x": "length_ok"}), on=[run])["run"])
    assert m["rate"] == 0.5 and m["n"] == 12 and m["lo"] < 0.5 < m["hi"], "a rate carries its 95% interval"
    assert one_row(k, c("run.go", in_=x, recipe=recipe(c, x, "mean", cols={"x": "length"}), on=[run])["run"])["mean"] == 6.5
    again = c("run.go", in_=x, recipe=chk, on=[raw])["run"]
    assert k.rec.get_row("bitt.run_end", (again,))["made"] == 0, "the same work on the same set"
    agree = recipe(c, x, "agreement", cols={"a": "qid", "b": "qid"})
    assert one_row(k, c("run.go", in_=x, recipe=agree, on=[raw])["run"])["agreement"] == 1.0, "an aggregate"
    flagged = c("run.go", in_=x, recipe=recipe(c, x, "length", cols={"text": "title"}), on=[raw], invalid_if={"min_n": 50})["run"]
    (f,) = [f for f in k.rec.find("flag") if f["links"]["subject"] == flagged]
    assert "fewer than min_n 50" in f["payload"]["detail"], "too few rows: the result is marked invalid, not hidden"


def test_a_select_makes_a_named_dataset(opener):
    k, c, t, x, raw = world(opener())
    out = c("run.go", in_=x, recipe=recipe(c, x, "split", cols={"qid": "qid"}), on=[raw], as_="dataset", line="tickets_split")
    ds = out["set"]
    splits = [sp for _, sp in sets.members(k.rec, k.node(ds)["payload"]["set"])]
    assert splits.count("test") == 6 and len(splits) == 12 and k.node(ds)["payload"]["test_hash"]
    assert k.resolve("tickets_split", t)[0] == ds and k.node(ds)["links"]["run"] == out["run"]
    with pytest.raises(Refused, match="named line"):
        c("run.go", in_=x, recipe=recipe(c, x, "split", cols={"qid": "qid"}), on=[raw], as_="evalset")
    w = c("run.go", in_=x, recipe=recipe(c, x, "words", cols={"text": "body"}), on=[ds], full="yes")["run"]
    assert len(out_rows(k, w)[1]) == 12, "a dataset is an input like any set"


def test_a_connector_answers_a_prompt(opener):
    k, c, t, x, raw = world(opener(), n=3)
    c("artifact.add", in_=x, content=PLAIN, artifact_kind="prompt", name="echo_title")
    r = recipe(c, x, "echo", artifacts={"prompt": "echo_title"}, cols={"title": "title"})
    run = c("run.go", in_=x, recipe=r, on=[raw], full="yes")["run"]
    tbl, rows = out_rows(k, run)
    assert tbl == "made.echo_title", "a generate's rows live in its prompt's table"
    assert sorted(x["echo_title"] for x in rows) == ["  Title 0 ", "  Title 1 ", "  Title 2 "] and rows[0]["raw_text"] == rows[0]["echo_title"]
    c("artifact.add", in_=x, content=JSONP, artifact_kind="prompt", name="ask_json")
    bad = c("run.go", in_=x, recipe=recipe(c, x, "echo", artifacts={"prompt": "ask_json"}, cols={"title": "title"}), on=[raw], full="yes")["run"]
    assert status_of(k.rec, bad) == "failed" and "not a JSON object" in k.rec.table_rows("bitt.run_error", bitt_run_hash=bad)[0]["error"]


def test_an_endpoint_is_asked_and_its_key_never_stored(opener, tmp_path):
    from fake_openai import FakeOpenAI
    srv = FakeOpenAI(models=["tiny"], key="sekrit-123").start()
    try:
        k, c, t, x, raw = world(opener(), n=2)
        keyf = tmp_path / "key"
        keyf.write_text("sekrit-123\n")
        c("module.define", in_=x, code=SHIPPED["openai_chat"].read_bytes(), name="openai_chat")
        c("artifact.add", in_=x, content=PLAIN, artifact_kind="prompt", name="echo_title")
        for model, name in (("tiny", "tiny_box"), ("huge", "huge_box")):
            c("module.wrap", in_=x, module="openai_chat", name=name, does=f"{model} on the fake box.",
              params={"url": srv.url, "model": model, "key_file": str(keyf)})
        with pytest.raises(Refused, match=r"endpoint_serves → fail.*serves \['tiny'\], not 'huge'"):
            c("run.go", in_=x, recipe=recipe(c, x, "huge_box", artifacts={"prompt": "echo_title"}, cols={"title": "title"}), on=[raw])
        run = c("run.go", in_=x, recipe=recipe(c, x, "tiny_box", artifacts={"prompt": "echo_title"}, cols={"title": "title"}),
                on=[raw], full="yes")["run"]
        assert status_of(k.rec, run) == "done" and srv.auth[-1] == "Bearer sekrit-123"
        stored = json.dumps([n for n in k.rec.nodes.values()], default=str)
        jobs = "".join(p.read_text(errors="ignore") for p in Path(tmp_path / "jobs").rglob("*") if p.is_file())
        assert "sekrit-123" not in stored and "sekrit-123" not in jobs, "the key is read at call time, into the job's process only"
    finally:
        srv.stop()


def test_data_goes_only_where_it_may(opener, tmp_path, monkeypatch):
    (tmp_path / "envs.yaml").write_text("open_box:\n  type: local\n  max_sensitivity: public\n")
    monkeypatch.setenv("BITT_ENVS", str(tmp_path / "envs.yaml"))
    k, c, t, x, raw = world(opener(), n=2, sensitivity="company")
    r = recipe(c, x, "clean", cols={"text": "title"})
    with pytest.raises(Refused, match="run.sensitivity → fail.*takes data up to 'public'; the input is 'company'"):
        c("run.go", in_=x, recipe=r, on=[raw], env="open_box")
    assert c("run.go", in_=x, recipe=r, on=[raw])["run"], "the local env takes company data"


def test_a_person_run_stays_open_and_blocks_nothing(opener):
    k, c, t, x, raw = world(opener(), n=3)
    c("module.define", in_=x, code=SHIPPED["person"].read_bytes(), name="person")
    c("artifact.add", in_=x, content=JSONP, artifact_kind="prompt", name="ask_json")
    r = recipe(c, x, "person", artifacts={"prompt": "ask_json"}, cols={"title": "title"})
    run = c("run.go", in_=x, recipe=r, on=[raw], full="yes")["run"]
    assert status_of(k.rec, run) == "open" and len(k.node(run)["payload"]["asks"]) == 3, "nothing is called: a person answers"
    other = c("run.go", in_=x, recipe=recipe(c, x, "clean", cols={"text": "title"}), on=[raw], full="yes")["run"]
    assert status_of(k.rec, other) == "done", "an open person run blocks no other run"
    first = k.node(run)["payload"]["asks"][0]
    with pytest.raises(Refused, match="does not fit the prompt"):
        c("run.answer", in_=x, run=run, answers={first[:10]: "not json"})
    c("run.answer", USR, in_=x, run=run, answers={first[:10]: '{"label": "billing"}'})
    w = c("run.go", in_=x, recipe=recipe(c, x, "words", cols={"text": "label"}), on=[run], full="yes")
    assert len(out_rows(k, w["run"])[1]) == 1 and any("still open" in d for d in w.get("warnings", [])), \
        "what reads it sees the answers so far, marked partial"
    c("run.close", USR, in_=x, run=run)
    e = k.rec.get_row("bitt.run_end", (run,))
    assert (e["made"], e["failed"], status_of(k.rec, run)) == (1, 2, "done"), "unanswered rows are counted, never invented"
    with pytest.raises(Refused, match="person_open → fail \\(the run is closed"):
        c("run.answer", in_=x, run=run, answers={first[:10]: '{"label": "x"}'})


NOT_SEED_3 = b'"""Is the smoke run kept?"""\nBITT = {"kind": "check"}\n\n\ndef smoke_kept(skip_smoke: str = "") -> bool:\n    return skip_smoke != "yes"\n'


def test_a_policys_rule_applies_to_every_call_of_one_act(opener):
    k, c, t, x, raw = world(opener())
    c("module.define", in_=x, code=NOT_SEED_3, name="smoke_kept")
    g = recipe(c, x, "smoke_kept", cols={"skip_smoke": "skip_smoke"})
    c("control.policy", USR, in_=t, on_event="run.go", rule=g)
    r = recipe(c, x, "clean", cols={"text": "title"})
    with pytest.raises(Refused, match="refused run.go: smoke_kept is false for {'skip_smoke': 'yes'}"):
        c("run.go", in_=x, recipe=r, on=[raw], skip_smoke="yes")
    assert c("run.go", in_=x, recipe=r, on=[raw])["run"], "a run that keeps its smoke goes on"


NOTED = (b'"""Clean a text and say what was done."""\nfrom typing import TypedDict\n\nBITT = {"kind": "derive"}\n\n\n'
         b'class Clean(TypedDict):\n    clean: str\n\n\n'
         b'def noted(text: str) -> Clean:\n    return {"clean": text.strip(), "note": "stripped"}\n')
NOTED_TABLE = (b'"""One row per text, and a note."""\nBITT = {"kind": "derive", "scope": "table", "writes": {"clean": "text"}, "reads": ["text"]}'
               b'\n\n\ndef noted_table(rows: list) -> list:\n'
               b'    return [{"clean": r["text"].strip(), "note": "stripped", "bitt_from": [i]} for i, r in enumerate(rows)]\n')
SAYS = json.dumps({"bitt": {"does": "Reply with a label and a reason."}, "gives": {"label": "text"},
                   "messages": [{"role": "user", "content": '{"label": "{title}", "why": "it says so"}'}]})


def test_undeclared_columns_are_kept_and_warned(opener):
    """A11 (10-30): a column a module did not declare is kept in bitt_extra with one warning naming it, for derives, table derives and
    generates; it is never bound by a recipe."""
    k, c, t, x, raw = world(opener(), n=3)
    c("module.define", in_=x, code=NOTED, name="noted")
    c("module.define", in_=x, code=NOTED_TABLE, name="noted_table")
    c("artifact.add", in_=x, content=SAYS, artifact_kind="prompt", name="says")
    for r, col in ((recipe(c, x, "noted", cols={"text": "title"}), "note"), (recipe(c, x, "noted_table", cols={"text": "title"}), "note"),
                   (recipe(c, x, "echo", artifacts={"prompt": "says"}, cols={"title": "title"}), "why")):
        out = c("run.go", in_=x, recipe=r, on=[raw], full="yes")
        assert status_of(k.rec, out["run"]) == "done", "never refused for it"
        assert {row["bitt_extra"][col] for row in out_rows(k, out["run"])[1]} <= {"stripped", "it says so"}, "kept, per row, in bitt_extra"
        assert any(f"kept columns the module does not declare: ['{col}'] (in bitt_extra)" in w for w in out["warnings"]), "warned"
    with pytest.raises(Refused, match="bitt_\\* columns are bitt's"):
        recipe(c, x, "words", cols={"text": "bitt_extra"})


def test_a_wrap_with_its_prompt_fixed_is_a_connector(opener):
    """A wrap that fixes a connector's prompt (a router: the model + its prompt) runs as that connector: bitt renders the fixed prompt,
    and the rows land in the prompt's table (found by compose_basics: the run once failed looking for the module's own writes)."""
    k, c, t, x, raw = world(opener(), n=3)
    c("artifact.add", in_=x, content=PLAIN, artifact_kind="prompt", name="title_p")
    c("module.wrap", in_=x, module="echo", name="echo_title", does="echo, its prompt fixed.", artifacts={"prompt": "title_p"})
    run = c("run.go", in_=x, recipe=recipe(c, x, "echo_title", cols={"title": "title"}), on=[raw], full="yes")["run"]
    t_, rows = out_rows(k, run)
    assert t_ == "made.title_p" and sorted(r["title_p"] for r in rows) == ["  Title 0 ", "  Title 1 ", "  Title 2 "]


def test_the_fake_endpoint_answers_what_it_was_told():
    """conformance/fake_openai.py with answers: a message that holds a text gets its reply (an eval knows its accuracy); else it echoes."""
    import urllib.request
    from fake_openai import FakeOpenAI
    srv = FakeOpenAI(models=["tiny"], answers={"refund (case 01)": "billing"}).start()
    try:
        def ask(text):
            req = urllib.request.Request(srv.url + "/chat/completions", headers={"Content-Type": "application/json"},
                                         data=json.dumps({"model": "tiny", "messages": [{"role": "user", "content": text}]}).encode())
            return json.loads(urllib.request.urlopen(req, timeout=5).read())["choices"][0]["message"]["content"]
        assert ask("Which queue? refund (case 01)") == "billing" and ask("hello") == "hello"
    finally:
        srv.stop()
