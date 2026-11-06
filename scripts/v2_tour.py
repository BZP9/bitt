"""Build a small, real bitt database on the THROWAWAY cluster and print the queries you would type in psql / DBeaver, with their
outputs (docs/v2/db.md). Synthetic data only.

  scripts/pg_throwaway.sh start
  uv run python scripts/v2_tour.py > docs/v2/db-tour.md

It creates database `bitt_tour` (dropped and recreated each run) on the throwaway cluster only, and refuses the live work DSN.
Every row is written by the kernel's own acts (data.load, module.define, artifact.add, recipe.make, run.go, tag.make), from the small
synthetic modules below and the shipped `echo` stub model (no network).
"""
import json
import os
import random
import sys
import tempfile
from pathlib import Path

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "conformance"))
from backend import throwaway_problem  # noqa: E402

from bitt import Kernel  # noqa: E402
from bitt.builtins import SHIPPED  # noqa: E402
from bitt.record.postgres import PostgresRecord  # noqa: E402
from bitt.tools import packages  # noqa: E402

admin = os.environ.get("BITT_PG_ADMIN_DSN") or "postgresql://bitt@localhost:55432/postgres"
if why := throwaway_problem(admin):
    sys.exit(f"refusing: {why}")
with psycopg.connect(admin, autocommit=True) as adm:
    adm.execute('DROP DATABASE IF EXISTS "bitt_tour" WITH (FORCE)')
    adm.execute('CREATE DATABASE "bitt_tour"')
DSN = make_conninfo(**(conninfo_to_dict(admin) | {"dbname": "bitt_tour"}))
tmp = Path(tempfile.mkdtemp(prefix="bitt-tour-"))
for var, sub in (("BITT_BLOBS", "blobs"), ("BITT_JOBS", "jobs"), ("BITT_ENVS", "no-envs.yaml"), ("BITT_CURRENT", "current.json")):
    os.environ[var] = str(tmp / sub)                         # never the user's own stores, envs or current cycle
k = Kernel(PostgresRecord(DSN), packages=packages())
USR, A = "usr", "agent:main"


def c(card, actor=A, **a):
    return k.call(card, {{"in_": "in", "as_": "as"}.get(x, x): v for x, v in a.items()}, actor)


MODULES = {        # the tour's own modules (synthetic): a row derive, a row check, a select
    "clean": b'"""Lower-case and strip a question."""\nBITT = {"kind": "derive"}\n\n\ndef clean(text: str) -> str:\n'
             b'    return text.strip().lower()\n',
    "split_by_id": b'"""Every fourth question is test."""\nBITT = {"kind": "derive", "writes": "selection", "reads": ["id"]}\n\n\n'
                   b'def split_by_id(rows: list) -> list:\n    return [(i, "test" if int(r["id"][1:]) % 4 == 0 else "train") '
                   b'for i, r in enumerate(rows)]\n',
}
ANSWER = json.dumps({"bitt": {"does": "Answer a support question (the echo stub replies with the prompt)."},
                     "messages": [{"role": "user", "content": "To {question}: open settings."}]})

random.seed(0)
rows = [{"id": f"q{i:03d}", "question": f"  How do I {random.choice(['reset', 'export', 'share', 'delete'])} my "
         f"{random.choice(['password', 'file', 'account'])}?  "} for i in range(12)]
task = c("control.goal.open_root", USR, problem="answer support questions well", name="demo")["goal"]
x = c("control.cycle.open", USR, in_=task, question="what do the answers look like", level="explore", because=[task])["cycle"]
for n, code in MODULES.items():
    c("module.define", in_=x, code=code, name=n)
for n in ("echo", "length", "rate"):
    c("module.define", in_=x, code=SHIPPED[n].read_bytes(), name=n)
c("artifact.add", in_=x, content=ANSWER, artifact_kind="prompt", name="answer")
raw = c("data.load", in_=x, bytes=json.dumps(rows), origin="file:support_questions.json", sensitivity="internal",
        does="synthetic rows for a test", line="support_questions")["raw"]


def recipe(module, **a):
    return c("recipe.make", in_=x, module=module, **a)["recipe"]


# a row derive → a prompt on a model (the echo stub) → a row check; the ladder climbs rung 1, then 5, then the full set
cleaned = c("run.go", in_=x, recipe=recipe("clean", cols={"text": "question"}), on=[raw], full="yes")["run"]
ans = recipe("echo", artifacts={"prompt": "answer"}, cols={"question": "clean"})
for _ in range(2):
    c("run.go", in_=x, recipe=ans, on=[cleaned])
answers = c("run.go", in_=x, recipe=ans, on=[cleaned], full="yes")["run"]
short = c("run.go", in_=x, recipe=recipe("length", cols={"text": "answer"}, params={"max": 40}), on=[answers], full="yes")["run"]
c("run.go", in_=x, recipe=recipe("rate", cols={"x": "length_ok"}), on=[short])          # across rows: a module of its own (D15)
# a dataset with splits, a person's approval, a version tag
qa = c("run.go", in_=x, recipe=recipe("split_by_id", cols={"id": "id"}), on=[raw], as_="dataset", line="qa")["set"]
val = c("control.validate", USR, in_=x, subject=qa, verdict="approve")["validation"]
f = c("control.log.finding", in_=x, text="a clean split", evidence=[val], finding_kind="conclusion")["finding"]
c("tag.make", in_=x, target=qa, tag="version", because=[f])
k.rec.commit() if hasattr(k.rec, "commit") else None

