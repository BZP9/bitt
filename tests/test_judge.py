"""Judging rules that read lineage (rebuild.md §3): datasets' splits, group leaks, unit sets, frozen test sides, excluded rows (A22),
contamination. On every backend."""
import pytest

from bitt import Refused, sets
from bitt.builtins import SHIPPED
from bitt.tools.run import land
from test_run import recipe, world

USR = "usr"
BY_ROW = (b'"""Every third row is test, whatever its group."""\nBITT = {"kind": "derive", "writes": "selection", "reads": ["group"]}\n\n\n'
          b'def by_row(rows: list) -> list:\n    return [(i, "test" if i % 3 == 0 else "train") for i, r in enumerate(rows)]\n')
NO_SPLIT = (b'"""Keep every row, no split."""\nBITT = {"kind": "derive", "writes": "selection", "reads": ["n"]}\n\n\n'
            b'def keep(rows: list) -> list:\n    return [(i, None) for i, r in enumerate(rows)]\n')
FLIP = (b'"""Every row is train."""\nBITT = {"kind": "derive", "writes": "selection", "reads": ["n"]}\n\n\n'
        b'def flip(rows: list) -> list:\n    return [(i, "train") for i, r in enumerate(rows)]\n')


def test_a_dataset_is_split_by_its_group_over_its_units(opener):
    k, c, t, x, raw = world(opener())
    for name, code in (("by_row", BY_ROW), ("keep_all", NO_SPLIT)):
        c("module.define", in_=x, code=code, name=name)
    with pytest.raises(Refused, match="run.split_assigned → fail \\(12 members have no split"):
        c("run.go", in_=x, recipe=recipe(c, x, "keep_all", cols={"n": "qid"}), on=[raw], as_="dataset", line="qa")
    assert c("run.go", in_=x, recipe=recipe(c, x, "keep_all", cols={"n": "qid"}), on=[raw], as_="evalset", line="qa_eval")["set"], \
        "an evalset needs no split"
    with pytest.raises(Refused, match="run.group_leak → fail \\(group 'qid' values on several sides"):
        c("run.go", in_=x, recipe=recipe(c, x, "by_row", cols={"group": "qid"}), on=[raw], as_="dataset", line="qa")
    cleaned = c("run.go", in_=x, recipe=recipe(c, x, "clean", cols={"text": "title"}), on=[raw], full="yes")["run"]
    with pytest.raises(Refused, match="run.unit_set → fail.*a set over its units"):
        c("run.go", in_=x, recipe=recipe(c, x, "split", cols={"qid": "tickets.qid"}), on=[cleaned], as_="dataset", line="qa")


def test_a_new_version_keeps_its_test_side_and_excluded_rows_warn(opener):
    k, c, t, x, raw = world(opener())
    c("module.define", in_=x, code=FLIP, name="flip")
    c("module.define", in_=x, code=SHIPPED["exclude"].read_bytes(), name="exclude")
    v1 = c("run.go", in_=x, recipe=recipe(c, x, "split", cols={"qid": "qid"}), on=[raw], as_="dataset", line="qa")["set"]
    with pytest.raises(Refused, match="run.frozen_test → fail.*moved 6 rows"):
        c("run.go", in_=x, recipe=recipe(c, x, "flip", cols={"n": "qid"}), on=[v1], as_="dataset", line="qa", parent=v1)
    bad = [m for m, sp in sets.members(k.rec, k.node(v1)["payload"]["set"])][:2]
    c("data.exclude", USR, in_=x, set=v1, rows=[b[:10] for b in bad], because="duplicates of another ticket")
    v2 = c("run.go", in_=x, recipe=recipe(c, x, "exclude", params={"drop": bad}), on=[v1], as_="dataset", line="qa", parent=v1)
    assert len(sets.members(k.rec, k.node(v2["set"])["payload"]["set"])) == 10 and not v2.get("warnings")
    assert len(sets.members(k.rec, k.node(v1)["payload"]["set"])) == 12, "a version always means the same rows"
    again = c("run.go", in_=x, recipe=recipe(c, x, "split", cols={"qid": "qid"}, params={}, why="rebuilt"), on=[raw], as_="evalset",
              line="qa_all")
    assert any("2 rows marked excluded" in w for w in again.get("warnings", [])), "a later set that still holds them is warned"


