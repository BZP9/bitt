"""Run one agent eval end to end with a non-Claude agent through opencode: setup → the agent gets only the eval's TASK → grade →
a row in evals/haiku/results.jsonl. The agent finds the bitt skills itself (they sync to opencode's skills folder).

  uv run python evals/run_agent_eval.py <eval> [--model macstudio/qwen3.8-27b] [--dir <scratch dir>]   (default ~/.bitt/evals/…)

An eval is evals/haiku/<eval>.py (`setup <dir>` prints the TASK; `grade <dir>` judges it). The v1 tool evals went with the v1 tools;
each eval covers one part of the skill. evals/haiku/results.jsonl keeps every past run.
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals" / "haiku"))
import _store  # noqa: E402
ap = argparse.ArgumentParser()
ap.add_argument("eval", choices=sorted(p.stem for p in (ROOT / "evals" / "haiku").glob("*.py")))
ap.add_argument("--model", default="macstudio/qwen3.8-27b", help="an opencode provider/model")
ap.add_argument("--dir", help="a scratch directory for the store (default: _output/agent-evals/<eval>-<time>)")
ap.add_argument("--mode", choices=["steps", "goal"], default="steps", help="numbered outcomes, or the end goal only (passed to setup)")
ap.add_argument("--dev", action="store_true", help="the agent's `bitt` is this tree (uv run --project), not the release on PATH: for a "
                                                   "feature not yet tagged")
a = ap.parse_args()
# outside any git repo: the agent's tools search the project they start in, and an eval must see only its own folder and the skills
d = Path(a.dir or Path.home() / ".bitt" / "evals" / f"{a.eval}-{time.strftime('%Y%m%d-%H%M%S')}").resolve()
script = ROOT / "evals" / "haiku" / f"{a.eval}.py"
setup = subprocess.run([sys.executable, str(script), "setup", str(d), *(["--mode", a.mode] if a.mode != "steps" else [])],
                       capture_output=True, text=True, cwd=ROOT)
if setup.returncode:
    sys.exit(f"setup failed: {setup.stderr[-500:]}")
task = "In bitt (store:" + setup.stdout.split("In bitt (store:", 1)[-1].rstrip() if "In bitt (store:" in setup.stdout else setup.stdout.strip()
repo = lambda: subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, cwd=ROOT).stdout  # noqa: E731
before = repo()
# reading bitt's own docs and code is a proper way to learn it (owner 10-30): allowed, and noted per run; nothing else outside the folder
env = _store.agent_env(d, os.environ)
if a.dev:                                                      # a `bitt` first on the agent's PATH that runs this tree
    (d / "devbin").mkdir(exist_ok=True)
    (d / "devbin" / "bitt").write_text(f'#!/usr/bin/env bash\nexec uv run -q --project "{ROOT}" bitt "$@"\n')
    (d / "devbin" / "bitt").chmod(0o755)
    env["PATH"] = f"{d / 'devbin'}:{env.get('PATH', '')}"
# an eval tests this tree's skills: write them for the run, then let the release put its own back (src/bitt/skills.py)
from bitt import skills  # noqa: E402
skills.sync(source=skills.SOURCE)
t0 = time.monotonic()
try:
    with open(d / "agent.jsonl", "w") as out:
        subprocess.run(["opencode", "run", "-m", a.model, "--format", "json", "--dir", str(d), task], stdin=subprocess.DEVNULL, stdout=out,
                       stderr=open(d / "agent.err", "w"), cwd=d, env=env)
finally:
    rel = subprocess.run(["bitt", "--help"], capture_output=True, env={k: v for k, v in os.environ.items() if not k.startswith("BITT_")})
    if rel.returncode:
        print("eval: no release `bitt` on PATH: the dev skills stay installed (uv tool install git+https://github.com/BZP9/bitt@<tag>)")
secs = int(time.monotonic() - t0)
events = [json.loads(x) for x in (d / "agent.jsonl").read_text().splitlines() if x.strip()]
tools = [e for e in events if e.get("type") == "tool_use"]
tokens = sum(((e.get("part") or {}).get("tokens") or {}).get("input", 0) + ((e.get("part") or {}).get("tokens") or {}).get("output", 0)
             for e in events if e.get("type") == "step_finish")
grade = subprocess.run([sys.executable, str(script), "grade", str(d)], capture_output=True, text=True, cwd=ROOT)
if a.eval in ("run_basics", "measure_basics", "cycle_basics", "e2e_basics", "compose_basics"):
    subprocess.run([sys.executable, str(script), "stop", str(d)], cwd=ROOT)
(d / "grade.txt").write_text(grade.stdout)
last = grade.stdout.strip().splitlines()[-1]
passed, total = (int(x) for x in last.split()[0].split("/"))
first_tool = (tools[0].get("part") or {}).get("tool") if tools else None
row = {"eval": a.eval, "mode": a.mode, "run": None, "date": datetime.date.today().isoformat(), "model": a.model.split("/")[-1] + " (opencode)",
       "commit": subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip(),
       "passed": passed, "total": total, "tool_calls": len(tools), "tokens": tokens, "seconds": secs, "grade": "~/" + str((d / "grade.txt").relative_to(Path.home())) if d.is_relative_to(Path.home()) else str(d / "grade.txt"),
       "notes": f"first tool: {first_tool}" + ("; --dev: the agent ran this tree, uncommitted changes included" if a.dev else "")}
read = sorted({str(p.relative_to(ROOT)) for e in tools for p in [Path(x) for x in re.findall(rf"{re.escape(str(ROOT))}/[\w./-]+",
               json.dumps((e.get("part") or {}).get("state", {}).get("input", {})))] if p.is_relative_to(ROOT)})
if read:
    row["notes"] += f"; read bitt's own files: {', '.join(read[:8])}" + (" …" if len(read) > 8 else "")
if repo() != before:
    row["notes"] += "; THE BITT REPO CHANGED during the run (git status differs): look before trusting it"
res = ROOT / "evals" / "haiku" / "results.jsonl"
prior = [json.loads(x) for x in res.read_text().splitlines() if x.strip()]
row["run"] = 1 + sum(1 for r in prior if r["eval"] == a.eval and r["model"] == row["model"])
with open(res, "a") as f:
    f.write(json.dumps(row, ensure_ascii=False) + "\n")
print(grade.stdout.strip())
subprocess.run([sys.executable, str(ROOT / "scripts" / "viz_evals.py"), str(d)], cwd=ROOT)   # the store as the viz draws it
print(f"{a.model}: {passed}/{total} · {len(tools)} tool calls · {tokens} tokens · {secs}s · first tool {first_tool} · {d}")