# ---- the tour: queries and what they return
db = psycopg.connect(DSN)


def show(title, sql, note=""):
    cur = db.execute(sql)
    cols = [d.name for d in cur.description]
    out = cur.fetchall()
    print(f"### {title}\n")
    if note:
        print(note + "\n")
    print("```sql\n" + sql.strip() + "\n```\n")
    print("| " + " | ".join(cols) + " |\n|" + "---|" * len(cols))
    for r in out:
        print("| " + " | ".join(("" if v is None else str(v)[:46]).replace("|", "\\|").replace("\n", " ") for v in r) + " |")
    print()


print("# bitt database tour (generated by scripts/v2_tour.py; synthetic data)\n")
print("Connect: `psql postgresql://bitt@localhost:55432/bitt_tour` (the throwaway cluster; `scripts/pg_throwaway.sh start`).")
print("Design: `docs/v2/db.md`. Every table below was written through the record (registered columns, FKs, append-only).\n")
show("1. The tables: raw imports, and one made table per output contract (shared by every task), each with __src and __sets",
     "SELECT schema, name, kind, sources FROM bitt.table WHERE schema IN ('raw', 'made') ORDER BY schema, name")
show("2. Which table holds a contract's rows (a module's writes, a prompt's gives)",
     "SELECT tbl, line, left(contract_hash, 12) AS contract FROM bitt.writer ORDER BY tbl")
show("3. The sets: the import, each run's input and output, the dataset, the ladder's rungs",
     "SELECT left(bitt_set_hash, 12) AS set, tbl, kind, n, left(parent, 12) AS parent, k FROM bitt.set ORDER BY tbl, kind, n DESC",
     "A rung, a split or a test side makes no table: only a `bitt.set` row (a rung is the first k members of its parent).")
show("4. Runs: the recipe's work, the kind, the rung, what it made and reused",
     "SELECT left(run, 12) AS run, kind, out_table, rung, status, rows_total, made, reused, failed FROM bitt.v_run ORDER BY started_at")
show("5. Lineage: an answer's length verdict back to the raw question, through __src",
     "SELECT r.id, r.question AS raw_question, q.clean, a.answer, ok.length_ok\n"
     "FROM made.length ok\n"
     "JOIN made.length__src l3 ON l3.bitt_in_hash = ok.bitt_in_hash\n"
     "JOIN made.answer a ON a.bitt_row_hash = l3.bitt_src_hash\n"
     "JOIN made.answer__src l2 ON l2.bitt_in_hash = a.bitt_in_hash\n"
     "JOIN made.clean q ON q.bitt_row_hash = l2.bitt_src_hash\n"
     "JOIN made.clean__src l1 ON l1.bitt_in_hash = q.bitt_in_hash\n"
     "JOIN raw.support_questions r ON r.bitt_row_hash = l1.bitt_src_hash\n"
     "ORDER BY r.id LIMIT 6",
     "`bitt data inspect` walks this for you; here it is by hand. Rows are keyed by what they read, so two questions that clean to the "
     "same text share one answer row.")
show("6. An aggregate: the `rate` module's one row over the check's run (per unit, with its 95% interval)",
     "SELECT rate, lo, hi, n, left(bitt_recipe_hash, 12) AS work, left(bitt_run_hash, 12) AS run FROM made.rate",
     "A check writes per-row verdicts only; anything across rows is a module that writes its own row into its own table.")
show("7. A dataset: its members and splits (a set over the raw rows)",
     "SELECT m.ord, m.split, r.id FROM bitt.set s JOIN raw.support_questions__sets m ON m.bitt_set_hash = s.bitt_set_hash\n"
     "JOIN raw.support_questions r USING (bitt_row_hash) WHERE s.kind = 'dataset' ORDER BY m.ord LIMIT 6")
show("8. Names (docs/v2/names.md) and tags: every name, the line it names, its version",
     "SELECT v.ns = '' AS is_task, bitt.name_of(v.target) AS ref, v.class, v.kind, (SELECT count(*) FROM bitt.members(v.target)) AS members\n"
     "FROM bitt.v_name v ORDER BY v.ns = '' DESC, v.ns, v.name",
     "A name is a `name` node bound to a line's root; versions and aliases are `tag` nodes on the unchanged thing.")
show("9. bitt.resolve(): the kernel's resolver in SQL",
     "SELECT r AS ref, (SELECT kind FROM bitt.node WHERE id = bitt.resolve(r)) AS kind, bitt.name_of(bitt.resolve(r)) AS line,\n"
     "       bitt.version_of(bitt.resolve(r)) AS version\n"
     "FROM unnest(ARRAY['raw/support_questions', 'raw/support_questions@1', 'demo', 'demo/qa', 'demo/qa@1.0', 'lib/clean']) r")
show("10. A task's own rows (A23): `<task>.<name>` views over the shared made tables",
     "SELECT 'demo.answer' AS view, count(*) FROM demo.answer UNION ALL SELECT 'made.answer', count(*) FROM made.answer",
     "Every task gets a schema of its name and a view per made table: the rows its runs made or reused.")
print("### 11. bitt.tree(): the graph as a branch tree\n")
print("What was made from a raw line (`'up'` = what a node was made from). Every node once, under the data it was made from first; "
      "events, checks, names and jobs left out unless `hide` says otherwise.\n")
print("```sql\nSELECT line FROM bitt.tree('raw/support_questions')\n```\n\n```")
for (ln,) in db.execute("SELECT line FROM bitt.tree('raw/support_questions')"):
    print(ln)
print("```\n")
