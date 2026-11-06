"""The panel for development: `bitt serve` (bitt.panel.serve) plus the tour (bitt_tour) and every agent eval's store under
~/.bitt/evals, each with the same three levels (docs/v2/panel.md).

  uv run python scripts/viz_serve.py [--dsn <your store>] [--port 8765]        then open http://127.0.0.1:8765

  / or /stores  every eval as a lane of its runs (the panel's look), live; your store (--dsn or $BITT_DSN) is the top lane, /s/mine/
  /s/<store>/  a store's home, then /t/<task>, /t/<task>/c/<n>; /s/<store>/seq · /stores/seq the list's

Read only. An eval or tour store must be on the throwaway cluster. A store an older bitt made cannot be opened: its line says so.
"""
import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
EVALS = Path.home() / ".bitt" / "evals"
sys.path.insert(0, str(ROOT / "conformance"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
from backend import throwaway_problem  # noqa: E402
from bitt.panel.serve import Panel, Store, read_only  # noqa: E402,F401

def admin():
    return os.environ.get("BITT_PG_ADMIN_DSN") or subprocess.run([str(ROOT / "scripts" / "pg_throwaway.sh"), "dsn"], capture_output=True,
                                                                 text=True).stdout.strip()


def stores():
    """{key: (dsn, folder or None)}: the tour, then every eval folder, newest first."""
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    out = {"tour": (make_conninfo(**(conninfo_to_dict(admin()) | {"dbname": "bitt_tour"})), None)}
    for d in sorted((p.parent for p in EVALS.glob("*/dsn.txt")), key=lambda p: p.stat().st_mtime, reverse=True):
        out[d.name] = ((d / "dsn.txt").read_text().strip(), d)
    return out


MINE = {}                                                       # "mine": the owner's store, when --dsn / $BITT_DSN names one


def store_of(dsn, d):
    """A throwaway store (an eval's or the tour), read only; its blob reads from the eval's own folder."""
    if why := throwaway_problem(dsn):
        raise PermissionError(f"refused {dsn}: {why}")
    return Store.postgres(dsn, before=(lambda: os.environ.update({"BITT_BLOBS": str(d / "blobs"), "BITT_JOBS": str(d / "jobs")})) if d else None)


def kernel(dsn, d):
    return store_of(dsn, d).kernel()


def all_stores():
    out = {key: store_of(dsn, d) for key, (dsn, d) in stores().items()}
    return {**out, **({"mine": Store.postgres(MINE["dsn"])} if MINE else {})}


def tasks(k):
    from bitt import names
    return [names.task_name(k, n["id"]) or n["id"][:12] for n in sorted(k.rec.find("goal"), key=lambda n: n["seq"])
            if not n["links"].get("in")]


def running_dirs():
    """The eval folders an agent is working in now (an `opencode run … --dir <folder>` process)."""
    out = subprocess.run(["pgrep", "-fl", "opencode run"], capture_output=True, text=True).stdout
    return {Path(m).name for m in re.findall(r"--dir (\S+)", out)}


def last_at(k, d):
    """The newest write: the store's newest node, or the agent's transcript (it thinks between commands), in seconds."""
    at = max((n["stamp"].get("at", 0) for n in k.rec.nodes.values()), default=0) / 1e9
    tx = d / "agent.jsonl" if d else None
    return max(at, tx.stat().st_mtime if tx and tx.exists() else 0)


def state(key, d, live):
    if key in live:
        return "running"
    if d is None:
        return "tour"
    if key.startswith("ref-"):
        return "reference"
    return "graded" if (d / "grade.txt").exists() or (d / "check.txt").exists() else "stopped"


# ---------------------------------------------------------------- the list of stores, drawn like the panel's home
CACHE = {}                                                      # key → (signature, row): a store that stopped changing is read once


def sig(key, d, live):
    """What makes a store's row stale: running → always; otherwise its folder and its grade / check files."""
    if key in live or d is None:
        return None
    fs = [d, d / "grade.txt", d / "check.txt", d.parent / f"{d.name}.check.log"]
    return tuple(f.stat().st_mtime if f.exists() else 0 for f in fs)


def row(key, dsn, d, live):
    """One store's row: {key, ev, at, state, tasks, result, ok, err}; cached until its signature moves."""
    g = sig(key, d, live)
    if g is not None and key in CACHE and CACHE[key][0] == g:
        return CACHE[key][1]
    ev = re.sub(r"-\d{8}-\d{6}$", "", key)
    ref = key.startswith("ref-")
    r = {"key": key, "ev": ev[4:] if ref else ev, "ref": ref, "state": state(key, d, live), "tasks": [], "err": None,
         "at": d.stat().st_mtime if d else 0}
    try:
        k = kernel(dsn, d)
        r["tasks"], r["at"] = tasks(k), last_at(k, d)
    except Exception as e:                                       # gone, or an older bitt made it
        r["err"] = f"{type(e).__name__}: {str(e).splitlines()[0][:120] if str(e) else ''}"
    f = next((x for x in (d / "grade.txt", d / "check.txt", d.parent / f"{d.name}.check.log") if x.exists()), None) if d else None
    last = f.read_text().strip().splitlines()[-1] if f and f.read_text().strip() else ""
    m = re.match(r"(?:\S+: )?(\d+)/(\d+)", last)
    r["result"], r["ok"] = last, (m.group(1) == m.group(2)) if m else None
    r["score"] = m.group(1) if m else ""
    CACHE[key] = (g, r)
    return r


def rows():
    live = running_dirs()
    out = [row(key, dsn, d, live) for key, (dsn, d) in stores().items()]
    return sorted(out, key=lambda r: r["at"])                   # oldest first: a lane reads left to right


def list_seq():
    """The list's seq: moves when any row changes (a new run, a grade, a running store's write)."""
    import zlib
    return zlib.crc32(repr([(r["key"], r["state"], r["result"], int(r["at"])) for r in rows()]).encode()) | 1


LIST_CSS = """<style>
.tile.ev-full{border-color:var(--ok);color:var(--ok)}.tile.ev-miss{border-color:var(--bad);color:var(--bad)}
.tile.ev-run{background:var(--work);border-color:var(--work);color:var(--paper);background-image:repeating-linear-gradient(135deg,transparent 0 5px,rgba(255,255,255,.35) 5px 10px);background-size:28px 28px;animation:slide 1.6s linear infinite}
.tile.ev-stop{border-style:dashed}.tile.ev-old{border-color:var(--rule);color:var(--rule)}
.tile.ev-ref{border-radius:50%}.lane .tiles .sep{width:1px;height:22px;background:var(--rule);margin:0 2px}
</style>"""


def ev_tile(r):
    from bitt.panel.view import e
    cls = ("ev-run" if r["state"] == "running" else "ev-old" if r["err"] else "ev-full" if r["ok"] else "ev-miss" if r["ok"] is False
           else "ev-stop")
    tip = " · ".join(x for x in (r["key"], r["state"], r["result"], r["err"]) if x)
    inner = f"<span class='tile {cls}{' ev-ref' if r['ref'] else ''}'>{e(r['score']) if r['state'] != 'running' else ''}</span>"
    return inner if r["err"] else f"<a href='/s/{quote(r['key'])}/' title='{e(tip)}'>{inner}</a>"


def index(show="all"):
    """Every eval as a lane: its reference (a round tile), then each agent run, oldest → newest; green = full marks, red = a miss,
    striped = running, dashed = stopped ungraded, faint = made by an older bitt. The page redraws itself when any row moves."""
    from bitt.panel import view as V
    rs, lanes = rows(), {}
    for r in rs:
        lanes.setdefault(r["ev"], []).append(r)
    order = sorted(lanes, key=lambda ev: (not any(x["state"] == "running" for x in lanes[ev]), -max(x["at"] for x in lanes[ev])))
    out = []
    if MINE:
        out.append("<div class='lane'><div class='nm'><a href='/s/mine/'>your store</a></div><div class='tiles'></div></div>")
    for ev in order:
        runs = lanes[ev]
        refs, agents = [x for x in runs if x["ref"]], [x for x in runs if not x["ref"]]
        tiles = "".join(ev_tile(x) for x in refs) + ("<span class='sep'></span>" if refs and agents else "") + "".join(ev_tile(x) for x in agents)
        last = (agents or refs)[-1]
        busy = any(x["state"] == "running" for x in runs)
        out.append(f"<div class='lane {'busy' if busy else ''}' data-seq='{int(last['at'])}'><div class='nm'>{V.e(ev)}"
                   f"{'<span class=blip></span>' if busy else ''}</div><div class='tiles'>{tiles}</div><span></span>"
                   f"<div class='last'><span data-at='{int(last['at'])}'></span> · {V.e(last['state'])}{' · ' + V.e(last['result']) if last['result'] else ''}</div></div>")
    body = f"<h1>Agent evals</h1><div style='margin-top:12px'>{''.join(out)}</div>"
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<meta name='report:purpose' content='Every agent eval run on this machine, one lane per eval.'><title>Agent evals</title>"
            f"{V.CSS}{LIST_CSS}</head><body><main>{body}</main>{V.AGO_JS}{V.live_js('/stores/seq', list_seq())}</body></html>\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--dsn", default=os.environ.get("BITT_DSN"), help="your own store (read only); default $BITT_DSN")
    a = ap.parse_args()
    if a.dsn:
        MINE["dsn"] = a.dsn
    extra = lambda parts, q: index() if parts in ([], ["stores"]) else str(list_seq()) if parts == ["stores", "seq"] else None  # noqa: E731
    srv = Panel(all_stores, extra=extra).server(a.port)
    import threading
    threading.Thread(target=rows, daemon=True).start()          # read every store once now, so the first page is quick
    print(f"bitt live: http://127.0.0.1:{a.port}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
