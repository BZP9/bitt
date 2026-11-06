"""Named table inputs and the shipped union (docs/v2/inputs.md J3): a table derive may name inputs besides its units (`read` roles);
a union merges the units with every `read` input, once per key, each row linked to every source row it stands for. On every backend."""
import json

import pytest

from bitt import Kernel, Refused, sets
from bitt.builtins import SHIPPED
from bitt.tools import header, packages

USR, A = "usr", "agent:t"
EMAIL = [{"ticket_id": f"T{i}", "text": f"ticket {i}"} for i in range(4)]
CHAT = [{"ticket_id": f"T{i}", "text": f"ticket {i}"} for i in (2, 3, 4, 5)]          # T2, T3 came in both ways
MERGE = (b'"""Tickets from email and chat, chat marked."""\nBITT = {"kind": "derive", "writes": {"ticket_id": "text", "via": "text"}}\n\n\n'
         b'def merge(rows: list, chat: list) -> list:\n'
         b'    return [{"ticket_id": r["ticket_id"], "via": "email", "bitt_from": i} for i, r in enumerate(rows)] + \\\n'
         b'           [{"ticket_id": r["ticket_id"], "via": "chat", "bitt_from": ["chat", i]} for i, r in enumerate(chat)]\n')


@pytest.fixture(autouse=True)
def blobs(tmp_path, monkeypatch):
    monkeypatch.setenv("BITT_BLOBS", str(tmp_path / "blobs"))
    monkeypatch.setenv("BITT_JOBS", str(tmp_path / "jobs"))


def world(rec, chat=CHAT):
    k = Kernel(rec, packages=packages())

    def c(card, actor=A, **a):
        return k.call(card, {{"in_": "in", "as_": "as"}.get(x, x): v for x, v in a.items()}, actor)
    t = c("control.goal.open_root", USR, problem="x", name="t")["goal"]
    x = c("control.cycle.open", in_=t, question="q", level="explore", because=[t])["cycle"]
    email = c("data.load", bytes=json.dumps(EMAIL), origin="file:email.json", sensitivity="internal", does="synthetic rows for a test", line="email")["raw"]
    ch = c("data.load", bytes=json.dumps(chat), origin="file:chat.json", sensitivity="internal", does="synthetic rows for a test", line="chat")["raw"]
    c("module.define", in_=x, code=SHIPPED["union"].read_bytes(), name="union")
    return k, c, x, email, ch


def out(k, run):
    e = k.rec.get_row("bitt.run_end", (run,))
    t = k.rec.get_row("bitt.set", (e["out_set"],))["tbl"]
    return t, [k.rec.get_row(t, (m,)) for m, _, _ in sets.entries(k.rec, e["out_set"])]


def test_a_union_keeps_each_row_once_and_links_both_sources(opener):
    k, c, x, email, chat = world(opener())
    r = c("recipe.make", in_=x, module="union", cols={}, params={})["recipe"]
    run = c("run.go", in_=x, recipe=r, on=[email], read={"chat": chat})["run"]
    t, rows = out(k, run)
    assert sorted(x["ticket_id"] for x in rows) == [f"T{i}" for i in range(6)], "T2 and T3 once each"
    both = next(x for x in rows if x["ticket_id"] == "T2")
    assert set(sets.sources_of(k.rec, t, both["bitt_in_hash"])) == {"raw.email", "raw.chat"}, "a deduped row links both sources"
    only = next(x for x in rows if x["ticket_id"] == "T0")
    assert set(sets.sources_of(k.rec, t, only["bitt_in_hash"])) == {"raw.email"}
    assert k.node(run)["payload"]["reads"] == {"chat": k.node(chat)["payload"]["set"]}, "the run records the version it read"
    e = k.rec.get_row("bitt.run_end", (run,))
    assert (e["rows_total"], e["made"]) == (8, 6)
    again = c("run.go", in_=x, recipe=r, on=[email], read={"chat": chat})["run"]
    assert k.rec.get_row("bitt.run_end", (again,))["made"] == 0, "the same inputs again remake nothing"


def test_a_union_key_merges_rows_equal_on_it(opener):
    k, c, x, email, chat = world(opener(), chat=[{"ticket_id": "T1", "text": "the same ticket, retyped"}])
    by_id = c("recipe.make", in_=x, module="union", cols={}, params={"key": ["ticket_id"]})["recipe"]
    _, rows = out(k, c("run.go", in_=x, recipe=by_id, on=[email], read={"chat": chat})["run"])
    assert [x["text"] for x in rows if x["ticket_id"] == "T1"] == ["ticket 1"], "one row per key: the units' row is read first"
    every = c("recipe.make", in_=x, module="union", cols={}, params={})["recipe"]
    _, rows = out(k, c("run.go", in_=x, recipe=every, on=[email], read={"chat": chat})["run"])
    assert len([x for x in rows if x["ticket_id"] == "T1"]) == 2, "no key: rows that differ in any column stay apart"


def test_a_union_is_refused_without_a_second_input_or_a_shared_column(opener):
    k, c, x, email, _ = world(opener())
    other = c("data.load", bytes=json.dumps([{"ticket_id": "T9"}]), origin="file:o.json", sensitivity="internal", does="synthetic rows for a test", line="other")["raw"]
    r = c("recipe.make", in_=x, module="union", cols={}, params={})["recipe"]
    with pytest.raises(Refused, match="--read <role>=<data>"):
        c("run.go", in_=x, recipe=r, on=[email])
    with pytest.raises(Refused, match="has no text"):
        c("run.go", in_=x, recipe=r, on=[email], read={"other": other})


def test_a_table_derive_reads_its_named_inputs(opener):
    k, c, x, email, chat = world(opener())
    c("module.define", in_=x, code=MERGE, name="merge")
    r = c("recipe.make", in_=x, module="merge", cols={}, params={})["recipe"]
    with pytest.raises(Refused, match="next: --read chat=<data>"):
        c("run.go", in_=x, recipe=r, on=[email])
    run = c("run.go", in_=x, recipe=r, on=[email], read={"chat": chat})["run"]
    t, rows = out(k, run)
    assert sorted((x["via"], x["ticket_id"]) for x in rows) == sorted([("email", f"T{i}") for i in range(4)]
                                                                       + [("chat", f"T{i}") for i in (2, 3, 4, 5)])
    chat_row = next(x for x in rows if x["via"] == "chat")
    assert set(sets.sources_of(k.rec, t, chat_row["bitt_in_hash"])) == {"raw.chat"}, "[role, index] links the named input's row"
    assert k.node(run)["payload"]["reads"] == {"chat": k.node(chat)["payload"]["set"]}


def test_only_a_table_derive_names_inputs():
    two = b'"""x"""\nBITT = {"kind": "derive"}\n\n\nclass R(TypedDict):\n    n: int\n\n\ndef f(rows: list, chat: list) -> R:\n    return {}\n'
    h, problem = header.parse(two)
    assert problem and "aggregate reads one input" in problem
    sel = b'"""x"""\nBITT = {"kind": "derive", "writes": "selection"}\n\n\ndef f(rows: list, chat: list) -> list:\n    return []\n'
    assert "select picks rows of one input" in header.parse(sel)[1]
    h, problem = header.parse(MERGE)
    assert problem is None and h["inputs"] == ["chat"], problem
