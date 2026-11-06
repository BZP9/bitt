"""bitt command line (docs/v2/foundation.md §D2): the types, the joins, the workflow, the reads.

the types (on the shelf: any task uses them)
  bitt module add <file.py> [--name N]           a module: its function is its contract (kind, reads, writes, params, does)
  bitt module wrap <module> --name N --does "…" [--params k=v …] [--fill role=artifact …]   fixed params / artifacts = a module
  bitt artifact add <file> --kind K [--name N] [--does "…"]   content used whole: a prompt (needs → gives), a rubric, a model file …
  bitt module list · bitt artifact list
  bitt data load <file> --line L --does "…" --sensitivity S [--with <loader>] [--params k=v …]   rows into raw.<line> (once each)
  bitt data list [words …] [--task T]          every named data line: what it is for, its rows, versions, source (find data by its words)
  bitt data tables [--task T] · bitt data inspect <data> [--task T] · bitt data exclude <dataset> --rows <file> --because "…"
the joins
  bitt recipe <module> [--cols role=column …] [--fill role=artifact …] [--params k=v …] [--name N] [--why "…"]
  bitt recipe list
  bitt run go <recipe> --on <data> [--read role=data …] [--full] [--as dataset|evalset|selection|artifact --line L [--artifact-kind examples]] [--env E] [--evals <recipe> …] [--endpoint <module>]
  bitt run status [<run>] · bitt run sync [<job>] · bitt run answer <run> --file answers.jsonl · bitt run close <run>
the workflow
  bitt task new <name> "<problem>" · bitt goal new <task|goal> "<problem>"
  bitt cycle new <task|goal> "<question>" [--level working] · cycle use / list / close / park / resume / abandon / earlystop / iterate
  bitt want <kind> [--name N] [--contract json] · bitt plan --arms <ref> … --win "…" [--eval <pipeline> | --judged-by person]
  bitt note "<text>" --evidence <ref> … [--conclusion] · bitt validate <ref> pass|fail|approve|reject
  bitt tag <ref> --version | --alias A | --trust trusted|hint [--agreement <run>] | --deprecated "why"  [--because <finding> …]
  bitt ack <ref> --rule R --reason "…" · bitt grant / revoke
the reads
  bitt show <anything> · bitt log [task] [-n N] · bitt tasks · bitt cards [tool] · bitt lint · bitt init · bitt call <card> k=v …
  bitt serve [--port 8765]                        the panel, live and read only: http://127.0.0.1:8765 (docs/v2/panel.md)

Where work goes: your current cycle (bitt cycle use), or --in <cycle | task | goal> for one call.
The store: --dsn <postgres dsn> (default: $BITT_DSN). Who you are: --as <actor> (default: $BITT_ACTOR; else `usr` at a terminal,
`agent:cli` when not). Every write is a kernel call: a refusal prints the reason and its `next:` step, exit 2.
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

from . import cards, names, sets
from .errors import Failed, Refused
from .kernel import Kernel
from .tools import refs, where
from .walk import Walk


def open_record(args):
    dsn = args.dsn or os.environ.get("BITT_DSN")
    if not dsn:
        sys.exit("bitt: no store. Pass --dsn DSN or set BITT_DSN (a Postgres database).")
    from .record.postgres import PostgresRecord
    return PostgresRecord(dsn)


def _value(v):
    try:
        return json.loads(v)
    except ValueError:
        return v


def kv(items, what):
    out = {}
    for it in items or []:
        k, sep, v = it.partition("=")
        if not sep or not k:
            raise SystemExit(f"bitt: {what} takes key=value, not {it!r}")
        out[k] = _value(v)
    return out


def git_source(path):
    """{path, repo, commit}: the commit is the file's last one when the file is committed and unchanged since (else None)."""
    p = Path(path).resolve()
    run = lambda *a: subprocess.run(["git", "-C", str(p.parent), *a], capture_output=True, text=True)  # noqa: E731
    top = run("rev-parse", "--show-toplevel")
    if top.returncode:
        return {"path": str(p), "repo": None, "commit": None}
    tracked = run("ls-files", "--error-unmatch", str(p)).returncode == 0
    clean = tracked and run("diff", "--quiet", "HEAD", "--", str(p)).returncode == 0
    commit = run("log", "-1", "--format=%H", "--", str(p)).stdout.strip() if clean else None
    return {"path": str(p.relative_to(top.stdout.strip())), "repo": top.stdout.strip(), "commit": commit or None}