def test_a_model_is_never_judged_on_its_training_rows(opener):
    k, c, t, x, raw = world(opener())
    ds = c("run.go", in_=x, recipe=recipe(c, x, "split", cols={"qid": "qid"}), on=[raw], as_="dataset", line="qa")["set"]
    for n in ("nb_train", "nb_predict"):
        c("module.define", in_=x, code=SHIPPED[n].read_bytes(), name=n)
    tr = recipe(c, x, "nb_train", cols={"text": "title", "label": "qid"})
    ev = recipe(c, x, "exact_match", cols={"a": "pred", "b": "tickets.qid"})
    land(k, c("run.go", in_=x, recipe=tr, on=[ds], evals=[ev], skip_smoke="yes", endpoint="nb_predict", line="clf")["job"])
    pred = c("run.go", in_=x, recipe=recipe(c, x, "clf_endpoint", cols={"text": "title"}), on=[raw], full="yes")["run"]
    with pytest.raises(Refused, match="run.contamination → fail \\(model .*clf was trained on 6 of the rows it is evaluated on"):
        c("run.go", in_=x, recipe=ev, on=[pred])
    c("control.ack", USR, in_=x, subject=pred, rule="run.contamination", reason="a smoke test of the wiring")
    scored = c("run.go", in_=x, recipe=ev, on=[pred])["run"]
    assert any(f["links"]["subject"] == scored and f["payload"]["rule"] == "run.contamination" for f in k.rec.find("flag")), \
        "acked: it runs, and the result is marked invalid"


def test_a_model_read_through_a_join_is_still_judged_on_what_it_saw(opener):
    """The rules walk the data path through every input (walk.md W2): predictions that reach a check as a join's lookup are still the
    model's outputs, so a model trained on those tickets is refused as it is when the check reads the predictions directly."""
    k, c, t, x, raw = world(opener())
    ds = c("run.go", in_=x, recipe=recipe(c, x, "split", cols={"qid": "qid"}), on=[raw], as_="dataset", line="qa")["set"]
    for n in ("nb_train", "nb_predict", "join"):
        c("module.define", in_=x, code=SHIPPED[n].read_bytes(), name=n)
    tr = recipe(c, x, "nb_train", cols={"text": "title", "label": "qid"})
    ev = recipe(c, x, "exact_match", cols={"a": "pred", "b": "qid"})
    land(k, c("run.go", in_=x, recipe=tr, on=[ds], evals=[ev], skip_smoke="yes", endpoint="nb_predict", line="clf")["job"])
    pred = c("run.go", in_=x, recipe=recipe(c, x, "clf_endpoint", cols={"text": "title"}), on=[raw], full="yes")["run"]
    joined = c("run.go", in_=x, recipe=recipe(c, x, "join", cols={"pred": "p.pred"}, params={"key": {"p": "title"}}), on=[raw],
               read={"p": pred})["run"]
    with pytest.raises(Refused, match="run.contamination → fail \\(model .*clf was trained on 6 of the rows it is evaluated on"):
        c("run.go", in_=x, recipe=ev, on=[joined])


