"""Replay vk: a ticket-queue classifier, told in the foundation's acts (docs/v2/foundation.md, scenarios.md).

A person opens the task; an agent builds a dataset in a data cycle, trains a model in a model cycle, judges it with an eval in a third,
tags what counts, and a second task (gw) reuses vk's versions. Every rule the story touches is asserted; every refusal writes nothing.
Run: BITT_BACKEND=memory|postgres uv run python conformance/replay_vk.py
"""
import json

from backend import make_kernel
from harness import Harness

from bitt import names, sets
from bitt.builtins import SHIPPED
from bitt.tools.recipe import label
from bitt.tools.artifact import places
from bitt.tools.run import land, one_row, status_of
from bitt.tools.tag import trust_of

E = make_kernel("vk")
H = Harness(E)
c, ok, refused = H.c, H.ok, H.refused
USR, A = "usr", "agent:vk"

CLEAN = (b'"""Lower-case and strip a ticket title."""\nBITT = {"kind": "derive"}\n\n\n'
         b'def clean(title: str) -> str:\n    return title.strip().lower()\n')
SPLIT = (b'"""Split tickets by their thread: every fourth thread is test."""\nBITT = {"kind": "derive", "writes": "selection", "reads": ["group"]}\n\n\n'
         b'def split_by_thread(rows: list) -> list:\n    ids = sorted({r["group"] for r in rows})\n'
         b'    return [(i, "test" if ids.index(r["group"]) % 4 == 0 else "train") for i, r in enumerate(rows)]\n')
BY_ROW = (b'"""Split tickets by row: every fourth row is test."""\nBITT = {"kind": "derive", "writes": "selection", "reads": ["group"]}\n\n\n'
          b'def split_by_row(rows: list) -> list:\n    return [(i, "test" if i % 4 == 0 else "train") for i, r in enumerate(rows)]\n')
TEST_SIDE = (b'"""Keep the test side of a dataset."""\nBITT = {"kind": "derive", "writes": "selection"}\n\n\n'
             b'def test_side(rows: list) -> list:\n    return [(i, "test") for i, r in enumerate(rows) if r["bitt_split"] == "test"]\n')
EVAL = (b'"""Score a prediction run against the queue each ticket was routed to."""\n'
        b'BITT = {"kind": "pipeline", "win": "lo >= 0.2"}\n\n\n'
        b'def queue_accuracy(b, on):\n    v = b.run("exact_match", on=on, cols={"a": "pred", "b": "tickets.queue"})\n'
        b'    return b.run("rate", on=v, cols={"x": "exact_match"})\n')
