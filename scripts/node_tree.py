"""A bitt store's nodes as a branch tree, one HTML page: every task (its goal, walking down) and every raw line (down: what was
made from it), or the refs you name. Read only: bitt.tree() (src/bitt/sql/postgres_nav.sql, installed by every bitt command) on a
read-only session. Run: uv run python scripts/node_tree.py [--dsn D (default $BITT_DSN)] [--ref X [--up]]… [--all-kinds]
→ _report/tree/node_tree.html (and the hub)."""
import argparse
import html
import json
import os
import subprocess
import sys
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "_report" / "tree" / "node_tree.html"
HIDE = ["event", "ruling", "name", "job_status", "job"]      # bookkeeping: each call's event, rulings, names, job polling
COLS = "depth, role, id, kind, label, actor, at, also, path"


def trees(dsn, refs, hide):
    with psycopg.connect(dsn, autocommit=True) as db:
        db.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
        if not refs:
            refs = [(r, "down") for (r,) in db.execute("SELECT bitt.name_of(target) FROM bitt.v_name WHERE active AND (kind = 'goal' AND ns = '' "
                                                       "OR ns = 'raw') ORDER BY ns DESC, name")]
        out = []
        for ref, d in refs:
            rows = [dict(zip(COLS.split(", "), r)) for r in db.execute(f"SELECT {COLS} FROM bitt.tree(%s, %s, 30, %s)", (ref, d, hide))]
            pay = {i: (k, p) for i, k, p in db.execute("SELECT id, kind, payload FROM bitt.node WHERE id = ANY(%s)", ([r["id"] for r in rows],))}
            for r in rows:
                r["payload"] = pay[r["id"]][1]
            out.append((ref, d, rows))
        return out


def render(blocks, hide, dsn_label):
    def node(rows, i):
        r = rows[i]
        kids, j = [], i + 1
        while j < len(rows) and rows[j]["depth"] > r["depth"]:
            if rows[j]["depth"] == r["depth"] + 1:
                kids.append(j)
            j += 1
        fam = r["kind"].split(":")[0]
        also = f" <span class='also'>also: {html.escape(', '.join(r['also']))}</span>" if r["also"] else ""
        role = f"<span class='role'>{html.escape(r['role'])} →</span> " if r["role"] else ""
        head = (f"{role}<span class='kind k-{html.escape(fam)}'>{html.escape(r['kind'])}</span> <b>{html.escape(r['label'] or '')}</b> "
                f"<code>{r['id'][:12]}</code> <span class='mute'>{html.escape(r['actor'] or '')} · {r['at']:%Y-%m-%d %H:%M}</span>{also}")
        pay = f"<pre>{html.escape(json.dumps(r['payload'], indent=1, ensure_ascii=False)[:4000])}</pre>"
        inner = f"<details class='pay'><summary>payload</summary>{pay}</details>" + "".join(node(rows, k) for k in kids)
        return f"<details open data-q='{html.escape((r['label'] or '') + ' ' + r['kind'] + ' ' + r['id'])}'><summary>{head}</summary>{inner}</details>"

    body = [f"<p class='mute'>Store: {html.escape(dsn_label)}. Each node shows once, under the data it was made from (inputs, dataset, run, "
            "model) when it has some, else another made-from link (recipe, module), else any other link (in, subject); among those, under the "
            f"latest committed. <i>also</i> lists its other parents. Left out, with everything under them: {html.escape(', '.join(hide) or 'nothing')}.</p>"
            "<input id='q' placeholder='filter: name, kind or id prefix' oninput='f(this.value)'> "
            "<button onclick=\"document.querySelectorAll('details:not(.pay)').forEach(d=>d.open=true)\">open all</button> "
            "<button onclick=\"document.querySelectorAll('details:not(.pay)').forEach(d=>d.open=false)\">close all</button>"]
    for ref, d, rows in blocks:
        body.append(f"<h2>{html.escape(ref)} <span class='mute'>({'what it was made from' if d == 'up' else 'what was made from / in it'}, "
                    f"{len(rows)} nodes)</span></h2>" + (node(rows, 0) if rows else "<p class='bad'>no such node</p>"))
    js = ("<script>function f(q){q=q.toLowerCase();document.querySelectorAll('details[data-q]').forEach(d=>{const hit=!q||d.dataset.q.toLowerCase()"
          ".includes(q)||d.querySelector('details[data-q]')&&[...d.querySelectorAll('details[data-q]')].some(x=>x.dataset.q.toLowerCase().includes(q));"
          "d.style.display=hit?'':'none';if(q&&hit)d.open=true;});}</script>")
    return "".join(body) + js


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", default=os.environ.get("BITT_DSN"))
    ap.add_argument("--ref", action="append", default=[], help="a start node (name, id or prefix); repeat for more")
    ap.add_argument("--up", action="store_true", help="walk up from the refs (what they were made from) instead of down")
    ap.add_argument("--all-kinds", action="store_true", help="keep events, checks, names and jobs too")
    a = ap.parse_args()
    if not a.dsn:
        sys.exit("node_tree: no store (--dsn or $BITT_DSN)")
    hide = [] if a.all_kinds else HIDE
    blocks = trees(a.dsn, [(r, "up" if a.up else "down") for r in a.ref], hide)
    sys.path.insert(0, str(ROOT / "scripts"))
    from build_reports import page
    label = psycopg.conninfo.conninfo_to_dict(a.dsn)
    css = ("<style>details{margin-left:18px;border-left:1px solid var(--line);padding-left:6px}summary{cursor:pointer;list-style:none}"
           "summary::before{content:'▸ ';color:var(--mute)}details[open]>summary::before{content:'▾ '}.kind{font:12px monospace;padding:1px 5px;"
           "border-radius:4px;background:var(--line)}.role,.also{color:var(--mute);font-size:13px}code{font-size:12px;color:var(--mute)}"
           "details.pay{border:0}details.pay>summary{font-size:12px;color:var(--mute)}pre{font-size:12px;overflow-x:auto;max-width:100%}"
           "#q{width:min(360px,100%);padding:4px}body{max-width:1200px}</style>")
    page(OUT, "Node tree", "A bitt store's nodes as a branch tree: each task and raw line with what was made from it (or the refs asked for), "
         "every node once, its payload one click away.", css + render(blocks, hide, f"{label.get('dbname')} on {label.get('host')}:{label.get('port')}"))
    subprocess.run([sys.executable, str(ROOT / "scripts" / "build_reports.py")], check=True)   # the hub lists it
    print(f"{OUT} ({sum(len(b[2]) for b in blocks)} nodes in {len(blocks)} trees)")


if __name__ == "__main__":
    main()
