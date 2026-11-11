"""The four types (foundation.md §B): modules, wraps and artifacts on the shelf, loaded data in raw; on every backend."""
import json

import pytest

from bitt import Kernel, Refused, names
from bitt.builtins import SHIPPED
from bitt.tools import packages

USR, A = "usr", "agent:t"
WORDS = b'"""Count the words of a text."""\nBITT = {"kind": "derive"}\n\n\ndef words(text: str) -> int:\n    return len(text.split())\n'
CONNECTOR = (b'"""Send the messages to an OpenAI-style endpoint."""\nBITT = {"kind": "generate"}\n\n\n'
             b'def chat(messages: list, *, url: str, model: str, temperature: float = 0) -> str:\n    return ""\n')
PROMPT = json.dumps({"bitt": {"does": "Summarize a ticket in one line."}, "gives": {"summary": "text"},
                     "messages": [{"role": "system", "content": "Be short."}, {"role": "user", "content": "Ticket: {text}"}]})


@pytest.fixture(autouse=True)
def blobs(tmp_path, monkeypatch):
    monkeypatch.setenv("BITT_BLOBS", str(tmp_path / "blobs"))


def world(rec):
    k = Kernel(rec, packages=packages())

    def c(card, actor=A, **a):
        return k.call(card, {{"in_": "in"}.get(x, x): v for x, v in a.items()}, actor)
    t = c("control.goal.open_root", USR, problem="x", name="t")["goal"]
    x = c("control.cycle.open", in_=t, question="q", level="explore", because=[t])["cycle"]
    return k, c, t, x


def test_a_module_is_its_function(opener):
    k, c, t, x = world(opener())
    m = c("module.define", in_=x, code=WORDS, name="words")["module"]
    n = k.node(m)
    h = n["payload"]["header"]
    assert (h["kind"], h["reads"], h["writes"], h["does"]) == ("derive", ["text"], {"words": "int"}, "Count the words of a text.")
    assert n["links"]["origin"] == x and n["task"] is None, "on the shelf: its cycle is kept as origin, it belongs to no task"
    assert names.label(k, m) == "lib/words" and k.resolve("words", t)[0] == m, "every task's short name"
    for code, why in ((WORDS.replace(b'"""Count the words of a text."""\n', b""), "one sentence"),
                      (WORDS.replace(b'"derive"', b'"check", "calls": "model"'), "a check calls no model"),
                      (WORDS.replace(b"text: str", b"text"), "annotate it"),
                      (b'"""Loop."""\nBITT = {"kind": "pipeline"}\n\n\ndef p(b, on):\n    while True:\n        b.run("x", on=on)\n',
                       "no `while`"),
                      (b"x = 1\n", "no `BITT")):
        with pytest.raises(Refused, match=f"module.header → fail.*{why}"):
            c("module.define", in_=x, code=code, name="other")
    assert not names.binding(k, "lib", "other"), "a refused module leaves no name"


def test_a_new_version_stays_on_its_line_and_kind(opener):
    k, c, t, x = world(opener())
    m1 = c("module.define", in_=x, code=WORDS, name="words")["module"]
    m2 = c("module.define", in_=x, code=WORDS.replace(b"text.split()", b"text.split(' ')"), name="words")["module"]
    assert names.line_of(k, m2) == m1 and k.node(m2)["links"]["prev"] == m1, "the same name again = the line's next version"
    assert k.resolve("words", t)[0] == m2, "a name without a version = the newest member"
    same = c("module.define", "agent:other", in_=x, code=WORDS, name="words2")["module"]
    assert k.node(same)["spec_h"] == k.node(m1)["spec_h"], "the same code is the same module, whoever adds it (its line is history)"
    with pytest.raises(Refused, match="line of derive modules"):
        c("module.define", in_=x, code=WORDS.replace(b'"derive"', b'"check"'), name="words")
    with pytest.raises(Refused, match="names a module"):
        c("artifact.add", in_=x, content=PROMPT, artifact_kind="prompt", name="words")
    assert k.node(c("module.define", in_=x, code=SHIPPED["length"].read_bytes(), name="length")["module"])["payload"]["builtin"]


def test_a_wrap_fixes_params_and_roles(opener):
    k, c, t, x = world(opener())
    chat = c("module.define", in_=x, code=CONNECTOR, name="openai_chat")["module"]
    assert k.node(chat)["payload"]["header"]["roles"] == {"prompt": "prompt"}, "a connector's main role is its prompt"
    q = c("module.wrap", in_=x, module=chat, name="qwen", does="Qwen on the Mac Studio.",
          params={"url": "http://box:8899/v1", "model": "qwen"})["wrap"]
    h = k.node(q)["payload"]["header"]
    assert h["kind"] == "generate" and set(h["params"]) == {"temperature"}, "a wrap is a module of its kind, minus what it fixes"
    assert k.node(q)["links"]["wraps"] == chat
    for params, why in (({"port": 1}, r"has no params \['port'\]"), ({"temperature": "hot"}, "is number, not str")):
        with pytest.raises(Refused, match=f"wrap_fits → fail.*{why}"):
            c("module.wrap", in_=x, module=chat, name="bad", does="x", params=params)
    runner = c("module.define", in_=x, code=SHIPPED["nb_predict"].read_bytes(), name="nb_predict")["module"]
    rubric = c("artifact.add", in_=x, content="be kind", artifact_kind="rubric", name="kind_rubric", does="What kind means.")["artifact"]
    with pytest.raises(Refused, match="takes a model artifact, not a rubric"):
        c("module.wrap", in_=x, module=runner, name="clf", does="x", artifacts={"file": rubric})
    weights = c("artifact.add", in_=x, content="{}", artifact_kind="model", name="weights", does="Weights from outside.")["artifact"]
    w = c("module.wrap", in_=x, module=runner, name="clf", does="The classifier.", artifacts={"file": "weights"})["wrap"]
    assert k.node(w)["payload"]["fixed"]["artifacts"] == {"file": weights} and weights in k.node(w)["links"]["artifacts"]


