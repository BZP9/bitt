"""Can an agent train a model with bitt and score it fairly, from the bitt skills alone? `setup <dir>` makes a store (a fresh database
on the throwaway Postgres) with a task and an open cycle and writes tickets.jsonl; `grade <dir>` inspects the store. The trainer is
bitt's built-in CPU example (nb_train, a text classifier), so the accuracy is known (the two labels share no words).

  uv run python evals/haiku/train_basics.py setup <dir>   ·   (agent)   ·   grade <dir>
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _store as s  # noqa: E402

TEXTS = {"billing": ["refund my order", "the invoice is wrong", "a double charge on my card", "pay the bill", "refund the charge"],
         "account": ["reset my password", "change my username", "login fails again", "delete my account", "password reset link"]}
N = 40
TASK = s.TASK_HEAD + """ has an open cycle ({cyc}). The file {dir}/tickets.jsonl has synthetic support tickets (fields qid, text, label);
its sensitivity is internal.
1. Load it as the line tickets.
2. Make a dataset named tickets_split: every ticket whose qid ends in 0 or 5 goes to test, every other one to train.
3. Train a classifier on it with bitt's built-in text classifier trainer (text column text, label column label), on this machine.
4. Score the trained model's accuracy (its predicted label against the true label) on the test tickets only, and tell me the
   number and the names you made."""


def rows():
    """Every ticket's text is its own (a ticket number at the end): the model's predictions are one row per ticket."""
    return [{"qid": f"T{i}", "text": f"{TEXTS[lab][i % 5]} ticket{i}", "label": lab} for i, lab in enumerate(["billing", "account"] * (N // 2))]


def setup(d):
    cyc = s.new_store(d, "route support tickets", "can a small classifier route tickets")
    (d / "tickets.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows()))
    print(TASK.format(dir=d, dsn=s.env(d)["BITT_DSN"], cyc=cyc))


def grade(d):
    from bitt import sets
    k, res = s.kernel(d), {}
    res["tickets.jsonl is loaded as raw/tickets, all 40 rows"] = any(n["payload"].get("n_rows") == N for n in s.line(k, "raw", "tickets"))
    ds = [n for n in s.line(k, s.task(k), "tickets_split") if n["kind"] == "dataset"]
    test = {f"T{i}" for i in range(N) if str(i).endswith(("0", "5"))}
    split_ok = False
    if ds:
        t = ds[-1]["payload"]["table"]
        got = {k.rec.get_row(t, (m,))["qid"]: sp for m, sp in sets.members(k.rec, ds[-1]["payload"]["set"])}
        split_ok = len(got) == N and all((sp == "test") == (q in test) for q, sp in got.items())
    res["a dataset tickets_split: qid ending in 0 or 5 → test, the rest → train"] = split_ok
    nb = [m["id"] for m in s.line(k, "lib", "nb_train") if m["kind"] == "module" and m["payload"].get("builtin")]
    trains = [r for rc in s.recipes_using(k, nb) for r in s.runs_of(k, rc["id"])]
    res["it trained with the built-in nb_train"] = bool(trains)
    res["a smoke run first, then the full run"] = bool(trains) and trains[0]["payload"].get("smoke") and any(
        not r["payload"].get("smoke") for r in trains[1:])
    res["every train named an eval first"] = bool(trains) and all(r["links"].get("evals") for r in trains)
    models = [a for a in k.rec.find("artifact") if a["payload"].get("artifact_kind") == "model"
              and a["links"].get("run") in {r["id"] for r in trains}]
    res["the model landed: an artifact the train run made"] = bool(models)
    eps = [w["id"] for w in k.rec.find("module") if w["links"].get("wraps") and set(w["links"].get("artifacts") or []) &
           {m["id"] for m in models}]
    preds = {r["id"]: r for rc in s.recipes_using(k, eps) for r in s.runs_of(k, rc["id"])}
    acc = []
    for rc in k.rec.find("recipe"):
        for r in s.runs_of(k, rc["id"]):
            if r["payload"].get("kind") == "check" and set(r["links"].get("on") or []) & set(preds):
                acc += [a for a in s.aggregates(k, r["id"], "rate") if a["rate"] is not None]
    res["the model was scored (a check over its predictions, then its rate)"] = bool(acc)
    res["on the 8 test tickets only, accuracy 1.0"] = any(a["n"] == len(test) and a["rate"] == 1 for a in acc)
    res["nothing was written around bitt"] = s.direct_writes(k) == 0
    res["the agent never acted as usr"] = not s.acted_as_usr_after_setup(k)
    res["the agent acted as an agent"] = any(str(n["stamp"].get("actor", "")).startswith("agent:") for n in models + ds)
    return s.report(res)



def reference(d):
    """The task done with bitt commands as agent:ref: split, smoke then full train on this machine, land, score the test side."""
    import time
    b = s.bitt_cli
    b("data", "load", str(d / "tickets.jsonl"), "--does", "synthetic rows for a test", "--line", "tickets", "--sensitivity", "internal")
    (d / "by_qid.py").write_text('"""A qid ending in 0 or 5 is test, the rest train."""\nBITT = {"kind": "derive", "writes": "selection", '
                                 '"reads": ["qid"]}\n\n\ndef by_qid(rows: list) -> list:\n'
                                 '    return [(i, "test" if r["qid"].endswith(("0", "5")) else "train") for i, r in enumerate(rows)]\n')
    (d / "test_side.py").write_text('"""Keep the test side."""\nBITT = {"kind": "derive", "writes": "selection"}\n\n\n'
                                    'def test_side(rows: list) -> list:\n    return [(i, "test") for i, r in enumerate(rows) if r["bitt_split"] == "test"]\n')
    b("module", "add", str(d / "by_qid.py"))
    b("run", "go", s.label_in(b("recipe", "by_qid", "--cols", "qid=qid")), "--on", "raw/tickets", "--as", "dataset", "--line", "tickets_split")
    for m in ("nb_train", "nb_predict", "exact_match", "rate"):
        b("module", "add", m)
    tr = s.label_in(b("recipe", "nb_train", "--cols", "text=text", "label=label"))
    ev = s.label_in(b("recipe", "exact_match", "--cols", "a=pred", "b=tickets.label"))
    for _ in range(2):                                           # the smoke run, then the full train
        b("run", "go", tr, "--on", "tickets_split", "--evals", ev, "--endpoint", "nb_predict", "--line", "clf")
        for _ in range(120):
            if "clf_endpoint" in b("run", "sync") or s.bitt_try("show", "clf_endpoint")[0] == 0:
                break
            time.sleep(1)
    b("module", "add", str(d / "test_side.py"))
    b("run", "go", s.label_in(b("recipe", "test_side")), "--on", "tickets_split", "--as", "evalset", "--line", "tickets_test")
    pred = s.run_in(b("run", "go", s.label_in(b("recipe", "clf_endpoint", "--cols", "text=text")), "--on", "tickets_test", "--full"))
    v = s.run_in(b("run", "go", ev, "--on", pred, "--full"))
    b("run", "go", s.label_in(b("recipe", "rate", "--cols", "x=exact_match")), "--on", v)
    return 0


if __name__ == "__main__":
    s.main(setup, grade, reference=reference)