def test_the_same_tickets_loaded_again_elsewhere_are_still_what_the_model_saw(opener):
    """#3: next week's export holds 6 tickets the model was trained on, loaded through another file into another line, with other ids
    and labels: by identity they are new rows, by what the model reads (the title) they are the same, so scoring on them is refused."""
    import json
    k, c, t, x, raw = world(opener())
    ds = c("run.go", in_=x, recipe=recipe(c, x, "split", cols={"qid": "qid"}), on=[raw], as_="dataset", line="qa")["set"]
    for n in ("nb_train", "nb_predict"):
        c("module.define", in_=x, code=SHIPPED[n].read_bytes(), name=n)
    tr = recipe(c, x, "nb_train", cols={"text": "title", "label": "qid"})
    ev = recipe(c, x, "exact_match", cols={"a": "pred", "b": "later.qid"})
    land(k, c("run.go", in_=x, recipe=tr, on=[ds], evals=[ev], skip_smoke="yes", endpoint="nb_predict", line="clf")["job"])
    train_titles = [k.rec.get_row("raw.tickets", (m,))["title"] for m, sp in sets.members(k.rec, k.node(ds)["payload"]["set"])
                    if sp == "train"]
    week = [{"qid": f"N{i}", "title": f"{ttl.upper()}  ", "body": "w"} for i, ttl in enumerate(train_titles)] + \
           [{"qid": "N99", "title": "a ticket nobody saw", "body": "w"}]
    later = c("data.load", bytes=json.dumps(week), origin="file:later.json", sensitivity="internal", does="synthetic rows for a test", line="later")["raw"]
    pred = c("run.go", in_=x, recipe=recipe(c, x, "clf_endpoint", cols={"text": "title"}), on=[later], full="yes")["run"]
    with pytest.raises(Refused, match=f"run.contamination → fail \\(model .*clf saw the same input as {len(train_titles)} of the rows it "
                                      "is evaluated on, by content \\(e.g. raw.later [0-9a-f]{12} = raw.tickets"):
        c("run.go", in_=x, recipe=ev, on=[pred])
    fresh = c("data.load", bytes=json.dumps(week[-1:]), origin="file:fresh.json", sensitivity="internal", does="synthetic rows for a test", line="fresh")["raw"]
    clean = c("run.go", in_=x, recipe=recipe(c, x, "clf_endpoint", cols={"text": "title"}), on=[fresh], full="yes")["run"]
    assert c("run.go", in_=x, recipe=recipe(c, x, "exact_match", cols={"a": "pred", "b": "fresh.qid"}), on=[clean])["run"], \
        "a ticket the model never saw is scored"


GUESS = (b'"""Guess a ticket\'s id from worked examples."""\nBITT = {"kind": "generate", "roles": {"shots": "examples"}}\n\n\n'
         b'def guess(title: str) -> str:\n    return "Q0"\n')


def test_examples_picked_from_an_evalset_are_never_judged_on_it(opener):
    """W4 / #8 (charter guarantee 8): few-shot examples made by a run from rows saw those rows; a model shown them is refused on them,
    as a model is refused on what it was trained on. Examples from other rows are fine."""
    import json
    k, c, t, x, raw = world(opener())
    c("module.define", in_=x, code=GUESS, name="guess")
    held = c("run.go", in_=x, recipe=recipe(c, x, "split", cols={"qid": "qid"}), on=[raw], as_="evalset", line="held")["set"]
    with pytest.raises(Refused, match="names its kind: --artifact-kind examples"):
        c("run.go", in_=x, recipe=recipe(c, x, "split", cols={"qid": "qid"}), on=[held], as_="artifact", line="shots")
    got = c("run.go", in_=x, recipe=recipe(c, x, "split", cols={"qid": "qid"}), on=[held], as_="artifact", line="shots",
            artifact_kind="examples")
    shots = got["artifact"]
    from bitt import blobs
    assert len(blobs.get(k.node(shots)["payload"]["content_blob"]).splitlines()) == 12, "its content is the rows picked"
    shown = c("run.go", in_=x, recipe=recipe(c, x, "guess", cols={"title": "title"}, artifacts={"shots": "shots"}), on=[held],
              full="yes")["run"]
    score = recipe(c, x, "exact_match", cols={"a": "guess", "b": "tickets.qid"})
    with pytest.raises(Refused, match="run.contamination → fail \\(examples .*shots were made from 12 of the rows it is evaluated on"):
        c("run.go", in_=x, recipe=score, on=[shown])
    other = c("data.load", bytes=json.dumps([{"qid": "Z1", "title": "another", "body": "w"}]), origin="file:o.json",
              sensitivity="internal", does="synthetic rows for a test", line="other")["raw"]
    elsewhere = c("run.go", in_=x, recipe=recipe(c, x, "split", cols={"qid": "qid"}), on=[other], as_="artifact", line="shots2",
                  artifact_kind="examples")["artifact"]
    fine = c("run.go", in_=x, recipe=recipe(c, x, "guess", cols={"title": "title"}, artifacts={"shots": "shots2"}), on=[held],
             full="yes")["run"]
    assert c("run.go", in_=x, recipe=score, on=[fine])["run"] and elsewhere, "examples from other rows: scored"