def add_parsers(ap):
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("module", help="modules on the shelf")
    ms = s.add_subparsers(dest="verb", required=True)
    c = ms.add_parser("add")
    c.add_argument("file")
    c.add_argument("--name")
    c = ms.add_parser("wrap")
    c.add_argument("module")
    c.add_argument("--name", required=True)
    c.add_argument("--does", required=True)
    c.add_argument("--params", nargs="*")
    c.add_argument("--fill", nargs="*")
    c.add_argument("--pin", nargs="*", help="role=data …: `on` = the only units it walks; another role = a fixed read")
    ms.add_parser("list")
    s = sub.add_parser("artifact", help="artifacts on the shelf")
    as_ = s.add_subparsers(dest="verb", required=True)
    c = as_.add_parser("add")
    c.add_argument("file")
    c.add_argument("--kind", required=True)
    c.add_argument("--name")
    c.add_argument("--does")
    as_.add_parser("list")
    s = sub.add_parser("data", help="loaded and made data")
    ds = s.add_subparsers(dest="verb", required=True)
    c = ds.add_parser("load")
    c.add_argument("file")
    c.add_argument("--line", required=True)
    c.add_argument("--does", required=True, help="what the data is, in one sentence: how it is found later")
    c.add_argument("--sensitivity", required=True, choices=["public", "internal", "company", "personal"])
    c.add_argument("--with", dest="with_")
    c.add_argument("--params", nargs="*")
    c.add_argument("--sheet")
    c = ds.add_parser("list")
    c.add_argument("words", nargs="*", help="find data by these words (its name, what it is for, its columns, its source)")
    c.add_argument("--task")
    c = ds.add_parser("tables")
    c.add_argument("--task")
    c = ds.add_parser("inspect")
    c.add_argument("ref")
    c.add_argument("-n", type=int, default=5)
    c.add_argument("--task", help="only the rows that task's runs made or reused (A23)")
    c = ds.add_parser("exclude")
    c.add_argument("set")
    c.add_argument("--rows", required=True, help="a file: one row hash per line")
    c.add_argument("--because", required=True)
    s = sub.add_parser("recipe", help="a module, with these settings, on these columns")
    s.add_argument("module")
    s.add_argument("--cols", nargs="*")
    s.add_argument("--fill", nargs="*")
    s.add_argument("--params", nargs="*")
    s.add_argument("--name")
    s.add_argument("--why")
    s.add_argument("--samples", type=int, help="ask N times per row (a generate): every ask is a unit a check and rate count")
    s.add_argument("--sample-rows", dest="sample_rows", type=int, help="the ladder's sample rung: smoke 1 row, then this many (default 10), then all")
    s = sub.add_parser("run", help="run a recipe over data")
    rs = s.add_subparsers(dest="verb", required=True)
    c = rs.add_parser("go")
    c.add_argument("recipe")
    c.add_argument("--on", nargs="+")
    c.add_argument("--read", nargs="+", help="role=data …: the other inputs a join looks up (docs/v2/inputs.md)")
    c.add_argument("--full", action="store_true")
    c.add_argument("--as", dest="as_", choices=["selection", "dataset", "evalset", "artifact"])
    c.add_argument("--artifact-kind", dest="artifact_kind", help="with --as artifact: examples, rubric, … (docs/v2/walk.md W4)")
    c.add_argument("--line")
    c.add_argument("--parent")
    c.add_argument("--fills")
    c.add_argument("--env")
    c.add_argument("--evals", nargs="*")
    c.add_argument("--endpoint")
    c.add_argument("--skip-smoke", action="store_true")
    c.add_argument("--min-n", type=int)
    c = rs.add_parser("status")
    c.add_argument("run", nargs="?")
    c = rs.add_parser("sync")
    c.add_argument("job", nargs="?")
    c = rs.add_parser("answer")
    c.add_argument("run")
    c.add_argument("--file", required=True, help="jsonl: {\"row\": <hash or prefix>, \"answer\": \"…\"} per line")
    c = rs.add_parser("close")
    c.add_argument("run")
    s = sub.add_parser("task")
    s.add_argument("verb", choices=["new"])
    s.add_argument("name")
    s.add_argument("problem")
    s = sub.add_parser("goal")
    s.add_argument("verb", choices=["new"])
    s.add_argument("under")
    s.add_argument("problem")
    s = sub.add_parser("cycle")
    cs = s.add_subparsers(dest="verb", required=True)
    c = cs.add_parser("new")
    c.add_argument("under")
    c.add_argument("question")
    c.add_argument("--level", choices=["explore", "working"], default="explore")
    c = cs.add_parser("use")
    c.add_argument("cycle")
    c = cs.add_parser("list")
    c.add_argument("task", nargs="?")
    for o in ("close", "park", "resume", "abandon", "earlystop", "iterate", "spawn"):
        c = cs.add_parser(o)
        c.add_argument("cycle", nargs="?")
        c.add_argument("--reason")
    s = sub.add_parser("want")
    s.add_argument("kind", choices=["dataset", "evalset", "module", "artifact", "recipe", "run"])
    s.add_argument("--name")
    s.add_argument("--contract", default="{}")
    s = sub.add_parser("plan")
    s.add_argument("--arms", nargs="+", required=True)
    s.add_argument("--win", required=True)
    s.add_argument("--eval")
    s.add_argument("--judged-by", choices=["person"])
    s = sub.add_parser("note")
    s.add_argument("text")
    s.add_argument("--evidence", nargs="+", required=True)
    s.add_argument("--conclusion", action="store_true")
    s = sub.add_parser("validate")
    s.add_argument("ref")
    s.add_argument("verdict", choices=["pass", "fail", "approve", "reject"])
    s.add_argument("--evidence", nargs="*")
    s = sub.add_parser("tag")
    s.add_argument("ref")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--version", action="store_true")
    g.add_argument("--alias")
    g.add_argument("--trust", choices=["trusted", "hint"])
    g.add_argument("--deprecated")
    s.add_argument("--because", nargs="*")
    s.add_argument("--agreement")
    s = sub.add_parser("ack")
    s.add_argument("ref")
    s.add_argument("--rule")
    s.add_argument("--reason", required=True)
    s = sub.add_parser("grant")
    s.add_argument("agent")
    s.add_argument("acts", nargs="+", choices=["close", "earlystop", "validate_pass"])
    s.add_argument("--on", required=True)
    s.add_argument("--reason", required=True)
    s = sub.add_parser("revoke")
    s.add_argument("grant")
    s.add_argument("--reason", required=True)
    s = sub.add_parser("show")
    s.add_argument("ref")
    s = sub.add_parser("log")
    s.add_argument("task", nargs="?")
    s.add_argument("-n", type=int, default=30)
    s.add_argument("--all", action="store_true", help="every event, refusal and warning, in order, with the time")
    s = sub.add_parser("cards")
    s.add_argument("tool", nargs="?")
    s = sub.add_parser("call")
    s.add_argument("card")
    s.add_argument("args", nargs="*", help="key=value")
    sub.add_parser("lint")
    s = sub.add_parser("serve", help="the panel, live and read only: every task, a task, a cycle (docs/v2/panel.md)")
    s.add_argument("--port", type=int, default=8765)
    sub.add_parser("init")
    sub.add_parser("tasks")
    for p in list(sub.choices.values()) + [q for g in (ms, as_, ds, rs, cs) for q in g.choices.values()]:
        if not any(isinstance(x, argparse._SubParsersAction) for x in p._actions) and not p.prog.endswith(" serve"):   # a leaf command (serve: no cycle)
            p.add_argument("--in", dest="in_", default=None, help="the cycle (or task / goal) this call works in")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="bitt", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dsn")
    ap.add_argument("--as", dest="actor", help="usr[:name] or agent:<name>")
    add_parsers(ap)
    args = ap.parse_args(argv)
    try:
        from . import skills
        skills.sync()                          # the installed skills always match this repo's SKILL.md
    except OSError as x:
        print(f"bitt: could not sync skills ({x})", file=sys.stderr)
    if args.cmd == "lint":
        sys.argv = ["bitt-lint"]
        return cards.main()
    if args.cmd == "serve":                    # reads only: no kernel call, no actor
        dsn = args.dsn or os.environ.get("BITT_DSN")
        if not dsn:
            print("bitt: no store to show. next: bitt --dsn <dsn> serve (or set BITT_DSN)", file=sys.stderr)
            return 2
        from .panel import serve
        return serve.main(dsn, args.port)
    from .tools import packages
    where.STORE, where.SHOWN = args.dsn or os.environ.get("BITT_DSN") or "memory", set()
    k = Kernel(open_record(args), packages=packages())
    actor = args.actor or os.environ.get("BITT_ACTOR") or ("usr" if sys.stdin.isatty() else "agent:cli")
    refs.ACTOR = actor

    def call(card, a):
        out = k.call(card, a, actor)
        for w in out.get("warnings", []):
            print(f"warning: {w}", file=sys.stderr)
        return out
    try:
        return _run(k, args, call) or 0
    except (Refused, Failed) as x:
        print(f"refused: {x}", file=sys.stderr)
        return 2
    except SystemExit as x:
        if isinstance(x.code, str):
            print(x.code, file=sys.stderr)
            return 2
        raise


