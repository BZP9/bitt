"""Can an agent run a prompt on a served model from the bitt skill alone? `setup <dir>` makes a store (a fresh database on the
throwaway Postgres) with a task and an open cycle, writes questions.jsonl and a key file, and starts a fake OpenAI-compatible endpoint
(conformance/fake_openai.py: it replies with the last user message, so the prompt decides the reply); `grade <dir>` inspects the
store and the endpoint's call log; `stop <dir>` stops the endpoint. The agent is given only TASK.

  uv run python evals/haiku/run_basics.py setup <dir>   ·   (agent)   ·   grade <dir>   ·   stop <dir>
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _store as s  # noqa: E402

N = 20
KEY = "sk-eval-run-basics-0a9f"
TASK = s.TASK_HEAD + """ has an open cycle ({cyc}). The file {dir}/questions.jsonl has synthetic questions (fields qid, q); its sensitivity
is internal. A test model is served at {url} (OpenAI-compatible) under the id tiny; its key is in the file {dir}/key. This test
model replies with your last user message exactly, word for word.
1. Load the file as the line qs.
2. Register the model as tiny.
3. Write a prompt named summarize that gives one field, title (text), whose reply is a JSON object with title set to the row's
   question q.
4. Run summarize on tiny over raw/qs on the ladder: look at its sample's rows before you run the rest, until every row is done.
   Do not skip the ladder.
5. Then add a system message "Be brief." to the prompt (a new version of summarize) and run that over every row at once.
Tell me the names you made and what each run printed."""


def setup(d):
    cyc = s.new_store(d, "summarize some questions", "does a summarize prompt work")
    (d / "questions.jsonl").write_text("".join(json.dumps({"qid": f"Q{i}", "q": f"How do I reset item {i}?"}) + "\n" for i in range(N)))
    url = s.start_endpoint(d, KEY)
    print(TASK.format(dir=d, dsn=s.env(d)["BITT_DSN"], cyc=cyc, url=url))


def grade(d):
    k, res = s.kernel(d), {}
    imports = s.line(k, "raw", "qs")
    res["questions.jsonl is loaded as raw/qs, all 20 rows, internal"] = any(
        n["payload"].get("n_rows") == N and n["payload"].get("sensitivity") == "internal" for n in imports)
    wraps = [m for m in k.rec.find("module") if m["links"].get("wraps") and m["payload"].get("params", {}).get("model") == "tiny"]
    res["an endpoint: a wrap of a connector serving tiny, its key read from the file"] = any(
        w["payload"]["params"].get("key_file") for w in wraps)
    prompts = [n for n in s.line(k, "lib", "summarize") if n["kind"] == "artifact"]
    res["a prompt summarize that gives title"] = bool(prompts) and "title" in ((prompts[0]["payload"].get("contract") or {}).get("gives") or {})
    res["a second version with a system message"] = len(prompts) >= 2 and '"system"' in s.text_of(k, prompts[-1]["id"])
    want = {f"How do I reset item {i}?" for i in range(N)}
    first = [r for rc in s.recipes_using(k, [prompts[0]["id"]] if prompts else []) for r in s.runs_of(k, rc["id"])]
    rungs = [r["payload"].get("rung") for r in first]
    res["the first version climbed the ladder (smoke 1, the sample 10, all 20)"] = rungs[:1] == [1] and 10 in rungs and N in rungs
    res["... without skipping it"] = bool(first) and not any(r["payload"].get("full") == "yes" for r in first)
    last = [r for r in first if r["payload"].get("rung") == N]
    res["its 20 rows have title = the question"] = bool(last) and {r["title"] for r in s.run_rows(k, last[-1]["id"])} == want
    second = [r for rc in s.recipes_using(k, [prompts[-1]["id"]] if len(prompts) >= 2 else []) for r in s.runs_of(k, rc["id"])]
    res["the new version ran over all 20 rows"] = any(len(s.run_rows(k, r["id"])) == N for r in second)
    calls = s.calls(d)
    plain = [c for c in calls if c["messages"][0]["role"] != "system"]
    res["each row was paid for once per version (no row asked twice)"] = \
        len(plain) == len({json.dumps(c["messages"]) for c in plain}) == N and len(calls) - len(plain) == N
    res["the key is in no node and no job file"] = not s.key_leaked(k, d, KEY)
    res["the agent never acted as usr"] = not s.acted_as_usr_after_setup(k)
    res["the agent acted as an agent"] = any(str(n["stamp"].get("actor", "")).startswith("agent:") for n in prompts + wraps)
    return s.report(res)



def reference(d):
    """The task done with bitt commands as agent:ref (rung by rung, then the new version in full)."""
    b, url = s.bitt_cli, (d / "url.txt").read_text()
    b("data", "load", str(d / "questions.jsonl"), "--does", "synthetic rows for a test", "--line", "qs", "--sensitivity", "internal")
    b("module", "add", "openai_chat")
    b("module", "wrap", "openai_chat", "--name", "tiny", "--does", "the test model", "--params", f"url={url}", "model=tiny",
      f"key_file={d / 'key'}")
    v1 = {"bitt": {"does": "A title for a question."}, "gives": {"title": "text"},
          "messages": [{"role": "user", "content": '{"title": "{q}"}'}]}
    (d / "summarize.json").write_text(json.dumps(v1))
    b("artifact", "add", str(d / "summarize.json"), "--kind", "prompt", "--name", "summarize")
    r1 = s.label_in(b("recipe", "tiny", "--fill", "prompt=summarize", "--cols", "q=q"))
    for _ in range(3):                                           # the smoke rung and the sample, then all
        out = b("run", "go", r1, "--on", "raw/qs")
        if f"rung {N}/{N}" in out:
            break
    v2 = {**v1, "messages": [{"role": "system", "content": "Be brief."}] + v1["messages"]}
    (d / "summarize.json").write_text(json.dumps(v2))
    b("artifact", "add", str(d / "summarize.json"), "--kind", "prompt", "--name", "summarize")
    b("run", "go", s.label_in(b("recipe", "tiny", "--fill", "prompt=summarize", "--cols", "q=q")), "--on", "raw/qs", "--full")
    return 0


if __name__ == "__main__":
    s.main(setup, grade, s.stop_endpoint, reference)
