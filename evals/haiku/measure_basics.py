"""Can an agent score two prompt versions the same way and compare them from the bitt skill alone? `setup <dir>` makes a store (a
fresh database on the throwaway Postgres) with a task and an open cycle and writes questions.jsonl; `grade <dir>` inspects the store.
The agent is given only TASK.

  uv run python evals/haiku/measure_basics.py setup <dir>   ·   (agent)   ·   grade <dir>
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _store as s  # noqa: E402

N = 20
TASK = s.TASK_HEAD + """ has an open cycle ({cyc}). The file {dir}/questions.jsonl has synthetic questions (fields qid, q); its sensitivity
is internal.
1. Load it as the line qs.
2. Use bitt's stub model (it replies with your user message, word for word).
3. Write a prompt named summarize with one output field, title (text), whose reply is a JSON object with title set to the question
   q. Run it on the stub over every row.
4. Score its titles two ways: not empty, and at most 6 words; for each, the share of titles that pass.
5. Change the prompt so the title is "In short, the question is: " followed by the question. Run it over every row and score it
   the same two ways.
6. Tell me which version keeps titles short, with the numbers (each with its interval)."""


def setup(d):
    cyc = s.new_store(d, "short titles", "which prompt keeps titles short")
    (d / "questions.jsonl").write_text("".join(json.dumps({"qid": f"Q{i}", "q": f"How do I reset item {i}?"}) + "\n" for i in range(N)))
    print(TASK.format(dir=d, dsn=s.env(d)["BITT_DSN"], cyc=cyc))


def grade(d):
    k, res = s.kernel(d), {}
    res["questions.jsonl is loaded as raw/qs, all 20 rows"] = any(n["payload"].get("n_rows") == N for n in s.line(k, "raw", "qs"))
    prompts = [n for n in s.line(k, "lib", "summarize") if n["kind"] == "artifact"]
    res["a prompt summarize and a second version of it"] = len(prompts) >= 2
    shipped = {m["payload"]["header"]["fn"]: m["id"] for m in k.rec.find("module") if m["payload"].get("builtin")}

    def scored(prompt, check):
        """The rate rows over every run of the shipped `check` over a full run of this prompt version."""
        gens = {r["id"] for rc in s.recipes_using(k, [prompt]) for r in s.runs_of(k, rc["id"]) if r["payload"].get("rung") == N}
        out = []
        base = shipped.get(check)                                # the shipped check, or a wrap of it (a setting fixed: max 6)
        ids = [base] + [m["id"] for m in k.rec.find("module") if base and m["links"].get("wraps") == base] if base else []
        for rc in s.recipes_using(k, ids):
            out += [a for r in s.runs_of(k, rc["id"]) if set(r["links"].get("on") or []) & gens for a in s.aggregates(k, r["id"], "rate")]
        return out
    v1, v2 = (prompts[0]["id"], prompts[-1]["id"]) if len(prompts) >= 2 else (None, None)
    for p, name in ((v1, "v1"), (v2, "v2")):
        res[f"{name}'s titles were checked not empty (rate 1.0 over 20 rows)"] = any(
            a["rate"] == 1 and a["n"] == N for a in scored(p, "nonempty"))
    res["v1's titles are all at most 6 words (rate of length_ok 1.0 over 20 rows)"] = any(
        a["rate"] == 1 and a["n"] == N for a in scored(v1, "length"))
    res["v2's titles are all too long (rate of length_ok 0.0 over 20 rows)"] = any(
        a["rate"] == 0 and a["n"] == N for a in scored(v2, "length"))
    res["the agent never acted as usr"] = not s.acted_as_usr_after_setup(k)
    res["the agent acted as an agent"] = any(str(n["stamp"].get("actor", "")).startswith("agent:") for n in prompts)
    return s.report(res)



def reference(d):
    """The task done with bitt commands as agent:ref: two prompt versions on the echo stub, each scored twice with a rate."""
    b = s.bitt_cli
    b("data", "load", str(d / "questions.jsonl"), "--does", "synthetic rows for a test", "--line", "qs", "--sensitivity", "internal")
    for m in ("echo", "nonempty", "length", "rate"):
        b("module", "add", m)
    b("module", "wrap", "length", "--name", "short6", "--does", "at most 6 words", "--params", "max=6", "unit=words")
    for content in ('{"title": "{q}"}', '{"title": "In short, the question is: {q}"}'):
        (d / "summarize.json").write_text(json.dumps({"bitt": {"does": "A title for a question."}, "gives": {"title": "text"},
                                                      "messages": [{"role": "user", "content": content}]}))
        b("artifact", "add", str(d / "summarize.json"), "--kind", "prompt", "--name", "summarize")
        gen = s.run_in(b("run", "go", s.label_in(b("recipe", "echo", "--fill", "prompt=summarize", "--cols", "q=q")), "--on", "raw/qs",
                         "--full"))
        for check, role, col in (("nonempty", "value", "nonempty"), ("short6", "text", "length_ok")):
            v = s.run_in(b("run", "go", s.label_in(b("recipe", check, "--cols", f"{role}=title")), "--on", gen, "--full"))
            b("run", "go", s.label_in(b("recipe", "rate", "--cols", f"x={col}")), "--on", v)
    return 0


if __name__ == "__main__":
    s.main(setup, grade, reference=reference)