# ---------------------------------------------------------------- where
def cycle_of(k, args, what):
    """The cycle this call works in: --in (a cycle, or a task / goal: its current or only open cycle), else your current cycle."""
    if getattr(args, "in_", None):
        nid = refs.node(k, args.in_, kinds=["cycle", "goal"], quiet=True)
        c = nid if k.node(nid)["kind"] == "cycle" else where.pick(k, nid, what)
    else:
        c = where.current(k)
        if not c:
            raise SystemExit(f"bitt: {what}: no current cycle. next: bitt cycle new <task> \"<question>\" (or bitt cycle use <cycle>), "
                             "or --in <cycle>")
    where.show(k, c)
    return c


def task_of(k, args):
    if getattr(args, "task", None):
        return names.task_by_name(k, args.task)
    c = where.current(k)
    return k.task_of(c) if c else None


def node(k, x, task=None, kinds=None):
    return refs.node(k, x, task, kinds)


def short(k, nid, task=None):
    from .tools import recipe as recipes
    n = k.node(nid)
    if n["kind"] == "recipe":
        return recipes.label(k, nid, task)
    if n["kind"] in ("module", "artifact", "dataset", "evalset", "raw", "goal"):
        return names.ref_of(k, nid, task)
    if n["kind"] == "cycle":
        return where.ref(k, nid)
    return f"{n['kind']} {nid[:12]}"


# ---------------------------------------------------------------- commands
def _run(k, args, call):
    cmd = args.cmd
    if cmd == "module":
        return cmd_module(k, args, call)
    if cmd == "artifact":
        return cmd_artifact(k, args, call)
    if cmd == "data":
        return cmd_data(k, args, call)
    if cmd == "recipe":
        return cmd_recipe(k, args, call)
    if cmd == "run":
        return cmd_run(k, args, call)
    if cmd in ("task", "goal", "cycle", "want", "plan", "note", "validate", "tag", "ack", "grant", "revoke"):
        return cmd_workflow(k, args, call)
    if cmd == "show":
        return cmd_show(k, args)
    if cmd == "log":
        return cmd_log(k, args)
    if cmd == "cards":
        for cid, e in sorted(k.eff.items()):
            if e.get("kind") != "maneuver" or (args.tool and not cid.startswith(args.tool + ".")):
                continue
            ins = [f"{n}*" for n in cards.fields(e, "in", "min")] + list(cards.fields(e, "in", "opt"))
            print(f"{cid:<22} open in {','.join(e.get('open_in') or ['any'])}: {' '.join(ins)}")
        return 0
    if cmd == "call":
        print(json.dumps(call(args.card, kv(args.args, "call")), default=str))
        return 0
    if cmd == "init":
        print(f"ok: {len(k.rec.nodes)} nodes, contract {k.version}")
        return 0
    if cmd == "tasks":
        for n in k.rec.find("goal"):
            if not n["links"].get("in"):
                print(f"{names.task_name(k, n['id']) or '-':<14} {n['payload'].get('problem')}")
        return 0


def cmd_module(k, args, call):
    if args.verb == "list":
        return listing(k, "module")
    cyc = cycle_of(k, args, f"module {args.verb}")
    if args.verb == "add":
        from .builtins import SHIPPED
        p = Path(args.file)
        if not p.exists() and args.file in SHIPPED:              # a module bitt ships: `bitt module add length`
            p = SHIPPED[args.file]
        if not p.exists():
            raise SystemExit(f"bitt: module add: no file {args.file} (bitt ships: {', '.join(sorted(SHIPPED))})")
        src = {} if p.parent == SHIPPED[next(iter(SHIPPED))].parent else {"source": git_source(p)}
        m = call("module.define", {"in": cyc, "code": p.read_bytes(), "name": args.name or p.stem, **src})["module"]
        h = k.node(m)["payload"]["header"]
        print(f"module {names.ref_of(k, m)}: a {h['kind']}, reads {h['reads'] or '-'} → writes {h['writes'] or '-'}"
              f"{', params ' + ', '.join(h['params']) if h['params'] else ''}: {h['does']}")
        if src and not (k.node(m)["payload"].get("source") or {}).get("commit"):
            print("  (not committed in git yet: a version tag needs it committed; commit, then add it again)")
        print(f"next: bitt recipe {names.label(k, m).split('/')[-1]} --cols <role>=<column> …")
        return 0
    w = call("module.wrap", {"in": cyc, "module": node(k, args.module, k.task_of(cyc), ["module"]), "name": args.name,
                             "does": args.does, "params": kv(args.params, "--params"), **({"artifacts": kv(args.fill, "--fill")} if args.fill else {}),
                             **({"pin": kv(args.pin, "--pin")} if args.pin else {})})["wrap"]
    print(f"module {names.ref_of(k, w)}: wraps {names.ref_of(k, k.node(w)['links']['wraps'])}\nnext: bitt recipe {args.name} …")
    return 0