def test_an_artifact_is_content_with_a_contract(opener):
    k, c, t, x = world(opener())
    a = c("artifact.add", in_=x, content=PROMPT, artifact_kind="prompt", name="summarize")["artifact"]
    p = k.node(a)["payload"]
    assert p["contract"]["needs"] == ["text"] and set(p["contract"]["gives"]) == {"summary", "raw_text", "warn"}
    assert p["does"] == "Summarize a ticket in one line."
    with pytest.raises(Refused, match="artifact.parses → fail.*what it is for"):
        c("artifact.add", in_=x, content=PROMPT.replace('"bitt": {"does": "Summarize a ticket in one line."}, ', ""),
          artifact_kind="prompt", name="nodoes")
    with pytest.raises(Refused, match="artifact.parses → fail.*needs no column"):
        c("artifact.add", in_=x, content=PROMPT.replace("{text}", "text"), artifact_kind="prompt", name="noslot")
    with pytest.raises(Refused, match="--does"):
        c("artifact.add", in_=x, content="be kind", artifact_kind="rubric", name="r")
    a2 = c("artifact.add", in_=x, content=PROMPT.replace("Be short.", "Be brief."), artifact_kind="prompt", name="summarize")["artifact"]
    assert names.line_of(k, a2) == a
    with pytest.raises(Refused, match="line of prompt artifacts"):
        c("artifact.add", in_=x, content="x", artifact_kind="rubric", name="summarize", does="x")


def test_a_load_lands_rows_once(opener):
    k, c, t, x = world(opener())
    rows = [{"id": i, "Body Text": f"b{i}"} for i in range(3)]
    r1 = c("data.load", in_=x, bytes=json.dumps(rows), origin="file:t.json", sensitivity="internal", does="synthetic rows for a test", line="tickets")["raw"]
    assert sorted(r["body_text"] for r in k.rec.table_rows("raw.tickets")) == ["b0", "b1", "b2"], "headers get column names"
    assert k.node(r1)["links"]["during"] == x and k.node(r1)["task"] is None, "raw is no task's"
    r2 = c("data.load", bytes=json.dumps(rows + [{"id": 9, "Body Text": "b9"}]), origin="file:t2.json", sensitivity="internal",
           does="synthetic rows for a test", line="tickets")["raw"]
    assert len(k.rec.table_rows("raw.tickets")) == 4 and k.node(r2)["payload"]["new_rows"] == 1, "rows already there are not stored again"
    assert names.ref_of(k, r1) == "raw/tickets@1" and k.resolve("raw/tickets", t)[0] == r2
    with pytest.raises(Refused, match="is not a name"):
        c("data.load", bytes="[]", origin="f", sensitivity="public", does="synthetic rows for a test", line="Bad-Name")
    with pytest.raises(Refused, match="does"):                     # A24: data says what it is, as a module does
        c("data.load", bytes=json.dumps(rows), origin="f", sensitivity="public", line="nameless")


PARSE = (b'"""Read a pipe-separated file: one ticket per line, id|title."""\nBITT = {"kind": "load"}\n\n\n'
         b'def parse(data: bytes, *, sep: str = "|") -> list:\n'
         b'    return [dict(zip(("id", "title"), line.split(sep))) for line in data.decode().splitlines() if line.strip()]\n')


def test_a_loader_reads_the_file_in_a_job(opener):
    k, c, t, x = world(opener())
    c("module.define", in_=x, code=PARSE, name="parse_pipes")
    r = c("data.load", in_=x, bytes="1|first\n2|second\n", origin="file:t.txt", sensitivity="internal", does="synthetic rows for a test", line="piped",
          **{"with": "parse_pipes"})["raw"]
    assert sorted(x["title"] for x in k.rec.table_rows("raw.piped")) == ["first", "second"]
    p = k.node(r)["payload"]
    assert k.node(r)["links"]["with"] and set(p["bytes"]) == {"bytes_h", "n"} and "second" not in json.dumps(p), \
        "the file is kept as its hash; the loader is its lineage (A21)"
    with pytest.raises(Refused, match="takes a loader"):
        c("data.load", bytes="x", origin="f", sensitivity="public", does="synthetic rows for a test", line="other", **{"with": c("module.define", in_=x, code=WORDS,
                                                                                                    name="words")["module"]})
