"""Can an agent find data it was not given the name of (A24, owner 11-06: "iirc there should be a dataset about client questions, go
fetch em")? `setup <dir>` makes a store with a task, an open cycle and four data lines: the one meant (customers' help-desk questions,
no column called question, its own words say "customers", not "clients") and three that look close by name or column (a staff FAQ
with a question column, invoices with a client column, staff chat), plus a split of the meant one. The agent is given only TASK; it
writes what it found to found.json. `grade <dir>` reads the file and checks the store is unchanged (finding writes nothing).

  uv run python evals/haiku/find_basics.py setup <dir>   ·   (agent)   ·   grade <dir>
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _store as s  # noqa: E402

TASK = s.TASK_HEAD + """ has an open cycle ({cyc}). iirc there should be a dataset about client questions somewhere in bitt. Find it
and fetch me some of them: write {dir}/found.json as {{"name": "<its bitt name>", "rows": <how many rows it has>, "sample": [<the
text of 3 of its rows>]}}, and tell me which one you picked and why."""

HELP = ["how do I reset my password", "can I get a refund for a late order", "why was I charged twice this month", "where is my parcel",
        "can I change the delivery address", "is there a discount for students", "how do I close my account",
        "the app crashes when I pay", "can I pay by bank transfer", "do you ship abroad"]
FAQ = [("how do I reset my password?", "use the link on the sign-in page"), ("what are your hours?", "9 to 5, Monday to Friday"),
       ("how long is delivery?", "two to four days")]


def rows():
    return {
        "helpdesk": ("questions customers sent to the help desk, one message per row (synthetic export)", "internal",
                     [{"tid": f"H{i}", "msg": m, "channel": ["mail", "chat", "phone"][i % 3]} for i, m in enumerate(HELP * 3)]),
        "faq": ("our public FAQ page: questions and answers written by staff", "public",
                [{"question": q, "answer": a} for q, a in FAQ]),
        "invoices": ("invoice lines from the billing export", "internal",
                     [{"invoice_id": f"I{i}", "client": f"client {i % 4}", "amount": 10 * i} for i in range(8)]),
        "staff_chat": ("messages staff sent each other in the team chat", "internal",
                       [{"author": f"staff {i % 3}", "text": t} for i, t in enumerate(["lunch?", "the deploy is done", "who has the keys"])]),
    }


def setup(d, mode="steps"):
    cyc = s.new_store(d, "look after what clients ask", "what do clients ask about")
    for line, (does, sens, rs) in rows().items():
        (d / f"{line}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rs))
        s.bitt_cli("data", "load", str(d / f"{line}.jsonl"), "--line", line, "--does", does, "--sensitivity", sens, actor="agent:setup")
        (d / f"{line}.jsonl").unlink()                              # the agent finds it in bitt, not on disk
    (d / "by_tid.py").write_text('"""A message whose tid ends in 7 is test, the rest train."""\n'
                                 'BITT = {"kind": "derive", "writes": "selection", "reads": ["tid"]}\n\n\n'
                                 'def by_tid(rows: list) -> list:\n    return [(i, "test" if r["tid"].endswith("7") else "train") '
                                 'for i, r in enumerate(rows)]\n')
    s.bitt_cli("module", "add", str(d / "by_tid.py"), actor="agent:setup")
    (d / "by_tid.py").unlink()
    rc = s.label_in(s.bitt_cli("recipe", "by_tid", "--cols", "tid=tid", actor="agent:setup"))
    s.bitt_cli("run", "go", rc, "--on", "raw/helpdesk", "--as", "dataset", "--line", "helpdesk_split", actor="agent:setup")
    s.mark_setup(d)
    print(TASK.format(dir=d, dsn=s.env(d)["BITT_DSN"], cyc=cyc))


def grade(d):
    k, res = s.kernel(d), {}
    last = int((d / "setup_seq.txt").read_text())
    try:
        got = json.loads((d / "found.json").read_text())
    except (OSError, ValueError):
        got = {}
    name = str(got.get("name", "")).strip()
    base = name.split("@")[0].split("/")[-1]
    res["found.json is written (name, rows, sample)"] = bool(name) and isinstance(got.get("sample"), list)
    res["it names the help-desk questions (raw/helpdesk or its split), not the FAQ, invoices or chat"] = base in ("helpdesk", "helpdesk_split")
    res["its row count is right (30)"] = got.get("rows") == len(HELP * 3)
    texts = {m for m in HELP}
    sample = [str(x.get("msg", x) if isinstance(x, dict) else x).strip().rstrip("?") for x in got.get("sample") or []]
    res["3 sample rows, each a real help-desk message"] = len(sample) >= 3 and all(x in texts for x in sample[:3])
    res["finding wrote nothing to the store"] = not [n for n in k.rec.nodes.values() if n["seq"] > last]
    res["the agent never acted as usr"] = not s.acted_as_usr_after_setup(k, d)
    return s.report(res)


def reference(d):
    """The task done with bitt commands as agent:ref: list by the user's words, read the candidates, pick by what the rows hold."""
    out = s.bitt_cli("data", "list", "client", "questions", "customer")
    assert "raw/helpdesk" in out, out
    rows_out = s.bitt_cli("data", "inspect", "raw/helpdesk", "-n", "3")
    msgs = [m for m in HELP if f"msg={m}" in rows_out or m in rows_out][:3]
    (d / "found.json").write_text(json.dumps({"name": "raw/helpdesk", "rows": len(HELP * 3), "sample": msgs}))
    return 0


if __name__ == "__main__":
    s.main(setup, grade, reference=reference)