def cmd_artifact(k, args, call):
    if args.verb == "list":
        return listing(k, "artifact")
    cyc = cycle_of(k, args, "artifact add")
    p = Path(args.file)
    if not p.exists():
        raise SystemExit(f"bitt: artifact add: no file {args.file}")
    a = call("artifact.add", {"in": cyc, "content": p.read_bytes(), "artifact_kind": args.kind, "name": args.name or p.stem,
                              "source": git_source(p), **({"does": args.does} if args.does else {})})["artifact"]
    c = k.node(a)["payload"]["contract"]
    print(f"artifact {names.ref_of(k, a)}: a {args.kind}" + (f", needs {c['needs']} → gives {list(c['gives'])}" if c.get("needs") else "")
          + f": {k.node(a)['payload']['does']}")
    return 0


def listing(k, kind):
    from .tools.tag import deprecated
    for b in k.rec.find("name"):
        if b["payload"]["kind"] != kind:
            continue
        ms = names.members(k, b["links"]["target"])
        new = ms[-1]
        tags = [t["payload"]["value"] for m in ms for t in names.tags(k, m["id"], "alias")]
        extra = f" (wraps {names.ref_of(k, new['links']['wraps'])})" if new["links"].get("wraps") else ""
        d = deprecated(k, new["id"])
        print(f"{names.ref_of(k, new['id']):<32} {len(ms)} member(s){' @' + ' @'.join(tags) if tags else ''}{extra}"
              f"{'  DEPRECATED: ' + d if d else ''}  {new['payload'].get('does') or new['payload'].get('header', {}).get('does') or ''}")
    return 0


def cmd_data(k, args, call):
    if args.verb == "load":
        p = Path(args.file)
        if not p.exists():
            raise SystemExit(f"bitt: data load: no file {args.file}")
        cyc = where.current(k) if not args.in_ else cycle_of(k, args, "data load")
        a = {"bytes": p.read_bytes(), "origin": f"file:{p.name}", "sensitivity": args.sensitivity, "line": args.line, "does": args.does,
             **({"in": cyc} if cyc else {}), **({"sheet": args.sheet} if args.sheet else {})}
        if args.with_:
            a.update({"with": node(k, args.with_, k.task_of(cyc) if cyc else None, ["module"]), "params": kv(args.params, "--params")})
        r = call("data.load", a)["raw"]
        pl = k.node(r)["payload"]
        print(f"{names.ref_of(k, r)}: {pl['n_rows']} rows ({pl['new_rows']} new) into {pl['table']}\nnext: bitt data inspect "
              f"{names.ref_of(k, r)}, or bitt recipe <module> --cols … then bitt run go <recipe> --on {names.label(k, r)}")
        return 0
    if args.verb == "list":
        return list_cmd(k, args)
    if args.verb == "tables":
        return tables_cmd(k, args)
    if args.verb == "inspect":
        return inspect_cmd(k, args)
    cyc = cycle_of(k, args, "data exclude")
    s = node(k, args.set, k.task_of(cyc), ["dataset", "evalset"])
    rows = [x.strip() for x in Path(args.rows).read_text().splitlines() if x.strip()]
    mark = call("data.exclude", {"in": cyc, "set": s, "rows": rows, "because": args.because})["mark"]
    full = k.node(mark)["payload"]["rows"]
    exc = names.binding(k, "lib", "exclude")
    if not exc:
        from .builtins import SHIPPED
        call("module.define", {"in": cyc, "code": SHIPPED["exclude"].read_bytes(), "name": "exclude"})
    r = call("recipe.make", {"in": cyc, "module": "exclude", "params": {"drop": full}, "why": args.because})["recipe"]
    line = names.label(k, s).split("/")[-1]
    out = call("run.go", {"in": cyc, "recipe": r, "on": [s], "as": k.node(s)["kind"], "line": line, "parent": s})
    print(f"{len(full)} rows marked excluded on {names.ref_of(k, s)} ({args.because}); the new version {short(k, out['set'])} holds "
          f"{len(Walk(k).set_rows(k.node(out['set'])['payload']['set']))} rows (the old one keeps its rows)\n"
          f"next: bitt tag {line} --version --because <finding>")
    return 0


def data_lines(k, task=None):
    """Every named data line (raw imports, datasets, evalsets), newest version each: what it is for (a raw line's `does`; a dataset's:
    the module that made it, and its `does`), rows, versions, task, columns, source. `task`: that task's lines, and every raw line."""
    out = {}
    for n in sorted((n for n in k.rec.nodes.values() if n["kind"] in ("raw", "dataset", "evalset")), key=lambda n: n["seq"]):
        lab = names.label(k, n["id"])
        if not lab:
            continue
        t = k.task_of(n["id"]) if n["kind"] != "raw" else None
        if task and n["kind"] != "raw" and t != task:
            continue
        it = out.setdefault((n["kind"], lab), {"line": lab, "kind": n["kind"], "versions": 0})
        p = n["payload"]
        it.update(id=n["id"], ref=names.ref_of(k, n["id"]), rows=len(Walk(k).set_rows(p["set"])) if p.get("set") else 0,
                  task=names.task_name(k, t) if t else "", table=p.get("table", ""), versions=it["versions"] + 1)
        if n["kind"] == "raw":
            it.update(does=p.get("does") or "", source=p.get("origin", ""))
        else:
            rc = k.node(n["links"]["recipe"]) if n["links"].get("recipe") else None
            m = k.node(rc["links"]["module"]) if rc and rc["links"].get("module") else None
            ons = ", ".join(names.label(k, x) or x[:12] for x in Walk(k).links(n["id"], "on"))
            it.update(does=(p.get("does") or (f"made by {names.label(k, m['id'])}: " + (m["payload"].get("header", {}).get("does") or "")
                                              if m else "")), source=f"from {ons}" if ons else "")
        spec = k.rec.spec(it["table"]) if it["table"] else None
        it["columns"] = [c["name"] for c in (spec or {}).get("columns", []) if not c["name"].startswith("bitt_")]
    return list(out.values())


