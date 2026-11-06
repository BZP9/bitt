"""Replay gw: a gateway's reply drafts, told in the foundation's acts: prompts on a served model (a wrap of a connector), two prompts
in a row (a pipeline), a judge, a person's labels, rows excluded from a dataset, an eval that decides. Every refusal writes nothing.
Run: BITT_BACKEND=memory|postgres uv run python conformance/replay_gw.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

from backend import make_kernel
from harness import Harness

sys.path.insert(0, str(Path(__file__).parent))
from fake_openai import FakeOpenAI  # noqa: E402

from bitt import names, sets  # noqa: E402
from bitt.builtins import SHIPPED  # noqa: E402
from bitt.tools.recipe import find, label  # noqa: E402
from bitt.tools.run import status_of  # noqa: E402

E = make_kernel("gw")
H = Harness(E)
c, ok, refused = H.c, H.ok, H.refused
USR, A = "usr", "agent:gw"
srv = FakeOpenAI(models=["qwen-small"], key="gw-secret-7").start()
keyf = Path(tempfile.mkdtemp()) / "qwen.key"
keyf.write_text("gw-secret-7\n")


def prompt(does, text, gives=None):
    return json.dumps({"bitt": {"does": does}, **({"gives": gives} if gives else {}), "messages": [{"role": "user", "content": text}]})


def recipe(actor, in_, module, **a):
    return c("recipe.make", actor, in_=in_, module=module, **a)["recipe"]


POLISH = (b'"""Draft a reply, then polish it."""\nBITT = {"kind": "pipeline"}\n\n\n'
          b'def draft_and_polish(b, on, *, model: str = "qwen"):\n'
          b'    d = b.run("draft", on=on, with_=model, cols={"question": "question"})\n'
          b'    return b.run("polish", on=d, with_=model, cols={"text": "draft"})\n')
GRADE = (b'"""Grade replies: the judge says OK for most of them."""\nBITT = {"kind": "pipeline", "win": "lo >= 0.5"}\n\n\n'
         b'def grade(b, on, *, model: str = "qwen"):\n'
         b'    j = b.run("judge_reply", on=on, with_=model, cols={"reply": "polish"})\n'
         b'    v = b.run("says_ok", on=j, cols={"verdict": "judge_reply"})\n'
         b'    return b.run("rate", on=v, cols={"x": "says_ok"})\n')
SAYS_OK = b'"""Did the judge say OK?"""\nBITT = {"kind": "check"}\n\n\ndef says_ok(verdict: str) -> bool:\n    return "OK" in str(verdict)\n'
KEEP = (b'"""Keep every question, its thread decides the side."""\nBITT = {"kind": "derive", "writes": "selection", "reads": ["group"]}\n\n\n'
        b'def by_thread(rows: list) -> list:\n    return [(i, "test" if r["group"] in ("G0", "G3") else "train") for i, r in enumerate(rows)]\n')
QS = [{"qid": f"Q{i}", "thread": f"G{i % 5}", "question": f"Where is order {i}?"} for i in range(20)]

try:
    H.scene("roots: a task, its questions, a served model on the shelf")
    gw = c("control.goal.open_root", USR, problem="draft replies for the gateway", name="gw")["goal"]
    x = c("control.cycle.open", A, in_=gw, question="try prompts", level="explore", because=[gw])["cycle"]
    raw = c("data.load", A, in_=x, bytes=json.dumps(QS), origin="file:qs.json", sensitivity="internal", does="synthetic rows for a test", line="questions")["raw"]
    c("module.define", A, in_=x, code=SHIPPED["openai_chat"].read_bytes(), name="openai_chat")
    qwen = c("module.wrap", A, in_=x, module="openai_chat", name="qwen", does="qwen-small on the gateway box.",
             params={"url": srv.url, "model": "qwen-small", "key_file": str(keyf)})["wrap"]
    ok(E.node(qwen)["payload"]["header"]["kind"] == "generate", "an endpoint is a generate module: a wrap of a connector")
    c("module.wrap", A, in_=x, module="openai_chat", name="qwen_big", does="a model the box does not serve.",
      params={"url": srv.url, "model": "qwen-big", "key_file": str(keyf)})
    for name, text, gives in (("draft", "Reply to: {question}", None), ("polish", "Polished: {text}", None),
                              ("judge_reply", "OK? {reply}", None)):
        c("artifact.add", A, in_=x, content=prompt(f"The {name} prompt.", text, gives), artifact_kind="prompt", name=name)
    for name, code in (("draft_and_polish", POLISH), ("grade", GRADE), ("says_ok", SAYS_OK), ("by_thread", KEEP)):
        c("module.define", A, in_=x, code=code, name=name)
    for name in ("person", "agreement", "exclude", "rate"):
        c("module.define", A, in_=x, code=SHIPPED[name].read_bytes(), name=name)

    H.scene("1. a prompt on the served model: asked first, the key never stored")
    big = recipe(A, x, "qwen_big", artifacts={"prompt": "draft"}, cols={"question": "question"})
    refused("a model the endpoint does not serve", "run.endpoint_serves", lambda: c("run.go", A, in_=x, recipe=big, on=[raw]))
    refused("a prompt slot left unbound", "unbound: ['question']",
            lambda: c("recipe.make", A, in_=x, module="qwen", artifacts={"prompt": "draft"}))
    dr = recipe(A, x, "qwen", artifacts={"prompt": "draft"}, cols={"question": "question"})
    ok(label(E, dr) == f"draft:{E.node(dr)['spec_h'][:8]}" and label(E, big) != label(E, dr) and label(E, big).startswith("draft:"),
       "two recipes of one prompt: each label is the prompt, then its own hash (C10)")
    o1 = c("run.go", A, in_=x, recipe=dr, on=[raw])
    r1 = o1["run"]
    ok(status_of(E.rec, r1) == "done" and [E.node(r)["payload"]["rung"] for r in o1["runs"]] == [1, 10],
       "one call climbs the ladder by itself: the smoke rung (wired right?), then the sample of 10, and stops (owner 11-04)")
    ok(srv.auth and srv.auth[-1] == "Bearer gw-secret-7", "the key reached the endpoint")
    stored = json.dumps(list(E.rec.nodes.values()), default=str)
    jobs = "".join(p.read_text(errors="ignore") for p in Path(os.environ["BITT_JOBS"]).rglob("*") if p.is_file())
    ok("gw-secret-7" not in stored and "gw-secret-7" not in jobs, "and is in no node and no job file")
    got = sorted(r["draft"] for r in E.rec.table_rows("made.draft"))
    ok(len(got) == 10 and "Reply to: Where is order 0?" in got, "the replies land in their prompt's table")

    H.scene("2. two prompts in a row: a pipeline, its steps pinned")
    p = recipe(A, x, "draft_and_polish")
    ok(set(E.node(p)["payload"]["pins"]) == {"draft", "polish", "qwen"}, "every name its steps write, pinned at recipe time")
    p1 = c("run.go", A, in_=x, recipe=p, on=[raw])["run"]
    st = [E.rec.get_row("bitt.run_end", (s,)) for s in E.node(p1)["links"]["steps"]]
    ok([(s["made"], s["reused"]) for s in st] == [(10, 10), (19, 1)],
       "step 1 goes on to all, reusing the sample it had; step 2 smokes, then runs over all step 1 made")
    ok(E.rec.table_rows("made.polish")[0]["polish"].startswith("Polished: Reply to:"), "step 2 read step 1's output")
    full = c("run.go", A, in_=x, recipe=p, on=[raw], full="yes")
    ok(not any("without its sample" in w for w in full.get("warnings", [])), "full after the sample was looked at: nothing skipped, nothing said")
    replies = full["run"]

    H.scene("3. a judge and a check, an eval that decides")
    g1 = c("run.go", A, in_=x, recipe=recipe(A, x, "grade"), on=[replies])
    r1d = E.node(g1["decision"])["payload"]
    ok(r1d["row"]["n"] == 10 and r1d["row"]["lo"] < 0.75, "the judge on its sample: 10 units, a wide interval (a hint before all)")
    g = c("run.go", A, in_=x, recipe=recipe(A, x, "grade"), on=[replies], full="yes")
    d = E.node(g["decision"])["payload"]
    ok(d["won"] and d["row"]["n"] == 20 and d["row"]["lo"] >= 0.5, "the eval's rule over the rate's row: won, keeping the row it read")
    ok(any("a hint in this task" in w for w in g.get("warnings", [])), "a check nobody promoted: the decision is warned as a hint")

    H.scene("4. people label a sample; their agreement with the judge is measured")
    c("artifact.add", A, in_=x, content=prompt("Is this reply OK?", "Reply: {reply}", {"ok": "text"}), artifact_kind="prompt",
      name="ask_ok")
    lab = c("run.go", A, in_=x, recipe=recipe(A, x, "person", artifacts={"prompt": "ask_ok"}, cols={"reply": "polish"}), on=[replies],
            full="yes")["run"]
    asks = E.node(lab)["payload"]["asks"]
    ok(status_of(E.rec, lab) == "open" and len(asks) == 20, "20 rows wait for a person; nothing else waits on them")
    c("run.answer", USR, in_=x, run=lab, answers={a[:10]: json.dumps({"ok": "OK"}) for a in asks[:8]})
    c("run.close", USR, in_=x, run=lab)
    e = E.rec.get_row("bitt.run_end", (lab,))
    ok((e["made"], e["failed"]) == (8, 12), "closed: 8 answered, 12 counted unanswered, none invented")

    H.scene("5. a dataset, rows found bad, a new version without them (A22)")
    w = c("control.cycle.open", A, in_=gw, question="a test set of questions", level="working", because=[gw])["cycle"]
    sk = c("control.want", A, in_=w, want_kind="dataset", name="qs_split", contract={})["want"]
    c("control.plan", USR, in_=w, arms=[sk], win="threads apart", judged_by="person")
    v1 = c("run.go", A, in_=w, recipe=recipe(A, w, "by_thread", cols={"group": "thread"}), on=[raw], as_="dataset", fills=sk)["set"]
    val = c("control.validate", USR, in_=w, subject=v1, verdict="approve")["validation"]
    f = c("control.log.finding", A, in_=w, text="a clean split", evidence=[val], finding_kind="conclusion")["finding"]
    c("tag.make", A, in_=w, target=v1, tag="version", because=[f])
    c("control.act", USR, in_=w, outcome="iterate")
    sk2 = c("control.want", A, in_=w, want_kind="dataset", name="qs_split", contract={})["want"]
    c("control.plan", USR, in_=w, arms=[sk2], win="the same split without bad rows", judged_by="person")
    ok(E.cstate(w) == "WORK", "after its verdict the cycle iterates: a new plan, back to WORK")
    bad = [m for m, sp in sets.members(E.rec, E.node(v1)["payload"]["set"]) if sp == "test"][:2]
    c("data.exclude", USR, in_=w, set=v1, rows=bad, because="two questions were duplicates")
    v2 = c("run.go", A, in_=w, recipe=recipe(A, w, "exclude", params={"drop": bad}), on=[v1], as_="dataset", fills=sk2,
           parent=v1)["set"]
    ok(len(sets.members(E.rec, E.node(v2)["payload"]["set"])) == 18 and len(sets.members(E.rec, E.node(v1)["payload"]["set"])) == 20,
       "the new version lacks them; qs_split@1.0 still means its 20 rows")
    c("control.validate", USR, in_=w, subject=v2, verdict="pass")
    ok(E.cstate(w) == "JUDGE", "a person's pass measures it")
    refused("test rows removed: a major, a person's", "control.approval",
            lambda: c("tag.make", A, in_=w, target=v2, tag="version", because=[f]))
    c("control.validate", USR, in_=w, subject=v2, verdict="approve")
    ok(c("tag.make", A, in_=w, target=v2, tag="version", because=[f])["bump"] == "major" and names.ref_of(E, v2) == "gw/qs_split@2.0",
       "qs_split@2.0")
    again = c("run.go", A, in_=x, recipe=recipe(A, x, "by_thread", cols={"group": "thread"}, why="rebuilt"), on=[raw], as_="evalset",
              line="qs_all")
    ok(any("2 rows marked excluded" in x_ for x_ in again.get("warnings", [])), "a later set that still holds them is warned")
    ok(E.node(find(E, label(E, dr), gw))["spec_h"] == E.node(dr)["spec_h"], "a label reads back to its recipe (one work, whichever call made it)")
finally:
    srv.stop()
H.done()
