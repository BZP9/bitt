"""Can an agent load a file, write and run a module, and make a split dataset from the bitt-data skill alone? `setup <dir>` makes a
store (a fresh database on the throwaway Postgres, scripts/pg_throwaway.sh) with a task and an open cycle and writes
questions.jsonl; `grade <dir>` inspects the store. The agent is given only TASK.

  uv run python evals/haiku/data_basics.py setup <dir>   ·   (agent)   ·   grade <dir>
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _store as s  # noqa: E402

N = 40
TASK = s.TASK_HEAD + """ has an open cycle ({cyc}). The file {dir}/questions.jsonl has synthetic questions (fields qid, q); its sensitivity is
internal. Load it as the line qs. Write a bitt module named clean_q that writes q_clean: the question with the spaces around it
removed and lower-cased. Run it over every row of the import. Then make a dataset line named qs_split over the questions: every
row whose qid ends in 7 goes to test, every other row to train. Tell me the names you made."""


def rows():
    return [{"qid": f"Q{i % 20}", "q": f"{' ' * (i % 3)}What Is Item {i}?{' ' * (i % 4)}"} for i in range(N)]


def setup(d):
    cyc = s.new_store(d, "clean some questions", "what do the questions look like")
    (d / "questions.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows()))
    print(TASK.format(dir=d, dsn=s.env(d)["BITT_DSN"], cyc=cyc))


def grade(d):
    from bitt import sets
    k, res = s.kernel(d), {}
    imports = s.line(k, "raw", "qs")
    res["questions.jsonl is loaded as raw/qs, all 40 rows"] = any(n["payload"].get("n_rows") == N for n in imports)
    res["with the sensitivity internal"] = bool(imports) and all(n["payload"].get("sensitivity") == "internal" for n in imports)
    mods = [n for n in s.line(k, "lib", "clean_q") if n["kind"] == "module"]
    h = mods[-1]["payload"]["header"] if mods else {}
    res["a module clean_q on the shelf: a derive that writes q_clean"] = h.get("kind") == "derive" and "q_clean" in (h.get("writes") or {})
    want = {r["q"].strip().lower() for r in rows()}
    full = [r for rc in s.recipes_using(k, [m["id"] for m in mods]) for r in s.runs_of(k, rc["id"])
            if k.node(r["id"])["payload"].get("rung") == len({json.dumps(x) for x in rows()})]
    got = {r["q_clean"] for run in full for r in s.run_rows(k, run["id"])}
    res["a run of it over every row: q_clean stripped and lower-cased"] = bool(full) and got == want
    dss = [n for n in s.line(k, s.task(k), "qs_split") if n["kind"] == "dataset"]
    split_ok = False
    if dss:
        t = dss[-1]["payload"]["table"]
        ms = sets.members(k.rec, dss[-1]["payload"]["set"])
        split_ok = len(ms) == len({json.dumps(r) for r in rows()}) and all(
            sp == ("test" if k.rec.get_row(t, (m,))["qid"].endswith("7") else "train") for m, sp in ms)
    res["a dataset qs_split exists"] = bool(dss)
    res["every row: qid ending in 7 → test, the rest → train"] = split_ok
    res["the agent never acted as usr"] = not s.acted_as_usr_after_setup(k)
    res["the agent acted as an agent"] = any(str(m["stamp"].get("actor", "")).startswith("agent:") for m in mods + imports)
    return s.report(res)



def reference(d):
    """The task done with bitt commands as agent:ref."""
    b = s.bitt_cli
    b("data", "load", str(d / "questions.jsonl"), "--does", "synthetic rows for a test", "--line", "qs", "--sensitivity", "internal")
    (d / "clean_q.py").write_text('"""Strip and lower-case a question."""\nfrom typing import TypedDict\n\nBITT = {"kind": "derive"}\n\n\n'
                                  'class Clean(TypedDict):\n    q_clean: str\n\n\ndef clean_q(q: str) -> Clean:\n'
                                  '    return {"q_clean": q.strip().lower()}\n')
    (d / "by_qid.py").write_text('"""A qid ending in 7 is test, the rest train."""\nBITT = {"kind": "derive", "writes": "selection", "reads": ["qid"]}\n\n\n'
                                 'def by_qid(rows: list) -> list:\n    return [(i, "test" if r["qid"].endswith("7") else "train") for i, r in enumerate(rows)]\n')
    b("module", "add", str(d / "clean_q.py"))
    b("run", "go", s.label_in(b("recipe", "clean_q", "--cols", "q=q")), "--on", "raw/qs", "--full")
    b("module", "add", str(d / "by_qid.py"))
    b("run", "go", s.label_in(b("recipe", "by_qid", "--cols", "qid=qid")), "--on", "raw/qs", "--as", "dataset", "--line", "qs_split")
    return 0


if __name__ == "__main__":
    s.main(setup, grade, reference=reference)