def plural_n(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def match_lines(lines, words):
    """The lines that mention any of the words (in the name, what it is for, the source, the task, a column), most words first."""
    words = [w.lower() for w in words]
    hay = lambda it: " ".join([it["line"], it["does"], it["source"], it["task"], *it["columns"]]).lower().replace("_", " ")  # noqa: E731
    scored = [(sum(w in hay(it) for w in words), it) for it in lines]
    return [it for n, it in sorted(scored, key=lambda x: -x[0]) if n]


def list_cmd(k, args):
    task = names.task_by_name(k, args.task) if args.task else None
    lines = data_lines(k, task)
    if args.words:
        lines = match_lines(lines, args.words)
        if not lines:
            print(f"no data line mentions {' '.join(args.words)!r}; `bitt data list` shows every line, `bitt data tables` every table")
            return 0
    if not lines:
        print("no data yet: bitt data load <file> --line L --does \"…\" --sensitivity S")
        return 0
    for it in lines:
        print(f"{it['ref']:<28} {it['kind']:<8} {it['rows']:>6} rows  {it['does'] or '(says nothing about what it is)'}\n"
              f"{'':<28} {(it['task'] + ' · ') if it['task'] else ''}{it['source']}"
              f"{' · ' if it['source'] else ''}{plural_n(it['versions'], 'import') + ' · ' if it['kind'] == 'raw' else ''}"
              f"columns {', '.join(it['columns'])}")
    print(f"next: bitt data inspect {lines[0]['ref']} -n 20 (its rows), bitt show {lines[0]['ref']} (how it was made)")
    return 0


def tables_cmd(k, args):
    task = names.task_by_name(k, args.task) if args.task else None
    mine = sets.task_rows(k, task) if task else None
    for t, spec in sorted(k.rec.all_specs().items()):
        if spec["shape"] not in ("raw", "output") or (mine is not None and t not in mine and not t.startswith("raw.")):
            continue
        n = len(k.rec.table_rows(t))
        cols = [c["name"] for c in spec["columns"] if not c["name"].startswith("bitt_")]
        own = f" ({len(mine[t])} this task's)" if mine and t in mine else ""
        print(f"{t:<32} {n:>6} rows{own}  {', '.join(cols)}")
    return 0


def inspect_cmd(k, args):
    from .tools.run import input_of
    nid = node(k, args.ref)
    t, sh = input_of(k, nid)
    ms = [(m, sp) for _, m, sp in Walk(k).set_rows(sh)]
    if args.task:                                               # a task's own rows: those its runs made or reused (A23)
        mine = sets.task_rows(k, names.task_by_name(k, args.task)).get(t, set())
        print(f"{sum(m in mine for m, _ in ms)} of {len(ms)} rows are task {args.task}'s")
        ms = [(m, sp) for m, sp in ms if m in mine]
    splits = {}
    for _, sp in ms:
        splits[sp] = splits.get(sp, 0) + 1
    print(f"{short(k, nid)}: {len(ms)} rows of {t}" + (f", splits {splits}" if any(splits) and None not in splits else ""))
    cols = [c["name"] for c in k.rec.spec(t)["columns"] if not c["name"].startswith("bitt_")]
    for m, sp in ms[: args.n]:
        row = k.rec.get_row(t, (m,))
        print(f"  {m[:10]} {sp or '':<5} " + " · ".join(f"{c}={str(row.get(c))[:40]!r}" for c in cols))
    return 0


def cmd_recipe(k, args, call):
    from .tools import recipe as recipes
    cyc = cycle_of(k, args, "recipe")
    task = k.task_of(cyc)
    if args.module == "list" and not args.cols:
        for r in recipes.in_task(k, task):
            n = k.node(r)
            cols = ", ".join(f"{a} ← {b}" for a, b in n["payload"]["cols"].items())
            alias = f" (alias {b['payload']['name']})" if (b := names.bound(k, r)) else ""
            print(f"{recipes.label(k, r, task):<30} {names.ref_of(k, n['links']['module'], task)}  {cols}  {n['payload']['params'] or ''}{alias}")
        return 0
    a = {"in": cyc, "module": node(k, args.module, task, ["module"]), "params": kv(args.params, "--params"),
         "cols": kv(args.cols, "--cols")}
    if args.fill:
        a["artifacts"] = kv(args.fill, "--fill")
    a.update({k_: v for k_, v in (("name", args.name), ("why", args.why), ("samples", args.samples), ("sample_rows", args.sample_rows)) if v})
    r = call("recipe.make", a)["recipe"]
    n = k.node(r)
    print(f"recipe {recipes.label(k, r, task)}{f' (alias {args.name})' if args.name else ''}: {names.ref_of(k, n['links']['module'], task)}"
          + "".join(f", {x} ← {y}" for x, y in n["payload"]["cols"].items())
          + (f", params {n['payload']['params']}" if n["payload"]["params"] else "")
          + f"\nnext: bitt run go {recipes.label(k, r, task)} --on <data>")
    return 0


def cmd_run(k, args, call):
    from .tools import recipe as recipes
    from .tools.run import land, one_row, status_of
    if args.verb == "sync":
        jobs = [node(k, args.job, kinds=["job"])] if args.job else [j["id"] for j in k.rec.find("job") if k.job_status(j["id"]) == "running"]
        for j in jobs:
            st = k.node(call("exec.job.sync", {"job": j})["job_status"])["payload"]["status"]
            print(f"job {j[:12]}: {st}")
        return 0
    if args.verb == "status":
        if args.run:
            return cmd_show(k, argparse.Namespace(ref=args.run))
        task = task_of(k, args)
        for r in k.rec.find("run"):
            if task and k.task_of(r["id"]) != task:
                continue
            e = k.rec.get_row("bitt.run_end", (r["id"],)) or {}
            print(f"{r['id'][:12]} {r['payload']['kind']:<9} {recipes.label(k, r['links']['recipe']):<28} {status_of(k.rec, r['id']):<7} "
                  f"rung {r['payload'].get('rung') or '-'}/{r['payload'].get('of') or '-'} made {e.get('made', '-')} reused {e.get('reused', '-')}")
        return 0
    cyc = cycle_of(k, args, f"run {args.verb}")
    task = k.task_of(cyc)
    if args.verb in ("answer", "close"):
        run = node(k, args.run, task, ["run"])
        if args.verb == "close":
            out = k.node(call("run.close", {"in": cyc, "run": run})["closed"])["payload"]
            print(f"run {run[:12]} closed: {out['answered']} of {out['of']} rows answered")
            return 0
        answers = {}
        for line in Path(args.file).read_text().splitlines():
            if line.strip():
                x = json.loads(line)
                answers[str(x["row"])] = x["answer"] if isinstance(x["answer"], str) else json.dumps(x["answer"])
        out = k.node(call("run.answer", {"in": cyc, "run": run, "answers": answers})["answered"])["payload"]
        print(f"run {run[:12]}: {out['made']} answers added ({out['kept']} already answered)\nnext: bitt run close {run[:12]} when done")
        return 0
    r = node(k, args.recipe, task, ["recipe"])
    a = {"in": cyc, "recipe": r, **({"on": [node(k, x, task) for x in args.on]} if args.on else {})}
    if args.read:
        pairs = [x.partition("=") for x in args.read]
        if bad := [x for x, (role, sep, ref) in zip(args.read, pairs) if not (role and sep and ref)]:
            raise SystemExit(f"bitt: --read takes role=data, not {bad[0]!r}")
        a["read"] = {role: node(k, ref, task) for role, _, ref in pairs}
    for key, val in (("full", "yes" if args.full else None), ("as", args.as_), ("artifact_kind", args.artifact_kind), ("line", args.line),
                     ("env", args.env),
                     ("skip_smoke", "yes" if args.skip_smoke else None)):
        if val is not None:
            a[key] = val
    for key, val, kinds in (("parent", args.parent, ["dataset", "evalset"]), ("fills", args.fills, ["want"]),
                            ("endpoint", args.endpoint, ["module"])):
        if val:
            a[key] = node(k, val, task, kinds)
    if args.evals:
        a["evals"] = [node(k, x, task, ["recipe"]) for x in args.evals]
    if args.min_n:
        a["invalid_if"] = {"min_n": args.min_n}
    out = call("run.go", a)
    run = out["run"]
    n = k.node(run)
    e = k.rec.get_row("bitt.run_end", (run,)) or {}
    label = recipes.label(k, r, task)
    if out.get("job") and status_of(k.rec, run) == "open":
        print(f"run {run[:12]} ({n['payload']['kind']}{', smoke' if n['payload'].get('smoke') else ''}) started in {n['payload'].get('env') or 'local'}: "
              f"job {out['job'][:12]}\nnext: bitt run sync (lands it when it is done)")
        return 0
    if n["payload"].get("person"):
        print(f"run {run[:12]}: {len(n['payload']['asks'])} rows for a person to answer (it stays open; nothing waits on it)\n"
              f"next: bitt run answer {run[:12]} --file answers.jsonl, then bitt run close {run[:12]}")
        return 0
    if n["payload"]["kind"] == "pipeline":
        print(f"run {run[:12]} of {label}: {len(n['links'].get('steps', []))} steps, {status_of(k.rec, run)}")
        if out.get("decision"):
            d = k.node(out["decision"])["payload"]
            print(f"  decision: {'won' if d['won'] else 'lost'} ({d['rule']}; row {json.dumps(d['row'])})")
        return 0
    for x in out.get("runs") or [run]:                          # one call climbs: the smoke rung, then the sample (or all)
        nx, ex = k.node(x), k.rec.get_row("bitt.run_end", (x,)) or {}
        head = "  smoke" if x != run else "run"                 # the run to use is the last line's: `run <id>`
        print(f"{head} {x[:12]} of {label}: {status_of(k.rec, x)}, rung {nx['payload'].get('rung') or nx['payload'].get('of')}/"
              f"{nx['payload'].get('of')}: made {ex.get('made', 0)}, reused {ex.get('reused', 0)}, failed {ex.get('failed', 0)}")
    if out.get("set"):
        print(f"  {k.node(out['set'])['kind']} {short(k, out['set'], task)}")
    if out.get("artifact"):
        a = k.node(out["artifact"])["payload"]
        print(f"  artifact {short(k, out['artifact'], task)} ({a['artifact_kind']}): {a['does']}; fill a role with it: --fill <role>=<it>")
    if k.node(r)["kind"] == "recipe" and recipes.header(k, r).get("returns") == "row" and (row := one_row(k, run)):
        print("  row: " + ", ".join(f"{c} = {v}" for c, v in row.items()))
    rung, of = n["payload"].get("rung"), n["payload"].get("of")
    if rung and of and rung < of:
        print(f"next: look at the sample (bitt data inspect {run[:12]}), then bitt run go {label} --on {' '.join(args.on)} for the rest")
    return 0


def cmd_workflow(k, args, call):
    cmd = args.cmd
    if cmd == "task":
        g = call("control.goal.open_root", {"problem": args.problem, "name": args.name})["goal"]
        print(f"task {args.name}\nnext: bitt cycle new {args.name} \"<question>\" (or a goal: bitt goal new {args.name} \"<problem>\")")
        return 0 if g else 1
    if cmd == "goal":
        up = node(k, args.under, kinds=["goal"])
        g = call("control.goal.open", {"in": up, "problem": args.problem})["goal"]
        print(f"goal {where.ref(k, g)} under {where.ref(k, up)}\nnext: bitt cycle new {where.ref(k, g)} \"<question>\"")
        return 0
    if cmd == "cycle":
        return cmd_cycle(k, args, call)
    if cmd == "grant":
        on = node(k, args.on, kinds=["goal", "cycle"])
        g = call("control.grant", {"in": on, "to": args.agent, "acts": args.acts, "reason": args.reason})["grant"]
        print(f"grant {g[:12]}: {args.agent} may {', '.join(args.acts)} under {where.ref(k, on)}")
        return 0
    if cmd == "revoke":
        g = node(k, args.grant, kinds=["grant"])
        call("control.revoke", {"in": k.node(g)["links"]["in"], "grant": g, "reason": args.reason})
        print(f"revoked {g[:12]}")
        return 0
    cyc = cycle_of(k, args, cmd)
    task = k.task_of(cyc)
    if cmd == "want":
        sk = call("control.want", {"in": cyc, "want_kind": args.kind, "contract": json.loads(args.contract),
                                   **({"name": args.name} if args.name else {})})["want"]
        print(f"want {sk[:12]}: a {args.kind}{' named ' + args.name if args.name else ''}\nnext: plan it (bitt plan --arms {sk[:12]} …)")
    elif cmd == "plan":
        a = {"in": cyc, "arms": [node(k, x, task) for x in args.arms], "win": args.win}
        if args.eval:
            a["pipeline"] = node(k, args.eval, task, ["module"])
        if args.judged_by:
            a["judged_by"] = args.judged_by
        p = call("control.plan", a)["plan"]
        print(f"plan {p[:12]}: {len(a['arms'])} arm(s), judged by {args.eval or args.judged_by or 'a person'}; cycle {k.cstate(cyc)}")
    elif cmd == "note":
        f = call("control.log.finding", {"in": cyc, "text": args.text, "evidence": [node(k, x, task) for x in args.evidence],
                                         **({"finding_kind": "conclusion"} if args.conclusion else {})})["finding"]
        print(f"finding {f[:12]}{' (a conclusion)' if args.conclusion else ''}; cycle {k.cstate(cyc)}")
    elif cmd == "validate":
        v = call("control.validate", {"in": cyc, "subject": node(k, args.ref, task), "verdict": args.verdict,
                                      **({"evidence": [node(k, x, task) for x in args.evidence]} if args.evidence else {})})["validation"]
        print(f"validation {v[:12]}: {args.verdict} {args.ref}")
    elif cmd == "tag":
        tgt = node(k, args.ref, task, ["module", "artifact", "dataset", "evalset"])
        tag, value = (("version", None) if args.version else ("alias", args.alias) if args.alias else ("trust", args.trust)
                      if args.trust else ("deprecated", args.deprecated))
        a = {"in": cyc, "target": tgt, "tag": tag, **({"value": value} if value else {})}
        if args.because:
            a["because"] = [node(k, x, task) for x in args.because]
        if args.agreement:
            a["agreement"] = node(k, args.agreement, task, ["run"])
        out = call("tag.make", a)
        print(f"{names.ref_of(k, tgt, task)}: {tag}{' ' + out['bump'] if tag == 'version' else ' ' + str(value)}")
    elif cmd == "ack":
        call("control.ack", {"in": cyc, "subject": node(k, args.ref, task), "reason": args.reason,
                             **({"rule": args.rule} if args.rule else {})})
        print(f"acked {args.ref}{' for ' + args.rule if args.rule else ''}")
    return 0


def cmd_cycle(k, args, call):
    if args.verb == "new":
        up = node(k, args.under, kinds=["goal"])
        c = call("control.cycle.open", {"in": up, "question": args.question, "level": args.level, "because": [up]})["cycle"]
        where.use(c)
        print(f"cycle {where.ref(k, c)} ({args.level}), now your current cycle\nnext: work here; bitt cycle use <another> to switch")
        return 0
    if args.verb == "use":
        c = node(k, args.cycle, kinds=["cycle"])
        if not where.is_open(k, c):
            raise SystemExit(f"bitt: {where.ref(k, c)} is {k.cstate(c)}: only an open cycle can be current")
        where.use(c)
        print(f"current cycle: {where.line(k, c)}")
        return 0
    if args.verb == "list":
        ts = [names.task_by_name(k, args.task)] if args.task else [g["id"] for g in k.rec.find("goal") if not g["links"].get("in")]
        cur = where.current(k)
        for t in ts:
            for c in where.cycles(k, t):
                print(("* " if c == cur else "  ") + where.line(k, c).removeprefix("→ "))
        return 0
    c = node(k, args.cycle, kinds=["cycle", "goal"]) if args.cycle else cycle_of(k, args, f"cycle {args.verb}")
    call("control.act", {"in": c, "outcome": args.verb, **({"reason": args.reason} if args.reason else {})})
    print(f"{where.ref(k, c)}: {args.verb} → {k.cstate(c)}")
    return 0


# ---------------------------------------------------------------- reads
def cmd_show(k, args):
    from .tools import recipe as recipes
    from .tools.run import one_row, status_of
    from .tools.tag import deprecated, trust_of, trusted_elsewhere
    cur = where.current(k)
    task = k.task_of(cur) if cur else None
    nid = node(k, args.ref, task)
    n = k.node(nid)
    p = n["payload"]
    tags = names.tags(k, nid)
    print(f"{short(k, nid, task)} ({n['kind']} {nid[:12]}), by {n['stamp']['actor']}")
    if n["kind"] == "module":
        h = p["header"]
        print(f"  a {h['kind']} module: {h['does']}\n  reads {h['reads'] or '-'} → writes {h['writes'] or '-'}; params "
              f"{json.dumps(h['params'])}; roles {h['roles'] or '-'}")
        if n["links"].get("wraps"):
            print(f"  wraps {names.ref_of(k, n['links']['wraps'])}, fixed {json.dumps(p['fixed'])}")
        if h["kind"] == "check" and task:
            print(f"  trust here: {trust_of(k, nid, task)}" + (f" (trusted in {', '.join(trusted_elsewhere(k, nid, task))})"
                                                               if trusted_elsewhere(k, nid, task) else ""))
    elif n["kind"] == "artifact":
        c = p.get("contract") or {}
        print(f"  a {p['artifact_kind']}: {p.get('does')}" + (f"\n  needs {c['needs']} → gives {list(c['gives'])}" if c.get("needs") else ""))
        if n["links"].get("run"):
            print(f"  made by run {n['links']['run'][:12]}")
    elif n["kind"] == "recipe":
        print(f"  {names.vlabel(k, n['links']['module'], task)}" + "".join(f", {r} ← {c}" for r, c in p["cols"].items())
              + (f", params {p['params']}" if p["params"] else "") + "".join(f", {r}: {names.vlabel(k, a, task)}"   # the version it pinned
                                                                               for r, a in recipes.artifacts(k, nid).items()))
    elif n["kind"] == "run":
        e = k.rec.get_row("bitt.run_end", (nid,)) or {}
        print(f"  a {p['kind']} run of {recipes.label(k, n['links']['recipe'], task)}: {status_of(k.rec, nid)}; rung {p.get('rung') or '-'}/"
              f"{p.get('of') or '-'}; made {e.get('made', '-')}, reused {e.get('reused', '-')}, failed {e.get('failed', '-')}")
        if recipes.header(k, n["links"]["recipe"]).get("returns") == "row" and (row := one_row(k, nid)):
            print("  row: " + ", ".join(f"{c} = {v}" for c, v in row.items()))
        for x in k.rec.table_rows("bitt.run_error", bitt_run_hash=nid)[:3]:
            print(f"  error: {x['error'][:160]}")
    elif n["kind"] == "decision":
        print(f"  {'won' if p.get('won') else 'lost'}: {p.get('rule') or p.get('text')}; read {json.dumps(p.get('read'))}")
    elif n["kind"] == "cycle":
        print(f"  {where.line(k, nid)}")
        plan = k.latest_plan(nid)
        for a in as_list_(plan["links"].get("arms") if plan else None):
            print(f"  arm {short(k, a, task)}: {k.arm_state(a, plan)}")
    elif n["kind"] in ("raw", "dataset", "evalset", "selection"):
        print(f"  {len(Walk(k).set_rows(p['set']))} rows of {p['table']}")
    for t in tags:
        print(f"  tag {t['payload']['tag']} {t['payload']['value']} (by {t['stamp']['actor']})")
    if d := deprecated(k, nid):
        print(f"  DEPRECATED: {d}")
    for kind in ("flag", "warning"):
        for m in k.kids(nid, role="subject", kind=kind):
            print(f"  {kind}: {m['payload']['detail'][:160]}")
    return 0


def as_list_(x):
    return x if isinstance(x, list) else [] if x is None else [x]


def cmd_log(k, args):
    task = names.task_by_name(k, args.task) if args.task else (k.task_of(where.current(k)) if where.current(k) else None)
    evs = [e for e in k.rec.find("event") if task is None or k.task_of(e["id"]) == task or
           (e["links"].get("during") and k.task_of(e["links"]["during"]) == task)]
    if args.all:
        return log_all(k, task, evs)
    for e in evs[-args.n:]:
        made = [c for c in k.kids(e["id"], role="event") if c["kind"] not in ("ruling", "name", "event", "job")]
        print(f"{e['seq']:>5} {e['stamp']['actor']:<14} {e['payload']['card']:<20} "
              + ", ".join(short(k, m["id"], task) for m in made[:3]))
    refusals = [r for r in k.rec.find("refusal") if task is None or k.task_of(r["id"]) == task][-3:]
    for r in refusals:
        print(f"  refused {r['payload']['card']}: {r['payload']['reason'][:140]}")
    return 0


def log_all(k, task, evs):
    """Every event, refusal and warning of the task (or of the store), in the order they were written, each with its time."""
    def mine(n):
        try:
            return task is None or k.task_of(n["id"]) == task
        except Exception:                   # a node with no task (a store-level act): only in the store-wide log
            return task is None
    rows = evs + [n for kind in ("refusal", "warning") for n in k.rec.find(kind) if mine(n)]
    for n in sorted(rows, key=lambda n: n["seq"]):
        ns = n["stamp"].get("at")              # nanoseconds since the epoch (record.put)
        at = datetime.datetime.fromtimestamp(ns / 1e9).strftime("%Y-%m-%d %H:%M:%S") if isinstance(ns, int) else "?"
        who = n["stamp"].get("actor", "")
        if n["kind"] == "event":
            made = [c for c in k.kids(n["id"], role="event") if c["kind"] not in ("check", "name", "event", "job")]
            what = f"{n['payload']['card']:<20} " + ", ".join(short(k, m["id"], task) for m in made[:3])
        elif n["kind"] == "refusal":
            what = f"refused {n['payload']['card']}: {n['payload']['reason'][:300]}"
        else:
            what = f"warning: {str(n['payload'].get('detail', ''))[:300]}"
        print(f"{n['seq']:>5} {at} {who:<14} {what}")
    loose = [r for r in k.rec.refusals if task is None]
    for r in loose:                         # refusals with no cycle to sit in: no order, no time of their own
        print(f"      (no cycle)          {r.get('actor', ''):<14} refused {r.get('card')}: {str(r.get('reason', ''))[:300]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