SAME = b'"""Do two labels agree exactly?"""\nBITT = {"kind": "check"}\n\n\ndef same(a: str, b: str) -> bool:\n    return a == b\n'
SRC = {"path": "mods/x.py", "repo": "vk", "commit": "c0ffee"}
QUEUES = ["billing", "login", "refund", "shipping"]
ROWS = [{"tid": f"T{i}", "thread": f"H{i // 2}", "title": f"  {QUEUES[(i // 2) % 4].title()} issue {i} ", "queue": QUEUES[(i // 2) % 4]}
        for i in range(48)]


def recipe(actor, in_, module, **a):
    return c("recipe.make", actor, in_=in_, module=module, **a)["recipe"]


def verdict(cyc, evidence):
    return c("control.log.finding", A, in_=cyc, text="it holds", evidence=evidence, finding_kind="conclusion")["finding"]


# ================================================================== roots
H.scene("roots: a person opens the task; the types go on the shelf")
vk = c("control.goal.open_root", USR, problem="route support tickets to their queue", name="vk")["goal"]
g1 = c("control.goal.open", USR, in_=vk, problem="a classifier as good as the routing team")["goal"]
refused("an agent opens a goal", "human_actor", lambda: c("control.goal.open", A, in_=vk, problem="mine"))
x0 = c("control.cycle.open", A, in_=g1, question="set up", level="explore", because=[g1])["cycle"]
raw = c("data.load", A, in_=x0, bytes=json.dumps(ROWS), origin="file:tickets.json", sensitivity="company", does="synthetic rows for a test", line="tickets")["raw"]
ok(len(E.rec.table_rows("raw.tickets")) == 48 and E.node(raw)["task"] is None, "48 rows into raw.tickets; raw is no task's")
refused("a load that does not say what the data is", "does", lambda: c("data.load", A, in_=x0, bytes=json.dumps(ROWS[:1]), origin="file:x.json", sensitivity="company", line="nameless"))
ok(E.node(raw)["payload"]["does"] == "synthetic rows for a test", "the import keeps what the data is (A24: found by it later)")
for name, code in (("clean", CLEAN), ("split_by_thread", SPLIT), ("split_by_row", BY_ROW), ("test_side", TEST_SIDE),
                   ("queue_accuracy", EVAL), ("same", SAME)):
    c("module.define", A, in_=x0, code=code, name=name, source=SRC)
for name in ("nb_train", "nb_predict", "exact_match", "agreement", "person", "echo", "rate", "join", "union"):
    c("module.define", A, in_=x0, code=SHIPPED[name].read_bytes(), name=name)
ok(E.node(E.resolve("exact_match", vk)[0])["payload"].get("builtin"), "a shipped module is builtin")
ok(E.node(E.resolve("clean", vk)[0])["links"]["origin"] == x0, "a module keeps where it was added (F18), and is no task's")
refused("a module that does not say what it does", "one sentence",
        lambda: c("module.define", A, in_=x0, code=CLEAN.replace(b'"""Lower-case and strip a ticket title."""\n', b""), name="nodoc"))

# ================================================================== scene 1: the data cycle
H.scene("1. a data cycle: a dataset split by thread, judged by a person, tagged")
w1 = c("control.cycle.open", A, in_=g1, question="which split?", level="working", because=[g1])["cycle"]
ok(E.cstate(w1) == "FRAME", "a working cycle frames before it works")
split = recipe(A, x0, "split_by_thread", cols={"group": "thread"})
refused("work before a plan", "locked in FRAME",
        lambda: c("run.go", A, in_=w1, recipe=split, on=[raw], as_="dataset", line="tickets_split"))
sk = c("control.want", A, in_=w1, want_kind="dataset", name="tickets_split", contract={})["want"]
c("control.plan", USR, in_=w1, arms=[sk], win="no thread on two sides", judged_by="person")
ok(E.cstate(w1) == "WORK", "a person's plan: WORK")
by_row = recipe(A, w1, "split_by_row", cols={"group": "thread"})
refused("a split by row leaks threads across sides", "run.group_leak",
        lambda: c("run.go", A, in_=w1, recipe=by_row, on=[raw], as_="dataset", fills=sk))
ds = c("run.go", A, in_=w1, recipe=split, on=[raw], as_="dataset", fills=sk)["set"]
ok(names.label(E, ds) == "vk/tickets_split", "the dataset takes the name its want gave it")
ok(E.arm_state(sk, E.latest_plan(w1)) == "filled", "filled, not yet measured")
c("control.validate", A, in_=w1, subject=ds, verdict="pass")
ok(E.arm_state(sk, E.latest_plan(w1)) == "filled", "an ungranted agent's pass measures nothing")
v1 = c("control.validate", USR, in_=w1, subject=ds, verdict="approve")["validation"]
ok(E.cstate(w1) == "JUDGE", "a person's approval measures the arm: JUDGE")
f1 = verdict(w1, [v1])
ok(E.cstate(w1) == "ACT", "a verdict: ACT")
out = c("tag.make", A, in_=w1, target=ds, tag="version", because=[f1])
ok(out["bump"] == "major" and names.ref_of(E, ds) == "vk/tickets_split@1.0", "the first version: 1.0, a major the person approved")
refused("a version is set once", "tag.once", lambda: c("tag.make", A, in_=w1, target=ds, tag="version", because=[f1]))
refused("an agent closes a working cycle", "act_allowed", lambda: c("control.act", A, in_=w1, outcome="close"))
c("control.grant", USR, in_=g1, to=A, acts=["close"], reason="routine closes are fine")
c("control.act", A, in_=w1, outcome="close")
ok(E.cstate(w1) == "CLOSED", "granted: the agent closes it")

# ================================================================== scene 2: the model cycle
H.scene("2. a model cycle: a train in the background, smoke first; the model is an artifact a run made")
w2 = c("control.cycle.open", A, in_=g1, question="does naive Bayes route well?", level="working", because=[f1])["cycle"]
skm = c("control.want", A, in_=w2, want_kind="artifact", name="clf", contract={})["want"]
c("control.plan", USR, in_=w2, arms=[skm], win="a model that lands", judged_by="person")
tr = recipe(A, w2, "nb_train", cols={"text": "title", "label": "queue"})
ev = recipe(A, w2, "exact_match", cols={"a": "pred", "b": "tickets.queue"})
refused("a train names its eval first", "run.has_eval", lambda: c("run.go", A, in_=w2, recipe=tr, on=[ds], fills=skm))
refused("company data to a public env", "run.sensitivity",
        lambda: c("run.go", A, in_=w2, recipe=tr, on=[ds], fills=skm, evals=[ev], env="public_only"))
smoke = c("run.go", A, in_=w2, recipe=tr, on=[ds], fills=skm, evals=[ev], endpoint="nb_predict", env="gpubox")
ok(E.node(smoke["run"])["payload"]["smoke"] and status_of(E.rec, smoke["run"]) == "open", "the first train is a smoke run, running")
ok("model" not in land(E, smoke["job"]), "a smoke run proves the wiring and makes no model")
full = c("run.go", A, in_=w2, recipe=tr, on=[ds], fills=skm, evals=[ev], endpoint="nb_predict", env="gpubox")
made = land(E, full["job"])
model, ep = made["model"], made["endpoint"]
ok(E.node(model)["payload"]["artifact_kind"] == "model" and E.node(model)["links"]["run"] == full["run"],
   "the model is an artifact made by the train run (E11)")
ok(names.label(E, model) == "vk/clf" and names.label(E, ep) == "vk/clf_endpoint", "named by its want; its endpoint wraps nb_predict")
ok([r["step"] for r in E.rec.table_rows("made.nb_train_report", bitt_run_hash=full["run"])] == [1],
   "the script's own score is reported (rows of its report table), never trusted")
ok(E.arm_state(skm, E.latest_plan(w2)) == "filled", "the model fills the arm")
pred = recipe(A, w2, "clf_endpoint", cols={"text": "title"})
ok(E.node(model)["payload"]["at"]["env"] == "gpubox" and "content_blob" not in E.node(model)["payload"],
   "the model stays on gpubox, recorded by its files' hashes, never copied into the store (E12)")
refused("using a model on a machine it is not on", "is not on env 'local'", lambda: c("run.go", A, in_=w2, recipe=pred, on=[raw], full="yes"))
c("artifact.copy", A, in_=w2, target=model, to="local")
ok(sorted(pl["env"] for pl in places(E, model)) == ["gpubox", "local"], "copied here, hashed on arrival: a second place (E12)")
on_all = c("run.go", A, in_=w2, recipe=pred, on=[raw], full="yes")["run"]
refused("scoring the model on rows it trained on", "run.contamination", lambda: c("run.go", A, in_=w2, recipe=ev, on=[on_all]))
held = c("run.go", A, in_=x0, recipe=recipe(A, x0, "test_side"), on=[ds], as_="evalset", line="tickets_test")["set"]   # data is made where a plan wants it
on_test = c("run.go", A, in_=w2, recipe=pred, on=[held], full="yes")["run"]
score = c("run.go", A, in_=w2, recipe=ev, on=[on_test])["run"]
m = one_row(E, c("run.go", A, in_=w2, recipe=recipe(A, w2, "rate", cols={"x": "exact_match"}), on=[score])["run"])
ok(m["n"] == 12 and m["lo"] is not None, f"scored on the 12 held-out rows: {m['rate']} (95% [{m['lo']}, {m['hi']}])")
c("control.validate", USR, in_=w2, subject=model, verdict="approve")
f2 = verdict(w2, [score])
loose_ds = c("run.go", A, in_=x0, recipe=split, on=[raw], as_="dataset", line="scratch_split")["set"]
loose_eval = c("run.go", A, in_=x0, recipe=recipe(A, x0, "test_side"), on=[loose_ds], as_="evalset", line="scratch_test")["set"]
c("control.validate", USR, in_=w2, subject=loose_eval, verdict="approve")
refused("a version of an evalset made from an untagged dataset", "tag.upstream_tagged",
        lambda: c("tag.make", A, in_=w2, target=loose_eval, tag="version", because=[f2]))
ok(names.version_of(E, model) is None, "the model is still unversioned (no version tag)")
c("control.validate", USR, in_=w2, subject=held, verdict="approve")
c("tag.make", A, in_=w2, target=held, tag="version", because=[f2])
ok(c("tag.make", A, in_=w2, target=model, tag="version", because=[f2])["bump"] == "first" and names.version_of(E, model) == "1.0",
   "the model is tagged once its data is")

# ================================================================== scene 3: an eval measures an arm
H.scene("3. an eval cycle: the plan's eval runs on each arm when it is filled, its decision measures it")
w3 = c("control.cycle.open", A, in_=g1, question="does clf beat the bar on held-out rows?", level="working", because=[f2])["cycle"]
c("control.plan", USR, in_=w3, arms=[pred], win="exact match above 0.2 with its interval", pipeline="queue_accuracy")
refused("a working arm an eval judges, run on a raw import (owner 11-04)", "run.arm_on_version",
        lambda: c("run.go", A, in_=w3, recipe=pred, on=[raw], full="yes"))
run3 = c("run.go", A, in_=w3, recipe=pred, on=[held], full="yes")["run"]
ds3 = [d for d in E.rec.find("decision") if run3 in d["links"]["subject"]]
ok(len(ds3) == 1 and ds3[0]["stamp"]["actor"].startswith("pipeline:"), "the plan's eval ran on the arm, as the plan's pipeline")
ok(ds3[0]["payload"]["row"]["n"] == 12, "the decision keeps the row it read")
ok(E.arm_state(pred, E.latest_plan(w3)) == "measured" and E.cstate(w3) == "JUDGE", "its decision measures the arm: JUDGE")
w3b = c("control.cycle.open", USR, in_=g1, question="does clf hold under the agent's own plan?", level="working", because=[f2])["cycle"]
p3b = c("control.plan", A, in_=w3b, arms=[pred], win="exact match above 0.2", pipeline="queue_accuracy")["plan"]
run3b = c("run.go", A, in_=w3b, recipe=pred, on=[held], full="yes")["run"]
ok(not [d for d in E.rec.find("decision") if run3b in d["links"]["subject"]], "an agent's plan is a proposal: its eval waits (owner 11-04)")
hand = c("run.go", A, in_=w3b, recipe=recipe(A, w3b, "exact_match", cols={"a": "pred", "b": "tickets.queue"}), on=[run3b], full="yes")
ok([m for m in hand.get("warnings", []) if "outside the plan's eval" in m], "a check by hand in a working cycle: warned, a hint (SOP Q5)")
c("control.validate", USR, in_=w3b, subject=p3b, verdict="approve")
ok([d for d in E.rec.find("decision") if run3b in d["links"]["subject"]] and E.cstate(w3b) == "JUDGE",
   "the person's approve runs it on the arm already filled: JUDGE")

pin_w = c("module.wrap", A, in_=x0, module="clean", name="clean_held", does="clean, on the held-out version only", pin={"on": held})["wrap"]
rp = recipe(A, x0, "clean_held", cols={"title": "title"})
refused("a wrap that pins the held-out version, run on the raw import (owner 11-04)", "run.pinned", lambda: c("run.go", A, in_=x0, recipe=rp, on=[raw]))
ok(c("run.go", A, in_=x0, recipe=rp, on=[held])["run"] and held in E.lineage(pin_w), "on the version it pins it runs; the pin is its lineage")

# ================================================================== scene 4: versions of a module
H.scene("4. versions: computed against the previous version tag; a module's first is the agent's, a major is a person's")
cl1 = E.resolve("clean", vk)[0]
r4 = c("run.go", A, in_=x0, recipe=recipe(A, x0, "clean", cols={"title": "title"}), on=[raw])["run"]
f4 = c("control.log.finding", A, in_=x0, text="clean works", evidence=[r4])["finding"]
refused("a module versioned on evidence over a raw import (owner 11-04)", "tag.evidence_versioned",
        lambda: c("tag.make", A, in_=x0, target=cl1, tag="version", because=[f4]))
r4 = c("run.go", A, in_=x0, recipe=recipe(A, x0, "clean", cols={"title": "title"}), on=[held])["run"]
f4 = c("control.log.finding", A, in_=x0, text="clean works on the held-out version", evidence=[r4])["finding"]
ok(c("tag.make", A, in_=x0, target=cl1, tag="version", because=[f4])["bump"] == "first" and E.resolve("clean@1.0", vk)[0] == cl1,
   "the first version of a module (1.0) is the agent's: no person's approve")
cl2 = c("module.define", A, in_=x0, code=CLEAN.replace(b".lower()", b".casefold()"), name="clean", source=SRC)["module"]
ok(c("tag.make", A, in_=x0, target=cl2, tag="version", because=[f4])["bump"] == "minor", "code only: a minor (1.1), an agent may tag it")
ok(E.resolve("clean@1.0", vk)[0] == cl1 and E.resolve("clean@1", vk)[0] == cl2, "@1.0 is that version; @1 the newest 1.x")
loose = c("module.define", A, in_=x0, code=CLEAN.replace(b"strip()", b"strip(' ')"), name="clean")["module"]
refused("a version of code not committed in git", "module.in_git",
        lambda: c("tag.make", A, in_=x0, target=loose, tag="version", because=[f4]))
c("tag.make", A, in_=x0, target=cl2, tag="alias", value="best")
ok(E.resolve("clean@best", vk)[0] == cl2, "an alias points at a version")
refused("an agent moves @live", "control.approval", lambda: c("tag.make", A, in_=x0, target=cl2, tag="alias", value="live"))

# ================================================================== scene 5: trust
H.scene("5. trust: a check is trusted only where an agreement was measured, and a person said so")
same = E.resolve("same", vk)[0]
loose_v = c("run.go", A, in_=x0, recipe=recipe(A, x0, "same", cols={"a": "queue", "b": "queue"}), on=[raw])["run"]
loose_a = c("run.go", A, in_=x0, recipe=recipe(A, x0, "agreement", cols={"a": "same", "b": "tickets.queue"}), on=[loose_v])["run"]
f_raw = c("control.log.finding", A, in_=x0, text="agrees on raw", evidence=[loose_a])["finding"]
refused("trust on an agreement measured over a raw import (owner 11-04)", "tag.evidence_versioned",
        lambda: c("tag.make", USR, in_=x0, target=same, tag="trust", value="trusted", agreement=loose_a, because=[f_raw]))
verdicts = c("run.go", A, in_=x0, recipe=recipe(A, x0, "same", cols={"a": "queue", "b": "queue"}), on=[held])["run"]
agree = c("run.go", A, in_=x0, recipe=recipe(A, x0, "agreement", cols={"a": "same", "b": "tickets.queue"}), on=[verdicts])["run"]
f5 = c("control.log.finding", A, in_=x0, text="same agrees with routing", evidence=[agree])["finding"]
refused("an agent promotes a check", "control.approval",
        lambda: c("tag.make", A, in_=x0, target=same, tag="trust", value="trusted", because=[f5], agreement=agree))
c("control.validate", USR, in_=x0, subject=same, verdict="approve")
c("tag.make", USR, in_=x0, target=same, tag="trust", value="trusted", because=[f5], agreement=agree)
ok(trust_of(E, same, vk) == "trusted", "trusted in vk")

# ================================================================== scene 6: another task reuses vk's versions
H.scene("6. gw reuses vk's tagged dataset; its own trust and intent stay its own")
gw = c("control.goal.open_root", USR, problem="route the gateway's tickets", name="gw")["goal"]
xg = c("control.cycle.open", A, in_=gw, question="reuse vk's split", level="explore", because=[gw])["cycle"]
ok(E.resolve("vk/tickets_split@1.0", gw)[0] == ds, "another task's version, written in full")
ok(trust_of(E, same, gw) == "hint", "trust is per task: a hint in gw (D16)")
rg = c("run.go", A, in_=xg, recipe=recipe(A, xg, "clean@1.0", cols={"title": "title"}), on=["vk/tickets_split@1.0"], full="yes")
ok(E.rec.get_row("bitt.run_end", (rg["run"],))["reused"] >= 1, "the same work in gw reuses vk's rows")
ok(not [w for w in rg.get("warnings", []) if "not a version" in w], "reading vk's version warns nothing (#4)")
rl = c("run.go", A, in_=xg, recipe=recipe(A, xg, "clean@1.0", cols={"title": "title"}), on=[loose_ds], full="yes")
ok(any("is task vk's and not a version" in w for w in rl.get("warnings", [])), "reading vk's unversioned scratch split warns: it may change")
owners = c("data.load", A, in_=xg, bytes=json.dumps([{"queue": q, "owner": f"team-{q}"} for q in QUEUES]), origin="file:owners.json",
           sensitivity="internal", does="synthetic rows for a test", line="owners")["raw"]
jn = recipe(A, xg, "join", cols={"owner": "owners.owner"}, params={"key": {"owners": "queue"}})
jr = c("run.go", A, in_=xg, recipe=jn, on=["vk/tickets_split@1.0"], read={"owners": owners})["run"]
units = sets.entries(E.rec, E.node(ds)["payload"]["set"])
got = sets.entries(E.rec, E.rec.get_row("bitt.run_end", (jr,))["out_set"])
ok([src for _, _, src in got] == list(range(len(units))) and [sp for _, sp, _ in got] == [sp for _, sp, _ in units],
   "a join keeps vk's units and their splits: entry i is unit i (docs/v2/inputs.md)")
jt = E.rec.get_row("bitt.set", (E.rec.get_row("bitt.run_end", (jr,))["out_set"],))["tbl"]
ok(set(sets.sources_of(E.rec, jt, E.rec.get_row(jt, (got[0][0],))["bitt_in_hash"])) == {"raw.tickets", "raw.owners"},
   "a joined row links its ticket and the owner row it read")
ok(owners in E.lineage(jr) and raw in E.lineage(jr), "a join's lookup is lineage, like its units: one walker follows every input (walk.md)")
lr = c("run.go", A, in_=xg, recipe=recipe(A, xg, "same", cols={"a": "owner", "b": "queue"}), on=[jr], full="yes")["run"]
ok(E.rec.get_row("bitt.run_end", (lr,))["rows_total"] == len(units), "a later step reads the joined column and the ticket's own, per unit")
hj = recipe(A, xg, "join", cols={"before": "past.tid"}, params={"key": {"past": "queue"}, "many": ["past"], "asof": {"past": ["tid", "tid"]}})
hr = c("run.go", A, in_=xg, recipe=hj, on=["vk/tickets_split@1.0"], read={"past": raw})["run"]
hs = E.rec.get_row("bitt.run_end", (hr,))["out_set"]
first = E.rec.get_row(E.rec.get_row("bitt.set", (hs,))["tbl"], (sets.entries(E.rec, hs)[0][0],))
unit0 = E.rec.get_row("raw.tickets", (units[0][0],))
ok(first["before"] == sorted([r["tid"] for r in ROWS if r["queue"] == unit0["queue"] and r["tid"] < unit0["tid"]]),
   "as of each ticket: only the earlier tickets of its queue, oldest first (many + asof)")
chat = c("data.load", A, in_=xg, bytes=json.dumps(ROWS[:3] + [{**ROWS[0], "tid": f"C{i}"} for i in range(2)]), origin="file:chat.json",
         sensitivity="company", does="synthetic rows for a test", line="chat")["raw"]
ur = c("run.go", A, in_=xg, recipe=recipe(A, xg, "union", params={"key": ["tid"]}), on=[raw], read={"chat": chat})["run"]
ue = E.rec.get_row("bitt.run_end", (ur,))
ut = E.rec.get_row("bitt.set", (ue["out_set"],))["tbl"]
t0 = next(r for r in E.rec.table_rows(ut) if r["tid"] == "T0")
ok((ue["rows_total"], ue["made"]) == (len(ROWS) + 5, len(ROWS) + 2) and
   set(sets.sources_of(E.rec, ut, t0["bitt_in_hash"])) == {"raw.tickets", "raw.chat"},
   "a union keeps each ticket once by tid, and a ticket that came both ways links both sources (inputs.md J3)")
wg = c("control.cycle.open", A, in_=gw, question="adopt vk's want", level="working", because=[gw])["cycle"]
refused("a plan on another task's want", "task_boundary",
        lambda: c("control.plan", USR, in_=wg, arms=[sk], win="x", judged_by="person"))

# ================================================================== scene 7: a person labels; policies; park
H.scene("7. a person labels without blocking anything; a policy guards a task; park and resume")
c("artifact.add", A, in_=x0, content=json.dumps({"bitt": {"does": "Which queue does this ticket belong to?"}, "gives": {"label": "text"},
                                                 "messages": [{"role": "user", "content": "{title}"}]}), artifact_kind="prompt", name="ask_queue")
lab = c("run.go", A, in_=x0, recipe=recipe(A, x0, "person", artifacts={"prompt": "ask_queue"}, cols={"title": "title"}), on=[held],
        full="yes")["run"]
ok(status_of(E.rec, lab) == "open", "a person run stays open")
ok(status_of(E.rec, c("run.go", A, in_=x0, recipe=recipe(A, x0, "clean", cols={"title": "title"}), on=[held], full="yes")["run"]) == "done",
   "and blocks no other run (C9)")
c("module.define", A, in_=x0, code=b'"""Is the smoke run kept?"""\nBITT = {"kind": "check"}\n\n\n'
  b'def smoke_kept(skip_smoke: str = "") -> bool:\n    return skip_smoke != "yes"\n', name="smoke_kept")
c("control.policy", USR, in_=vk, on_event="run.go", rule=recipe(A, x0, "smoke_kept", cols={"skip_smoke": "skip_smoke"}))
refused("a train that skips its smoke here", "smoke_kept is false", lambda: c("run.go", A, in_=x0, recipe=tr, on=[ds], evals=[ev], skip_smoke="yes"))
c("control.act", A, in_=x0, outcome="park", reason="waiting on labels")
cl = recipe(A, w3, "clean", cols={"title": "title"})
refused("work in a parked cycle", "locked in PARKED", lambda: c("run.go", A, in_=x0, recipe=cl, on=[raw]))
c("control.act", A, in_=x0, outcome="resume")
ok(E.cstate(x0) == "EXPLORE", "resumed")

# ================================================================== scene 8: probes
H.scene("8. probes: each is refused, nothing is written")
refused("a recipe that leaves a read unbound", "unbound", lambda: c("recipe.make", A, in_=x0, module="clean"))
nope = recipe(A, x0, "clean", cols={"title": "nope"})
refused("a column the input does not have", "run.input_fits", lambda: c("run.go", A, in_=x0, recipe=nope, on=[raw]))
refused("an input outside the card", "not in the contract", lambda: c("run.go", A, in_=x0, recipe=tr, on=[ds], bogus=1))
refused("an alias that looks like a version", "an alias is a name", lambda: c("tag.make", A, in_=x0, target=cl2, tag="alias", value="9"))
refused("an agent approves", "can_approve", lambda: c("control.validate", A, in_=x0, subject=cl2, verdict="approve"))
ok(sets.members(E.rec, E.node(ds)["payload"]["set"]) and label(E, pred, vk) == f"clf_endpoint:{E.node(pred)['spec_h'][:8]}",
   "a recipe's label is its module's here, then its hash")
c("artifact.add", A, in_=x0, content=json.dumps({"bitt": {"does": "Repeat the title."}, "messages": [{"role": "user", "content": "{title}"}]}),
  artifact_kind="prompt", name="echo_title")
drafts = c("run.go", A, in_=x0, recipe=recipe(A, x0, "echo", artifacts={"prompt": "echo_title"}, cols={"title": "title"}), on=[raw],
           full="yes")["run"]
judged = c("run.go", A, in_=x0, recipe=recipe(A, x0, "clf_endpoint", cols={"text": "echo_title"}), on=[drafts], full="yes")["run"]
refused("judging with a model trained on what it judges", "run.leak", lambda: c("run.go", A, in_=x0, recipe=ev, on=[judged]))
seen = c("run.go", A, in_=x0, recipe=pred, on=[raw], full="yes")["run"]
via = c("run.go", A, in_=x0, recipe=recipe(A, x0, "join", cols={"pred": "p.pred"}, params={"key": {"p": "tid"}}), on=[raw],
        read={"p": seen})["run"]
score = recipe(A, x0, "exact_match", cols={"a": "pred", "b": "queue"})
refused("scoring a model on its training rows, its predictions joined in as a lookup", "run.contamination",
        lambda: c("run.go", A, in_=x0, recipe=score, on=[via]))
seen_rows = [E.rec.get_row("raw.tickets", (m,)) for m, sp in sets.members(E.rec, E.node(ds)["payload"]["set"]) if sp == "train"][:6]
week = c("data.load", A, in_=x0, bytes=json.dumps([{"tid": f"W{i}", "thread": f"W{i}", "title": r["title"].strip(), "queue": "billing"}
                                                   for i, r in enumerate(seen_rows)]), origin="file:next_week.json", sensitivity="company",
         does="synthetic rows for a test", line="next_week")["raw"]
on_week = c("run.go", A, in_=x0, recipe=pred, on=[week], full="yes")["run"]
week_score = recipe(A, x0, "exact_match", cols={"a": "pred", "b": "next_week.queue"})
refused("next week's export: 6 tickets the model trained on, loaded again with new ids (#3: by content)", "saw the same input as 6",
        lambda: c("run.go", A, in_=x0, recipe=week_score, on=[on_week]))
c("module.define", A, in_=x0, code=b'"""Guess a queue from worked examples."""\nBITT = {"kind": "generate", "roles": {"shots": "examples"}}\n\n\n'
  b'def guess(title: str) -> str:\n    return "billing"\n', name="guess")
shots = c("run.go", A, in_=x0, recipe=split, on=[held], as_="artifact", line="few_shots", artifact_kind="examples")["artifact"]
ok(E.node(shots)["payload"]["artifact_kind"] == "examples" and E.node(shots)["links"]["run"], "a select makes an examples artifact, linked to its run (W4)")
guessed = c("run.go", A, in_=x0, recipe=recipe(A, x0, "guess", cols={"title": "title"}, artifacts={"shots": "few_shots"}), on=[held],
            full="yes")["run"]
guess_score = recipe(A, x0, "exact_match", cols={"a": "guess", "b": "tickets.queue"})
refused("scoring on the evalset the few-shot examples were picked from (W4, charter guarantee 8)", "were made from",
        lambda: c("run.go", A, in_=x0, recipe=guess_score, on=[guessed]))
twice = c("data.load", A, in_=xg, bytes=json.dumps([{"queue": "login", "owner": "a"}, {"queue": "login", "owner": "b"}]),
          origin="file:owners2.json", sensitivity="internal", does="synthetic rows for a test", line="owners2")["raw"]
refused("a lookup whose key repeats", "owners has 2 rows for queue 'login'",
        lambda: c("run.go", A, in_=xg, recipe=jn, on=[raw], read={"owners": twice}))
refused("a second input on a derive", "join it first", lambda: c("run.go", A, in_=x0, recipe=cl, on=[raw], read={"owners": owners}))
if hasattr(E.rec, "db"):                                         # W5: SQL walks the same record the walker does, on every node
    from bitt.walk import Walk
    w, off = Walk(E), []
    for nid in list(E.rec.nodes):
        up = {r[0] for r in E.rec.db.execute("SELECT id FROM bitt.lineage(%s)", (nid,)).fetchall()}
        down = {r[0] for r in E.rec.db.execute("SELECT id FROM bitt.downstream(%s)", (nid,)).fetchall()}
        off += [nid] if up != set(w.up(nid).ids()) or down != set(w.down(nid).ids()) else []
    ok(not off, f"bitt.lineage / bitt.downstream equal walk.up / walk.down on all {len(E.rec.nodes)} nodes (W5)")
H.done()