def test_a_lookup_read_again_for_a_new_unit_is_not_what_the_model_saw(opener):
    """#6 (story S1, 11-06): a joined row is one row per distinct input, so a customer's profile row is shared by every ticket of that
    customer, last week's and next week's; its source links reach them all. What a model saw is its units (the tickets it trained
    on), each down its own entry chain: a new ticket of a known customer is scored; the same ticket again is still refused."""
    import json
    k, c, t, x, raw = world(opener())
    for n in ("nb_train", "nb_predict", "join"):
        c("module.define", in_=x, code=SHIPPED[n].read_bytes(), name=n)
    prof = c("data.load", bytes=json.dumps([{"qid": f"Q{i}", "tier": ["gold", "basic"][i % 2]} for i in range(4)]), origin="file:p.json",
             sensitivity="internal", does="one profile per customer", line="profile")["raw"]
    ds = c("run.go", in_=x, recipe=recipe(c, x, "split", cols={"qid": "qid"}), on=[raw], as_="dataset", line="qa")["set"]
    jn = recipe(c, x, "join", cols={"tier": "p.tier"}, params={"key": {"p": "qid"}})
    joined = c("run.go", in_=x, recipe=jn, on=[ds], read={"p": prof})["run"]
    tr = recipe(c, x, "nb_train", cols={"text": "title", "label": "qid"})
    ev = recipe(c, x, "exact_match", cols={"a": "pred", "b": "qid"})
    land(k, c("run.go", in_=x, recipe=tr, on=[joined], evals=[ev], skip_smoke="yes", endpoint="nb_predict", line="clf")["job"])
    week = [{"qid": f"Q{i % 4}", "title": f"a new ticket {i}", "body": "w"} for i in range(8)]
    nxt = c("data.load", bytes=json.dumps(week), origin="file:n.json", sensitivity="internal", does="next week's tickets", line="nxt")["raw"]
    jw = c("run.go", in_=x, recipe=jn, on=[nxt], read={"p": prof})["run"]
    pred = c("run.go", in_=x, recipe=recipe(c, x, "clf_endpoint", cols={"text": "title"}), on=[jw], full="yes")["run"]
    assert c("run.go", in_=x, recipe=ev, on=[pred])["run"], "new tickets of known customers are scored: the profile is a feature"
    train = [k.rec.get_row("raw.tickets", (m,)) for m, sp in sets.members(k.rec, k.node(ds)["payload"]["set"]) if sp == "train"]
    again = c("data.load", bytes=json.dumps([{"qid": r["qid"], "title": r["title"], "body": r["body"]} for r in train[:2]]),
              origin="file:a.json", sensitivity="internal", does="two tickets again", line="again")["raw"]
    ja = c("run.go", in_=x, recipe=jn, on=[again], read={"p": prof})["run"]
    pa = c("run.go", in_=x, recipe=recipe(c, x, "clf_endpoint", cols={"text": "title"}), on=[ja], full="yes")["run"]
    with pytest.raises(Refused, match="run.contamination → fail"):
        c("run.go", in_=x, recipe=ev, on=[pa])
