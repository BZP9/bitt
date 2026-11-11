"""Recipes (foundation.md §C1, §M): this module, with these settings, on these columns; unversioned, the hash is the work, the label
derived. On every backend."""
import json

import pytest

from bitt import Kernel, Refused
from bitt.tools import packages
from bitt.tools.recipe import find, label

USR, A = "usr", "agent:t"
WORDS = (b'"""Count the words of a text."""\nBITT = {"kind": "derive"}\n\n\n'
         b'def words(text: str, *, sep: str = " ") -> int:\n    return len(text.split(sep))\n')
CONNECTOR = (b'"""Send the messages to an OpenAI-style endpoint."""\nBITT = {"kind": "generate"}\n\n\n'
             b'def chat(messages: list, *, url: str, model: str, temperature: float = 0) -> str:\n    return ""\n')
PROMPT = json.dumps({"bitt": {"does": "Summarize a ticket."}, "gives": {"summary": "text"},
                     "messages": [{"role": "user", "content": "Ticket {title}: {text}"}]})


@pytest.fixture(autouse=True)
def blobs(tmp_path, monkeypatch):
    monkeypatch.setenv("BITT_BLOBS", str(tmp_path / "blobs"))


def world(rec):
    k = Kernel(rec, packages=packages())

    def c(card, actor=A, **a):
        return k.call(card, {{"in_": "in"}.get(x, x): v for x, v in a.items()}, actor)
    t = c("control.goal.open_root", USR, problem="x", name="t")["goal"]
    x = c("control.cycle.open", in_=t, question="q", level="explore", because=[t])["cycle"]
    chat = c("module.define", in_=x, code=CONNECTOR, name="openai_chat")["module"]
    for n in ("qwen", "llama"):
        c("module.wrap", in_=x, module=chat, name=n, does=f"{n} served here.", params={"url": "http://box/v1", "model": n})
    c("artifact.add", in_=x, content=PROMPT, artifact_kind="prompt", name="summarize")
    c("module.define", in_=x, code=WORDS, name="words")
    return k, c, t, x


def test_a_recipe_fits_its_module(opener):
    k, c, t, x = world(opener())
    for a, why in (({"module": "words", "params": {"sepp": ","}}, r"has no params \['sepp'\]"),
                   ({"module": "words", "params": {"sep": 3}}, "param sep is text, not int"),
                   ({"module": "openai_chat", "artifacts": {"prompt": "summarize"}, "params": {"url": "u"}}, r"needs params \['model'\]"),
                   ({"module": "qwen"}, "fills its `prompt` role"),
                   ({"module": "qwen", "artifacts": {"prompt": "summarize", "rubric": "summarize"}}, r"has no role \['rubric'\]")):
        with pytest.raises(Refused, match=f"recipe.fits → fail.*{why}"):
            c("recipe.make", in_=x, **a, cols={"text": "body"})


def test_every_need_is_bound_and_nothing_else(opener):
    k, c, t, x = world(opener())
    for cols, why in ((None, r"unbound: \['text'\]"), ({"text": "body", "txt": "body"}, r"nothing reads \['txt'\]"),
                      ({"text": "body; drop"}, "not column names")):
        with pytest.raises(Refused, match=f"recipe.cols_bound → fail \\(.*{why}"):
            c("recipe.make", in_=x, module="words", **({} if cols is None else {"cols": cols}))
    with pytest.raises(Refused, match=r"unbound: \['title'\]"):                      # G2: a prompt slot with no column, at recipe time
        c("recipe.make", in_=x, module="qwen", artifacts={"prompt": "summarize"}, cols={"text": "body"})
    r = c("recipe.make", in_=x, module="qwen", artifacts={"prompt": "summarize"}, cols={"text": "body", "title": "qa.title"})["recipe"]
    assert k.node(r)["payload"]["cols"] == {"text": "body", "title": "qa.title"}


def test_the_hash_is_the_work(opener):
    k, c, t, x = world(opener())
    a = c("recipe.make", in_=x, module="words", cols={"text": "body"})["recipe"]
    b = c("recipe.make", "agent:other", in_=x, module="words", params={"sep": " "}, cols={"text": "body"}, why="the default, said")["recipe"]
    assert k.node(a)["spec_h"] == k.node(b)["spec_h"], "the default filled in: one setting is one work, whoever said it and why"
    t2 = c("control.goal.open_root", USR, problem="y", name="t2")["goal"]
    x2 = c("control.cycle.open", in_=t2, question="q", level="explore", because=[t2])["cycle"]
    other = c("recipe.make", in_=x2, module="words", cols={"text": "body"})["recipe"]
    assert k.node(other)["spec_h"] == k.node(a)["spec_h"], "the same work in another task"
    for diff in ({"params": {"sep": ","}, "cols": {"text": "body"}}, {"cols": {"text": "title"}}):
        assert k.node(c("recipe.make", in_=x, module="words", **diff)["recipe"])["spec_h"] != k.node(a)["spec_h"]
    m1 = k.node(a)["links"]["module"]
    c("module.define", in_=x, code=WORDS.replace(b"text.split(sep)", b"text.strip().split(sep)"), name="words")
    assert k.node(a)["links"]["module"] == m1, "pinned: a newer module version changes nothing until a new recipe (C11)"


def test_a_label_always_ends_in_its_hash(opener):
    k, c, t, x = world(opener())
    w = c("recipe.make", in_=x, module="words", cols={"text": "body"})["recipe"]
    h = lambda r: k.node(r)["spec_h"][:8]  # noqa: E731
    assert label(k, w) == f"words:{h(w)}", "the module, then the first 8 hex of the work"
    q = c("recipe.make", in_=x, module="qwen", artifacts={"prompt": "summarize"}, cols={"text": "body", "title": "title"})["recipe"]
    first = label(k, q)
    assert first == f"summarize:{h(q)}", "a generate recipe starts with its prompt"
    lm = c("recipe.make", in_=x, module="llama", artifacts={"prompt": "summarize"}, cols={"text": "body", "title": "title"})["recipe"]
    assert label(k, q) == first and label(k, lm) == f"summarize:{h(lm)}", "a second recipe of the same prompt changes no label"
    assert find(k, first, t) == q and find(k, label(k, lm), t) == lm, "a label reads back to its recipe"
    with pytest.raises(Refused, match=f"next: write one of summarize:{h(lm)}, summarize:{h(q)}"):
        find(k, "summarize", t)                                  # the base alone never resolves: the full labels, newest first
    with pytest.raises(Refused, match="always ends in its hash"):
        k.resolve("summarize", t, ["recipe"])
    n = c("recipe.make", in_=x, module="words", params={"sep": ";"}, cols={"text": "body"}, name="by_semicolon")["recipe"]
    assert label(k, n) == f"words:{h(n)}" and k.resolve("by_semicolon", t, ["recipe"])[0] == n, "an alias resolves; the label stays"
    assert k.resolve(first, t, ["recipe"])[0] == q, "a label is a ref wherever a recipe is wanted"
    assert k.resolve(first, t)[0] == q, "a label with `:` is a recipe's even where any kind is taken (plan arms)"
