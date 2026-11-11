"""The run tool (spec/cards/run.yaml): a recipe over data, in a cycle (foundation.md §C1). One act; the module kind decides how.

  a row module (derive, check, generate)   a ladder climbed by itself (smoke 1 → the sample → all; one call stops at the sample); one row per (the recipe's work, what it read, sample, part),
                                           reused when it exists; a connector (generate with a prompt) gets each row's rendered
                                           messages and its reply is parsed into the prompt's gives
  a table derive                           its rows, keyed by the source rows they name (`bitt_from`) or by the input set; a select
                                           ("selection") makes a selection (`as` dataset / evalset on a `line`)
  an aggregate (a table check, or a table  exactly one row of what it declares, keyed by the input set it read (d15.md §3.3)
  derive returning one row)
  a join                                   each unit's row looked up by key in the `read` inputs (docs/v2/inputs.md): computed by bitt
                                           per table, recorded per row, the units kept, in full
Every run counts per unit (d15.md §3.1): its input entries are the units it started from (a raw import, a set, a dataset, an evalset) or
the entries of the run it reads, and its output set follows them in order (entry i names the input entry it came from), so a row
module reads each bound column along its own unit's chain, never from another unit that happens to share a stored row.
Every module runs through one job path (`job`): a job folder (tools/envs.py, tools/bitt_run.py) in an env, never inside bitt.
Made rows live in one table per output contract (`writer`), shared by every recipe and task that writes it.
"""
import ast
import json
import os
import subprocess
import time
from pathlib import Path

from .. import blobs, names, sets, tables
from ..errors import Failed, Refused
from ..hashing import canonical, h, in_hash, out_hash
from ..kernel import Package
from ..util import as_list
from ..walk import Walk
from . import envs, prompts
from . import recipe as recipes
from .module import code_of, inner

from ..cards import CARDS  # noqa: E402  (a release: inside the package)
SAMPLE_ROWS = 10                                    # the sample rung's default (a recipe declares its own: sample_rows)
MAX_ERRORS = 3
TIMEOUT = 600
TYPE = {"text": "text", "int": "bigint", "number": "numeric", "bool": "boolean", "json": "jsonb"}
REACHES_OUT = {"socket", "urllib", "http", "requests", "httpx", "aiohttp", "ftplib", "smtplib", "subprocess", "paramiko"}
MISSING = object()
WALK = "_walk"                                               # the walker kept in a call's memo


# ---------------------------------------------------------------- inputs, units and lineage (d15.md §3.1, §3.2)
def resolved(eng, ref):
    """A pipeline run reads as the step it returned."""
    while eng.node(ref)["kind"] == "run" and eng.node(ref)["payload"].get("kind") == "pipeline" and eng.node(ref)["payload"].get("result"):
        ref = eng.node(ref)["payload"]["result"]
    return ref


def input_of(eng, ref):
    """(table, set hash) of one input: a raw import, a set / dataset / evalset, or a run (the rows it made or reused, per unit)."""
    ref = resolved(eng, ref)
    n = eng.node(ref)
    if n["kind"] in ("raw", "selection", "dataset", "evalset"):
        return n["payload"]["table"], n["payload"]["set"]
    e = eng.rec.get_row("bitt.run_end", (ref,))
    if not e and n["payload"].get("person"):                    # an open person run: the answers so far (partial, C9)
        t, got = n["payload"]["out_table"], person_entries(eng, ref)
        if not got:
            raise Refused(f"run {ref[:12]} is a person run nobody has answered yet")
        return t, sets.write_set(eng.rec, t, got, "run_out", ref)
    if not e or not e["out_set"]:
        raise Refused(f"run {ref[:12]} made no rows (a select makes a set: run on that set)")
    return eng.rec.get_row("bitt.set", (e["out_set"],))["tbl"], e["out_set"]


def walker(eng, memo):
    """The one walker of a call (docs/v2/walk.md), kept in its memo; an open person run's answers so far come through `input_of`."""
    if WALK not in memo:
        def open_run(r):
            return input_of(eng, r) if eng.node(r)["payload"].get("person") else None
        memo[WALK] = Walk(eng, open_run=open_run)
    return memo[WALK]


def entries_of(eng, ref, memo):
    """(table, set hash, [(row, split, src)]) of one input: src = the entry of the run's own input it came from (None: a unit).
    What has no rows is refused (`input_of`)."""
    t, sh, es = walker(eng, memo).entries(ref)
    if sh is None:
        input_of(eng, ref)                                       # refuses with the reason
    return t, sh, es


def chain(eng, ref, i, memo):
    """[(table, row hash)] of entry i of an input, then entry src of the run it read, … down to its unit row: nearest first."""
    entries_of(eng, ref, memo)
    return walker(eng, memo).chain(ref, i)


def units_of(eng, ref, memo):
    """The unit set an input's entries belong to (walk.units_of)."""
    entries_of(eng, ref, memo)
    return walker(eng, memo).units_of(ref)


def along(eng, ref, i, memo):
    """[(table, row)] a row module reads for entry i: the entry's row, its own unit's chain, then what the unit was made from (row links
    only: a whole-set link is not a row's own history)."""
    rec, w = eng.rec, walker(eng, memo)
    ch = chain(eng, ref, i, memo)
    rows = [(t, rec.get_row(t, (r,))) for t, r in ch]
    seen = set(ch)
    above = [(t, rec.get_row(t, (r,))) for t, r in w.rows_up(*ch[-1], through_sets=False)[1:] if (t, r) not in seen]
    return rows + [(t, up) for t, up in above if up]


def line_of_table(t):
    return tables.split_fq(t)[1]


def read_value(rows, col):
    """(value, problem, (table, row hash) it was read from) of column `col` over `along`'s rows: the entry's own column, else the nearest
    row on its chain that has it (`line.col`: that line's). problem says why it cannot be read."""
    (t0, row), ups = rows[0], rows[1:]
    line, _, c = col.rpartition(".")
    if (not line or line == line_of_table(t0)) and c in row and not c.startswith("bitt_"):
        return row[c], None, (t0, row["bitt_row_hash"])
    hits = [(tt, r) for tt, r in ups if c in r and (not line or line_of_table(tt) == line)]
    if not hits:
        have = sorted({line_of_table(tt) for tt, _ in ups})
        cols = sorted({k for k in row if not k.startswith("bitt_")})
        return MISSING, (f"no column {col!r} in {t0} (its columns: {cols}) or above it (lines above: {have or 'none'})"), None
    if not line and len({line_of_table(tt) for tt, _ in hits}) > 1:
        two = sorted({line_of_table(tt) for tt, _ in hits})
        return MISSING, f"{' and '.join(two)} both have {c!r} above {t0}: bind {' or '.join(f'{x}.{c}' for x in two)}", None
    return hits[0][1][c], None, (hits[0][0], hits[0][1]["bitt_row_hash"])


def values_at(eng, ref, i, cols, memo):
    """({role: value}, [(table, row hash) read]) of entry i: each role read from the column it is bound to (input_fits refused what
    cannot be read)."""
    rows, vals, read = along(eng, ref, i, memo), {}, []
    for role, col in cols.items():
        v, _, at = read_value(rows, col)
        vals[role] = None if v is MISSING else v
        read += [at] if at else []
    return vals, read


def link_sources(rec, out_t, ih, in_t, m, read):
    """A made row's lineage: its input row and every row a bound column was read from (d15.md §3.2)."""
    for t, r in dict.fromkeys([(in_t, m), *read]):
        sets.link(rec, out_t, ih, t, r)


def split_extra(o, writes):
    """(the declared columns, the undeclared ones or None, the declared ones missing) of one output: what a module returns beyond its
    contract is kept in bitt_extra with a warning, never refused (A11); a declared column it lacks fails the row."""
    o = dict(o)
    more = {**(o.pop("bitt_extra", None) or {}), **{k: v for k, v in o.items() if k not in writes}}
    return {k: o[k] for k in writes if k in o}, more or None, [c for c in writes if c not in o]


def kept_warning(eng, ctx, recipe, extras):
    if extras:
        warn(eng, ctx, f"run of {recipes.label(eng, recipe)}: kept columns the module does not declare: {sorted(extras)} (in bitt_extra). "
                       "next: declare them in the module's writes (a prompt: its gives), or stop returning them")


def unit_ends(units):
    """ends[k-1] = how many entries the first k units hold (entries are unit-major)."""
    starts, seen = [], set()
    for i, u in enumerate(units):
        if u not in seen:
            seen.add(u)
            starts.append(i)
    return starts[1:] + [len(units)]


# ---------------------------------------------------------------- one table per output contract
def connector_prompt(eng, recipe):
    """The prompt a connector recipe renders (its own, or the one its wrap fixed), or None: a connector is a generate that reads no
    column."""
    h_ = recipes.header(eng, recipe)
    return recipes.artifacts(eng, recipe).get("prompt") if h_["kind"] == "generate" and not h_["reads"] else None


def writes_of(eng, recipe):
    """(the writer node, its columns {name: type}): a connector's prompt and its gives, else the module and its writes."""
    if p := connector_prompt(eng, recipe):
        return p, eng.node(p)["payload"]["contract"]["gives"]
    return inner(eng, eng.node(recipe)["links"]["module"]), recipes.header(eng, recipe)["writes"]


def writer(eng, recipe, node):
    """The table of the recipe's output contract, made on its first run: `made.<line>` (`<line>_2` for the line's next contract)."""
    w, cols = writes_of(eng, recipe)
    root = names.line_of(eng, w)
    return contract_table(eng, h("contract", canonical({"line": root, "writes": cols})), names.born(eng, root) or "out", cols, w, node)


def contract_table(eng, ch, base, cols, w, node):
    rec = eng.rec
    row = rec.get_row("bitt.writer", (ch,))
    if row:
        return row["tbl"]
    n, name = 1, base
    while rec.spec(f"made.{name}") is not None:
        n += 1
        name = f"{base}_{n}"
    t = rec.make_table("output", "made", name, {}, [{"name": c, "type": TYPE[ty], "kind": "output"} for c, ty in cols.items()], node)
    sets.src_table(rec, t, {"src": "any", "set": "bitt.set"}, node)
    rec.insert("bitt.writer", {"contract_hash": ch, "tbl": t, "line": base, "node": w})
    return t


def report_table(eng, recipe, node):
    """A train's reported numbers (d15.md §3.5): `made.<module>_report`, columns step + what its BITT["reports"] declares."""
    m = inner(eng, eng.node(recipe)["links"]["module"])
    cols = {"step": "int", **(recipes.header(eng, recipe).get("reports") or {})}
    root = names.line_of(eng, m)
    return contract_table(eng, h("contract", canonical({"line": root, "reports": cols})), f"{names.born(eng, root) or 'train'}_report",
                          cols, m, node)


# ---------------------------------------------------------------- the one job path
def untraced_why(code):
    """What in a module's code reaches outside its job folder (None: nothing). A scan, not a proof."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None
    for n in ast.walk(tree):
        mods = [a.name for a in n.names] if isinstance(n, ast.Import) else [n.module or ""] if isinstance(n, ast.ImportFrom) else []
        if hit := [x for x in mods if x.split(".")[0] in REACHES_OUT]:
            return f"the module imports {hit[0]} (an input bitt cannot see)"
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("open", "__import__", "exec", "eval"):
            return f"the module calls {n.func.id}() (an input bitt cannot see)"
    return None


def run_dir(env, d, timeout=TIMEOUT, extra_env=None):
    """Run a written job folder in its env and wait for it: `done`, or `failed <code>`. `extra_env` (a local job only) is set in the
    job's process and nowhere else (a key: never in a file)."""
    if isinstance(env, envs.SSHEnv):
        env.launch(d.name)
        t0 = time.monotonic()
        while (st := env.status(d.name)) in ("staged", "running") and time.monotonic() - t0 < timeout:
            time.sleep(0.2)
        env.fetch(d.name)
        return st if st not in ("staged", "running") else "failed timeout"
    try:
        subprocess.run(["bash", "run.sh"], cwd=d, timeout=timeout, stdin=subprocess.DEVNULL, capture_output=True,
                       env={**os.environ, **extra_env} if extra_env else None)
    except subprocess.TimeoutExpired:
        return "failed timeout"
    st = d / "status"
    return st.read_text().strip() if st.exists() else "failed (no status)"


def log_tail(d, n=600):
    p = d / "log.txt"
    return p.read_text()[-n:].strip() if p.exists() else ""


def write_artifacts(eng, arts, d, env=None):
    """Each artifact a recipe fills, in input/<role>/: any content but a model as input/<role>/content. A model is never copied: it
    must sit in the job's env, and the shim links input/<role> to its folder there. Returns {role: folder} (job.json artifact_dirs)."""
    dirs = {}
    for role, a in arts.items():
        p = eng.node(a)["payload"]
        if p["artifact_kind"] == "prompt":
            continue                                             # bitt renders a prompt; the module never sees the file
        if p.get("at"):
            dirs[role] = model_dir_in(eng, a, env)
            continue
        dest = d / "input" / role
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "content").write_bytes(blobs.get(p["content_blob"]))
    return dirs


def model_dir_in(eng, a, env):
    """The folder of model a in env, or a refusal that says where it is (run there, or copy it here) or that it was removed."""
    from .artifact import places
    here = [pl for pl in places(eng, a) if pl["env"] == env.name]
    if here:
        if not env.has(here[0]["path"]):
            raise Refused(f"run.go: model {names.label(eng, a) or a[:12]} is recorded at {env.name}:{here[0]['path']}, but that folder is "
                          "gone (deleted outside bitt). next: bitt artifact rm it --env " + env.name + " to record that")
        return here[0]["path"]
    other = places(eng, a)
    if not other:
        raise Refused(f"run.go: model {names.label(eng, a) or a[:12]} was removed (its record stays; its files cannot be restored)")
    raise Refused(f"run.go: model {names.label(eng, a) or a[:12]} is not on env {env.name!r}; it is on {sorted({x['env'] for x in other})}. "
                  f"next: run with --env {other[0]['env']}, or bring it here: bitt artifact copy <it> --to {env.name}")


def key_env(params):
    """A key file named by the params is read now, into the job's process environment only."""
    f = params.get("key_file")
    if not f:
        return None
    p = Path(f).expanduser()
    if not p.exists():
        raise Refused(f"the key file {f} is not there. next: put the key there, or fix key_file in the wrap")
    return {"BITT_KEY": p.read_text().strip()}


def job(eng, ctx, spec, code, rows, params, arts, background=False, files=None):
    """One job: a node (exec.job.submit), a folder in the run's env, run there; finished done / failed. Returns (job, folder).
    `files` {name: bytes} land in input/ (a loader's file: its bytes are hashed in the record, never stored there or in git)."""
    env = envs.get(ctx.get("env") or "local")
    j = eng.call("exec.job.submit", {"caller_event": ctx["_event"], "needs": {"env": env.name, "kind": spec["kind"]}},
                 actor=ctx["_stamp"]["actor"])["job"]
    d = env.local_dir(j)
    dirs = write_artifacts(eng, arts, d, env)
    envs.write_module_job(d, {**spec, "params": {k: v for k, v in params.items()}, **({"artifact_dirs": dirs} if dirs else {})}, code,
                          rows, env.python(), env.c.get("gpus"))
    for name, data in (files or {}).items():
        (d / "input" / name).write_bytes(data)
    if background:
        env.launch(j)
        return j, d
    status = run_dir(env, d, extra_env=key_env(params))
    eng.call("exec.job.finish", {"job": j, "outputs": [], "status": "done" if status == "done" else "failed",
                                 "reason": None if status == "done" else f"{status}: {log_tail(d)}"}, actor="system")
    if status != "done":
        raise Refused(f"run.go: the module's job {status} (log: {log_tail(d, 300) or 'empty'})")
    return j, d


def job_spec(h_, connector=False):
    return {"kind": h_["kind"], "scope": h_["scope"], "fn": h_["fn"], "reads": h_["reads"], "writes": h_["writes"],
            "returns": h_.get("returns"), "connector": connector, **({"inputs": h_["inputs"]} if h_.get("inputs") else {})}


def read_rows(d, n):
    """Per input row: its output dict (one part), a list of parts, or the Exception it raised."""
    got = {}
    for line in (x for x in (d / "output" / "rows.jsonl").read_text().splitlines() if x.strip()):
        r = json.loads(line)
        i = r.pop("bitt_in")
        if "bitt_error" in r:
            got[i] = RuntimeError(r["bitt_error"])
            continue
        got.setdefault(i, []).append((r.pop("bitt_part"), r))
    out = []
    for i in range(n):
        g = got.get(i)
        if g is None:
            out.append(RuntimeError("the module returned nothing for this row"))
        elif isinstance(g, Exception):
            out.append(g)
        else:
            parts = [o for _, o in sorted(g, key=lambda x: x[0])]
            out.append(parts[0] if len(parts) == 1 else parts)
    return out


# ---------------------------------------------------------------- the run's records
def samples_of(eng, recipe):
    """How many times each row is asked: the recipe's (the same recipe always asks the same number of times)."""
    return int(eng.node(recipe)["payload"].get("samples") or 1)


def start(eng, ctx, refs, h_, **payload):
    run_n = eng.make("run", ctx, refs, **payload)                 # ctx carries `kind` (the card's kind_of)
    eng.rec.insert("bitt.run", {"bitt_run_hash": run_n, "bitt_recipe_hash": eng.node(ctx["recipe"])["spec_h"], "kind": h_["kind"],
                                "task": eng.task_of(ctx["in"]), "input": payload.get("input_set"), "units": payload.get("units"),
                                "rung": payload.get("rung"),
                                "n_samples": samples_of(eng, ctx["recipe"]), "env": ctx.get("env") or "local",
                                "traced": "untraced" if payload.get("untraced") else "traced", "untraced_why": payload.get("untraced")})
    return run_n


def end(rec, run_n, counts, status, out_set=None):
    rec.insert("bitt.run_end", {"bitt_run_hash": run_n, "status": status, "out_set": out_set,
                                **{k: counts.get(k, 0) for k in ("rows_total", "made", "reused", "failed", "outputs_made", "calls")}})


def status_of(rec, run_n):
    e = rec.get_row("bitt.run_end", (run_n,))
    return e["status"] if e else "open"


def warn(eng, ctx, detail):
    eng.make("warning", ctx, {"in": ctx["in"]}, detail=detail)


# ---------------------------------------------------------------- the act
def i_go(eng, e, ctx, refs):
    recipe = ctx["recipe"]
    h_ = recipes.header(eng, recipe)
    if h_["kind"] == "load":
        raise Refused("run.go: a loader runs through bitt data load --with <it>")
    named = h_.get("inputs") or []                               # a table derive's named inputs (docs/v2/inputs.md J3)
    if ctx.get("read") and h_["kind"] not in ("join", "pipeline", "union") and not named:
        raise Refused(f"run.go: a {h_['kind']} reads one input (--on); another input is looked up by a join step: join it first "
                      "(bitt recipe join --cols <column>=<role>.<column> --params key=…, then run go on that run), or merged by a "
                      "table module that names it (def merge(rows: list, chat: list)) or the shipped union")
    if named and sorted(ctx.get("read") or {}) != sorted(named):
        lack = sorted(set(named) - set(ctx.get("read") or {}))
        raise Refused(f"run.go: {recipes.label(eng, recipe)} reads {', '.join(named)} besides its units: "
                      + (f"next: --read {lack[0]}=<data>" if lack else f"it reads no {sorted(set(ctx['read']) - set(named))[0]}"))
    if h_["kind"] == "pipeline":                                 # its steps get `read` through b.read
        from .pipeline import run_pipeline
        return run_pipeline(eng, ctx, refs, h_)
    ons = as_list(ctx.get("on"))
    if h_["kind"] in ("join", "union"):
        if len(ons) != 1:
            raise Refused(f"run.go: a {h_['kind']} walks one input (--on <the units>); the others are --read <role>=<data>")
        if h_["kind"] == "union" and not ctx.get("read"):
            raise Refused("run.go: a union merges the units with at least one other input. next: --read <role>=<data>")
        return (join if h_["kind"] == "join" else union)(eng, ctx, refs, h_, ons[0])
    if h_["kind"] == "train":
        if len(ons) != 1:
            raise Refused("run.go: a train reads one dataset (--on <dataset>)")
        return train(eng, ctx, refs, h_, ons[0])
    if len(ons) != 1:
        raise Refused(f"run.go: a {h_['kind']} recipe runs on one input (--on <data>); a second input is looked up by a join step "
                      "first: bitt recipe join (docs/v2/inputs.md)")
    if h_["scope"] == "table":
        if h_.get("returns") == "row":
            return aggregate(eng, ctx, refs, h_, ons[0])
        return select(eng, ctx, refs, h_, ons[0]) if h_["writes"] == "selection" else table(eng, ctx, refs, h_, ons[0])
    return rows(eng, ctx, refs, h_, ons[0])


def rungs_of(n, sample_rows, full):
    """The ladder (owner 11-04): smoke (1 unit: is it wired right? the kernel judges) → the sample (`sample_rows`, default 10: are the
    outputs as predicted? a person or the plan's eval judges) → all N. `full`: smoke, then all."""
    return sorted({k for k in (1, *(() if full else (sample_rows,))) if k < n} | {n})


def next_rung(rec, work, out_t, ih, ends, full, samples, sample_rows=SAMPLE_ROWS):
    """The smallest rung whose units still have an entry with no output."""
    n = len(ends)
    for k in rungs_of(n, sample_rows, full):
        if any(rec.get_row(out_t, (out_hash(work, ih[i], s, 0),)) is None for i in range(ends[k - 1]) for s in range(samples)):
            return k
    return n


def sample_rows_of(eng, recipe):
    return int(eng.node(recipe)["payload"].get("sample_rows") or SAMPLE_ROWS)


def rows(eng, ctx, refs, h_, src):
    """One call climbs by itself: the smoke rung, and when it is clean (no failed row) the next rung, stopping at the sample (its
    outputs are looked at before all) or, with `full`, going on to all. A failed rung stops the climb. A check runs on all at once."""
    out, runs = rung(eng, ctx, refs, h_, src), []
    runs.append(out["run"])
    while out.get("climb") and len(runs) < 2:                  # the smoke rung, then one more: never a loop
        out = rung(eng, ctx, refs, h_, src)
        runs.append(out["run"])
    out.pop("climb", None)
    return {**out, "runs": runs} if len(runs) > 1 else out


def rung(eng, ctx, refs, h_, src):
    """One rung of the ladder: a run of the next rung's units (`climb`: it was the clean smoke rung, and a rung is left above it)."""
    rec, recipe, memo = eng.rec, ctx["recipe"], {}
    work = eng.node(recipe)["spec_h"]
    in_t, in_set, es = entries_of(eng, src, memo)
    cols = eng.node(recipe)["payload"]["cols"]
    arts = recipes.artifacts(eng, recipe)
    params = recipes.params(eng, recipe)
    connector = connector_prompt(eng, recipe) is not None
    prompt = eng.node(connector_prompt(eng, recipe)) if connector else None
    _, writes = writes_of(eng, recipe)
    out_t = writer(eng, recipe, recipe)
    samples = samples_of(eng, recipe)
    got = [values_at(eng, src, i, cols, memo) for i in range(len(es))]
    vals = [v for v, _ in got]
    ih = [in_hash({"src": v}) for v in vals]
    ends = unit_ends([chain(eng, src, i, memo)[-1] for i in range(len(es))])
    check_all = h_["kind"] == "check"                           # a check is cheap and judges: all at once
    check_all = check_all or (h_["calls"] == "person" and ctx.get("full") == "yes")   # a person's answers: nothing wired to smoke
    k = len(ends) if check_all else next_rung(rec, work, out_t, ih, ends, ctx.get("full") == "yes", samples, sample_rows_of(eng, recipe))
    sr = sample_rows_of(eng, recipe)
    had_sample = sr < len(ends) and all(rec.get_row(out_t, (out_hash(work, ih[i], s, 0),)) is not None
                                        for i in range(ends[sr - 1]) for s in range(samples))     # looked at before this run
    p = ends[k - 1]
    rung = in_set if p >= len(es) else sets.prefix_set(rec, in_set, p, recipe)
    code = code_of(eng, eng.node(recipe)["links"]["module"])
    base = dict(input_set=in_set, units=units_of(eng, src, memo), rung=k, of=len(ends), upto=p, rung_set=rung, out_table=out_t)
    if h_["calls"] == "person":                                  # a person answers: the run stays open, nothing is called (C9)
        asks = list(dict.fromkeys(es[i][0] for i in range(p) if rec.get_row(out_t, (out_hash(work, ih[i], 0, 0),)) is None))
        run_n = start(eng, ctx, refs, h_, **base, person=True, asks=asks)
        for i in range(p):
            link_sources(rec, out_t, ih[i], in_t, es[i][0], got[i][1])
        return {"run": run_n}
    run_n = start(eng, ctx, refs, h_, **base, untraced=None if connector else untraced_why(code))
    counts = {"rows_total": p, "made": 0, "reused": 0, "failed": 0, "outputs_made": 0, "calls": 0}
    errors, todo, queued, dups, extras = [], [], set(), {}, set()
    for i in range(p):
        m = es[i][0]
        link_sources(rec, out_t, ih[i], in_t, m, got[i][1])
        for s in range(samples):
            key = out_hash(work, ih[i], s, 0)
            if key in queued:
                dups[key] = dups.get(key, 0) + 1
            if rec.get_row(out_t, (key,)) is not None or key in queued:
                counts["reused"] += 1
                continue
            past = [x for x in rec.table_rows("bitt.run_error", bitt_in_hash=ih[i])
                    if rec.get_row("bitt.run", (x["bitt_run_hash"],))["bitt_recipe_hash"] == work]
            if len(past) >= MAX_ERRORS:
                counts["failed"] += 1
                errors.append(f"row {m[:12]}: failed {len(past)} times, skipped")
                continue
            queued.add(key)
            todo.append((i, key, s))
    results = []
    if todo:
        counts["calls"] = len(todo)
        if connector:
            msgs = prompts.messages_of(blobs.get(prompt["payload"]["content_blob"]))
            job_rows = [{"messages": prompts.render(msgs, vals[i])} for i, _, _ in todo]
        else:
            job_rows = [vals[i] for i, _, _ in todo]
        _, d = job(eng, ctx, job_spec(h_, connector), code, job_rows, params, arts)
        results = read_rows(d, len(todo))
        if connector:
            results = [r if isinstance(r, Exception) else _parse(r, prompt) for r in results]
    for (i, key, s), res in zip(todo, results):
        m = es[i][0]
        if not isinstance(res, Exception):
            split = [split_extra(o, writes) for o in (res if isinstance(res, list) else [res])]
            lack = sorted({c for _, _, miss in split for c in miss})
            if lack:
                res = RuntimeError(f"the output lacks {lack}, which the module declares (module.contract)")
        if isinstance(res, Exception):
            seq = len(rec.table_rows("bitt.run_error", bitt_run_hash=run_n))
            rec.insert("bitt.run_error", {"bitt_run_hash": run_n, "bitt_in_hash": ih[i], "src": {"src": m},
                                          "error": f"{type(res).__name__}: {res}"[:2000], "seq": seq})
            counts["failed"] += 1 + dups.get(key, 0)
            counts["reused"] -= dups.get(key, 0)
            errors.append(f"row {m[:12]}: {res}")
            continue
        for q, (o, more, _) in enumerate(split):
            extras |= set(more or {})
            rec.insert(out_t, {"bitt_row_hash": out_hash(work, ih[i], s, q), "bitt_in_hash": ih[i], "bitt_recipe_hash": work,
                               "bitt_run_hash": run_n, "bitt_sample": s, "bitt_part": q, "bitt_parts": len(split), **o, "bitt_extra": more})
            counts["outputs_made"] += 1
        counts["made"] += 1
    out = []                                                     # per unit, per sample, per part: a failed row has no entry
    for i in range(p):
        for s in range(samples):
            first = rec.get_row(out_t, (out_hash(work, ih[i], s, 0),))
            out += [(out_hash(work, ih[i], s, q), es[i][1], i) for q in range(first["bitt_parts"])] if first else []
    out_set = sets.write_set(rec, out_t, out, "run_out", run_n) if out else None
    end(rec, run_n, counts, "failed" if counts["failed"] else "done", out_set)
    label = recipes.label(eng, recipe)
    kept_warning(eng, ctx, recipe, extras)
    if errors:
        warn(eng, ctx, f"run of {label}: rung {k} failed: " + "; ".join(errors[:3]))
    n = len(ends)
    if ctx.get("full") == "yes" and k == n and sr < n and not check_all and not had_sample:
        warn(eng, ctx, f"run of {label}: all {n} without its sample of {sr} looked at first (full)")
    return {"run": run_n, "climb": k == 1 and k < n and not errors and not check_all}



def _parse(res, prompt):
    try:
        return prompts.parse_reply(res["raw_text"], prompt["payload"]["contract"], prompt["payload"]["contract"].get("plain"))
    except ValueError as x:
        return x


def table_rows(eng, src, cols):
    """What a table-scope module sees: per entry of the input (per unit, sample, part), its bound values read along its own unit's chain
    (or, with no cols, the row's own columns) + bitt_split, bitt_row_hash, bitt_unit, bitt_sample; and the row it is."""
    rec, memo = eng.rec, {}
    in_t, in_set, es = entries_of(eng, src, memo)
    out = []
    for i, (m, sp, _) in enumerate(es):
        row = rec.get_row(in_t, (m,))
        base = values_at(eng, src, i, cols, memo)[0] if cols else {k: v for k, v in row.items() if not k.startswith("bitt_")}
        out.append(({**base, "bitt_split": sp, "bitt_row_hash": m, "bitt_unit": chain(eng, src, i, memo)[-1][1],
                     "bitt_sample": row.get("bitt_sample") or 0}, m))
    return in_t, in_set, out


def aggregate(eng, ctx, refs, h_, src):
    """A module across rows (d15.md §3.3): exactly one row of what it declares, keyed by the input set it read (linked as `set`); the same
    set again reuses that row."""
    rec, recipe = eng.rec, ctx["recipe"]
    work = eng.node(recipe)["spec_h"]
    in_t, in_set, rs = table_rows(eng, src, eng.node(recipe)["payload"]["cols"])
    out_t = writer(eng, recipe, recipe)
    ih = h("in", canonical({"set": in_set}))
    key = out_hash(work, ih, 0, 0)
    run_n = start(eng, ctx, refs, h_, input_set=in_set, units=units_of(eng, src, {}), of=len(rs), out_table=out_t)
    made = 0
    if rec.get_row(out_t, (key,)) is None:
        _, d = job(eng, ctx, job_spec(h_), code_of(eng, eng.node(recipe)["links"]["module"]), [r for r, _ in rs],
                   recipes.params(eng, recipe), recipes.artifacts(eng, recipe))
        got = [json.loads(x) for x in (d / "output" / "rows.jsonl").read_text().splitlines() if x.strip()]
        o, more, lack = split_extra(got[0], h_["writes"]) if len(got) == 1 else (None, None, None)
        if len(got) != 1 or lack:
            raise Refused(f"run.go: an aggregate writes one row of {sorted(h_['writes'])}, not {got[:2]} (module.contract)")
        sets.link(rec, out_t, ih, "set", in_set)
        rec.insert(out_t, {"bitt_row_hash": key, "bitt_in_hash": ih, "bitt_recipe_hash": work, "bitt_run_hash": run_n, "bitt_sample": 0,
                           "bitt_part": 0, "bitt_parts": 1, **o, "bitt_extra": more})
        kept_warning(eng, ctx, recipe, more)
        made = 1
    out_set = sets.write_set(rec, out_t, [(key, None)], "run_out", run_n)
    end(rec, run_n, {"rows_total": len(rs), "made": made, "reused": 1 - made, "outputs_made": made, "calls": made}, "done", out_set)
    return {"run": run_n}


def one_row(eng, run_n):
    """The data columns of the one row a run made or reused (an aggregate's), or None when it has none or several."""
    run_n = resolved(eng, run_n)
    e = eng.rec.get_row("bitt.run_end", (run_n,))
    if not e or not e["out_set"]:
        return None
    ms = Walk(eng).set_rows(e["out_set"])
    if len(ms) != 1:
        return None
    row = eng.rec.get_row(ms[0][0], (ms[0][1],))
    return {k: (float(v) if isinstance(v, str) and k in _numeric(eng, e["out_set"]) else v) for k, v in row.items() if not k.startswith("bitt_")}


def _numeric(eng, sh):
    spec = eng.rec.spec(eng.rec.get_row("bitt.set", (sh,))["tbl"])
    return {c["name"] for c in spec["columns"] if c["type"] == "numeric"}


def table(eng, ctx, refs, h_, src):
    """A table derive: the module sees every row and returns rows; one that names `bitt_from` (indexes of the rows it came from) is
    keyed by those rows and linked to each; one that does not is keyed by (and linked to) the whole input set."""
    rec, recipe = eng.rec, ctx["recipe"]
    work = eng.node(recipe)["spec_h"]
    in_t, in_set, rs = table_rows(eng, src, eng.node(recipe)["payload"]["cols"])
    named = h_.get("inputs") or []                               # named inputs (docs/v2/inputs.md J3): each role's rows as they are
    others = {role: table_rows(eng, ctx["read"][role], {}) for role in named}
    out_t = writer(eng, recipe, recipe)
    run_n = start(eng, ctx, refs, h_, input_set=in_set, units=units_of(eng, src, {}), of=len(rs), out_table=out_t,
                  **({"reads": {role: others[role][1] for role in sorted(named)}} if named else {}))
    files = {f"{role}.jsonl": "".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r, _ in others[role][2]).encode()
             for role in named}
    _, d = job(eng, ctx, job_spec(h_), code_of(eng, eng.node(recipe)["links"]["module"]), [r for r, _ in rs],
               recipes.params(eng, recipe), recipes.artifacts(eng, recipe), files=files)
    got = [json.loads(x) for x in (d / "output" / "rows.jsonl").read_text().splitlines() if x.strip()]
    outs, parts, pending, extras = [], {}, [], set()
    whole = {"set": in_set, **({"reads": {role: others[role][1] for role in sorted(named)}} if named else {})}
    for o in got:
        frm = o.pop("bitt_from", None)
        o, more, lack = split_extra(o, h_["writes"])
        if lack:
            raise Refused(f"run.go: an output lacks {lack}; the module declares {sorted(h_['writes'])} (module.contract)")
        extras |= set(more or {})
        o["bitt_extra"] = more
        if frm is None:                                          # keyed by (and linked to) every input set it read
            ih = h("in", canonical(whole))
            links = [("set", in_set)] + [("set", others[role][1]) for role in sorted(named)]
        else:
            src_rows = from_rows(frm, in_t, rs, others)
            ih = h("in", canonical({"from": sorted(m if t == in_t else f"{t}:{m}" for t, m in src_rows)}))
            links = sorted(src_rows)
        p = parts.get(ih, 0)
        parts[ih] = p + 1
        for role, x in links:
            sets.link(rec, out_t, ih, role, x)
        pending.append((out_hash(work, ih, 0, p), ih, p, o))
    for key, ih, p, o in pending:
        rec.insert(out_t, {"bitt_row_hash": key, "bitt_in_hash": ih, "bitt_recipe_hash": work, "bitt_run_hash": run_n, "bitt_sample": 0,
                           "bitt_part": p, "bitt_parts": parts[ih], **o})
        outs.append(key)
    kept_warning(eng, ctx, recipe, extras)
    distinct = list(dict.fromkeys(outs))                         # its rows are new units (d15.md §3.1)
    out_set = sets.write_set(rec, out_t, [(o, None) for o in distinct], "run_out", run_n) if distinct else None
    end(rec, run_n, {"rows_total": len(rs), "made": len(outs), "outputs_made": len(outs), "calls": 1}, "done", out_set)
    return {"run": run_n}


def made_artifact(eng, ctx, refs, run_n, in_t, chosen, rs, task, name):
    """A select's picked rows as an artifact (docs/v2/walk.md W4): few-shot examples, a rubric's worked cases. Its content is the rows'
    own columns, one JSON line each (input/<role>/content in a job); it links the run that made it and the set it saw, so the
    contamination rule knows every row it was made from, test side included."""
    kind = ctx.get("artifact_kind")
    if not kind:
        raise Refused("run.go: an artifact made from data names its kind: --artifact-kind examples (or rubric, …)")
    if kind in ("model", "prompt"):
        raise Refused(f"run.go: a {kind} is not made by a select (a model: a train run; a prompt: bitt artifact add)")
    rows_ = {m: r for r, m in rs}
    content = "".join(json.dumps({k: v for k, v in rows_[m].items() if not k.startswith("bitt_")}, ensure_ascii=False, sort_keys=True,
                                 default=str) + "\n" for m, _ in chosen).encode()
    sh = sets.set_hash(chosen)
    root = names.join(eng, task, name, "artifact")
    a = eng.make("artifact", ctx, refs, artifact_kind=kind, content_blob=blobs.put(content), set=sh, table=in_t,
                 contract={"needs": [], "gives": {}}, does=f"{kind}: {len(chosen)} rows picked by {recipes.label(eng, ctx['recipe'])}",
                 _links={"run": run_n, **names.line_link(root)})
    names.settle(eng, ctx, task, name, a, root)
    sets.write_set(eng.rec, in_t, chosen, "selection", a)          # the rows it saw, owned by the artifact
    end(eng.rec, run_n, {"rows_total": len(rs), "made": len(chosen), "calls": 1}, "done")
    return {"run": run_n, "artifact": a}


def from_rows(frm, in_t, rs, others):
    """{(table, row hash)} a table derive's output row names in `bitt_from`: an index into the units, or [role, index] into a named
    input (docs/v2/inputs.md J3)."""
    out = set()
    for x in as_list(frm) if not (isinstance(frm, list) and len(frm) == 2 and isinstance(frm[0], str)) else [frm]:
        if isinstance(x, list) and len(x) == 2 and isinstance(x[0], str):
            role, i = x
            if role not in others:
                raise Refused(f"run.go: bitt_from names {role!r}, which is not one of the module's inputs ({', '.join(others) or 'none'})")
            t, _, ro = others[role]
            out.add((t, ro[i][1]))
        else:
            out.add((in_t, rs[x][1]))
    return out


def union(eng, ctx, refs, h_, src):
    """A union (docs/v2/inputs.md J3): every row of the units and of each `read` input, once per key; a row is keyed by its values, linked
    to every source row it stands for, and is a new unit. The contract is the units' columns, typed from their table; every input has
    them."""
    rec, recipe, memo = eng.rec, ctx["recipe"], {}
    work = eng.node(recipe)["spec_h"]
    reads = ctx["read"]
    inputs = [("on", src)] + [(role, reads[role]) for role in sorted(reads)]
    got = {role: entries_of(eng, ref, memo) for role, ref in inputs}
    t0 = got["on"][0]
    cols = {c["name"]: PG_TYPE.get(c["type"], "json") for c in rec.spec(t0)["columns"] if c["kind"] != "bitt"}
    for role, (t, _, _) in got.items():
        if lack := [c for c in cols if c not in {x["name"] for x in rec.spec(t)["columns"]}]:
            raise Refused(f"run.go: a union's inputs share the units' columns, but {role} ({t}) has no {', '.join(lack)}. next: derive "
                          f"{role} to the same columns first")
    key = recipes.params(eng, recipe).get("key") or list(cols)
    if bad := [c for c in key if c not in cols]:
        raise Refused(f"run.go: the key names {bad[0]}, which is not a column of the units ({', '.join(cols)})")
    root = names.line_of(eng, inner(eng, eng.node(recipe)["links"]["module"]))
    out_t = contract_table(eng, h("contract", canonical({"line": root, "writes": cols, "of": t0})), f"union_{line_of_table(t0)}", cols,
                           inner(eng, eng.node(recipe)["links"]["module"]), recipe)
    run_n = start(eng, ctx, refs, h_, input_set=got["on"][1], units=units_of(eng, src, memo), of=sum(len(g[2]) for g in got.values()),
                  out_table=out_t, reads={role: got[role][1] for role in sorted(reads)})
    groups = {}                                                  # key values → (the first row's values, [(table, row hash)])
    for role, (t, _, es) in got.items():
        for m, _, _ in es:
            row = rec.get_row(t, (m,))
            k_ = canonical([row.get(c) for c in key])
            groups.setdefault(k_, ({c: row.get(c) for c in cols}, []))[1].append((t, m))
    counts, out = {"rows_total": sum(len(g[2]) for g in got.values()), "made": 0, "reused": 0, "outputs_made": 0, "calls": 0}, []
    for vals, srcs in groups.values():
        ih = in_hash({"src": {"union": vals}})
        for t, m in dict.fromkeys(srcs):
            sets.link(rec, out_t, ih, t, m)
        key_ = out_hash(work, ih, 0, 0)
        if rec.get_row(out_t, (key_,)) is None:
            rec.insert(out_t, {"bitt_row_hash": key_, "bitt_in_hash": ih, "bitt_recipe_hash": work, "bitt_run_hash": run_n,
                               "bitt_sample": 0, "bitt_part": 0, "bitt_parts": 1, **vals, "bitt_extra": None})
            counts["made"] += 1
            counts["outputs_made"] += 1
        else:
            counts["reused"] += 1
        out.append((key_, None))
    out_set = sets.write_set(rec, out_t, list(dict.fromkeys(out)), "run_out", run_n)
    end(rec, run_n, counts, "done", out_set)                     # rows_total − the output's rows = the duplicates merged
    return {"run": run_n}


def select(eng, ctx, refs, h_, src):
    """A select: the module picks rows (and their splits) of its input; the pick is a set over the input's table (`as` set / dataset /
    evalset, a dataset and an evalset on a named `line` in the task)."""
    rec, recipe = eng.rec, ctx["recipe"]
    in_t, in_set, rs = table_rows(eng, src, eng.node(recipe)["payload"]["cols"])
    run_n = start(eng, ctx, refs, h_, input_set=in_set, units=units_of(eng, src, {}), of=len(rs))
    _, d = job(eng, ctx, job_spec(h_), code_of(eng, eng.node(recipe)["links"]["module"]), [r for r, _ in rs],
               recipes.params(eng, recipe), recipes.artifacts(eng, recipe))
    picked = [tuple(p) for p in json.loads((d / "output" / "select.json").read_text())]
    chosen = [(rs[i][1], sp) for i, sp in picked]
    if not chosen:
        raise Refused("run.go: the select picked no rows")
    as_ = ctx.get("as") or "selection"
    if (shared := len({m for m, _ in chosen})) < len(chosen):    # units that read the same values share one stored row
        base, w = src, Walk(eng)
        while eng.node(base)["kind"] == "run":
            base = w.links(base, "on")[0]
        ref = names.ref_of(eng, base) or base[:12]
        raise Refused(f"run.go: a {as_} lists each row once, but {len(chosen)} units share {shared} stored rows (units that read the same "
                      f"values share one). next: split {ref} first (run go {recipes.label(eng, recipe)} --on {ref} --as {as_} …), then join "
                      "on that dataset: a join keeps the splits")
    task = eng.task_of(ctx["in"])
    name = ctx.get("line") or (eng.node(ctx["fills"])["payload"].get("name") if ctx.get("fills") else None)
    if as_ != "selection" and not name:
        raise Refused(f"run.go: a {as_} is a named line: --line <name>")
    if as_ == "artifact":                                        # W4: an artifact made from data; it saw exactly the rows picked
        return made_artifact(eng, ctx, refs, run_n, in_t, chosen, rs, task, name)
    root = names.place(eng, task, name, as_, ctx.get("parent")) if as_ != "selection" else None
    test = sorted(m for m, sp in chosen if sp == "test")
    sh = sets.set_hash(chosen)
    out_n = eng.make(as_, ctx, refs, set=sh, table=in_t, test_hash=h("test", canonical(test)) if test else None,
                     _links={"run": run_n, **names.line_link(root)})
    if as_ != "selection":
        names.settle(eng, ctx, task, name, out_n, root)
    sets.write_set(rec, in_t, chosen, as_, out_n)
    end(rec, run_n, {"rows_total": len(rs), "made": len(chosen), "calls": 1}, "done")
    return {"run": run_n, "set": out_n}


# ---------------------------------------------------------------- the join (docs/v2/inputs.md)
PG_TYPE = {v: k for k, v in TYPE.items()}


def lookup_index(eng, role, ref, kcols, picked, memo, many=False, at=None):
    """{key values: (row hash, {column: value}, [(table, row hash) read])} of one lookup input, built once per run (docs/v2/inputs.md
    §1); a key that repeats is refused. A row with an empty key is never found. `many`: {key values: [those, …]} in the lookup's
    order, or ordered by column `at` (a row with no `at` is never read)."""
    _, _, es = entries_of(eng, ref, memo)
    by, seen = {}, set()
    for j, (m, _, _) in enumerate(es):
        if m in seen:
            continue
        seen.add(m)
        rows_ = along(eng, ref, j, memo)
        got = {c: read_value(rows_, c) for c in dict.fromkeys([*kcols, *picked, *([at] if at else [])])}
        key = tuple(got[c][0] for c in kcols)
        if not any(v is MISSING or v is None for v in key):
            by.setdefault(key, []).append((m, {c: (None if v is MISSING else v) for c, (v, _, _) in got.items()},
                                           [at for _, _, at in got.values() if at]))
    if many:
        return {k_: sorted([x for x in v if x[1].get(at) is not None], key=lambda x: x[1][at]) if at else v for k_, v in by.items()}
    if twice := [(k_, len(v)) for k_, v in by.items() if len(v) > 1]:
        (k_, n), more = twice[0], len(twice) - 1
        raise Refused(f"run.go: {role} has {n} rows for {', '.join(kcols)} {k_[0] if len(k_) == 1 else k_!r}"
                      + (f" (and {more} more keys repeat)" if more else "")
                      + f" (a lookup reads one row per key). next: dedup {role} first (a select), or read every row as a list: "
                      f"--params many='[\"{role}\"]'")
    return {k_: v[0] for k_, v in by.items()}


def join_columns(eng, recipe, ctx, memo):
    """(keys {role: {lookup column: unit column}}, picked {role: [lookup column]}, the output's columns {name: type}). Types are read
    from the table each picked column lives in (json when it cannot be told)."""
    from .recipe import join_keys
    n = eng.node(recipe)
    keys, cols = join_keys(recipes.params(eng, recipe)["key"]), n["payload"]["cols"]
    picked = {role: [] for role in keys}
    for src in cols.values():
        role, _, col = src.partition(".")
        picked[role].append(col)
    types = {}
    for out, src in cols.items():
        role, _, col = src.partition(".")
        ref = (ctx.get("read") or {})[role]
        _, _, es = entries_of(eng, ref, memo)
        at = read_value(along(eng, ref, 0, memo), col)[2] if es else None
        spec = {c["name"]: c["type"] for c in eng.rec.spec(at[0])["columns"]} if at else {}
        types[out] = "json" if role in (recipes.params(eng, recipe).get("many") or []) else PG_TYPE.get(spec.get(col), "json")
    return keys, picked, types


def join(eng, ctx, refs, h_, src):
    """A join: one index per lookup, then per unit its picked values (the unit's key read along its own chain). Entry i of the output
    belongs to unit i; a row is keyed by the values it read and linked to its unit row and every lookup row it read."""
    rec, recipe, memo = eng.rec, ctx["recipe"], {}
    work = eng.node(recipe)["spec_h"]
    in_t, in_set, es = entries_of(eng, src, memo)
    reads = ctx.get("read") or {}
    keys, picked, types = join_columns(eng, recipe, ctx, memo)
    params = recipes.params(eng, recipe)
    cols, miss, many, asof = eng.node(recipe)["payload"]["cols"], params.get("miss", "empty"), params.get("many") or [], params.get("asof") or {}
    index = {role: lookup_index(eng, role, reads[role], list(keys[role]), picked[role], memo, role in many, (asof.get(role) or [None])[0])
             for role in keys}
    root = names.line_of(eng, inner(eng, eng.node(recipe)["links"]["module"]))
    out_t = contract_table(eng, h("contract", canonical({"line": root, "writes": types})), "join_" + "_".join(sorted(keys)), types,
                           inner(eng, eng.node(recipe)["links"]["module"]), recipe)
    run_n = start(eng, ctx, refs, h_, input_set=in_set, units=units_of(eng, src, memo), of=len(es), out_table=out_t,
                  reads={role: entries_of(eng, reads[role], memo)[1] for role in sorted(reads)})
    counts = {"rows_total": len(es), "made": 0, "reused": 0, "failed": 0, "outputs_made": 0, "calls": 0}
    out, missed, empty = [], 0, {role: 0 for role in many}
    for i, (m, sp, _) in enumerate(es):
        rows_ = along(eng, src, i, memo)
        vals, read, key_vals, found = {}, [], {}, True
        for role, kv in keys.items():
            got = [read_value(rows_, uc) for uc in kv.values()]
            read += [at for _, _, at in got if at]
            key = tuple(v for v, _, _ in got)
            key_vals[role] = [None if v is MISSING else v for v in key]
            if role in many:
                hits = index[role].get(key, [])
                if role in asof:
                    t_, _, t_at = read_value(rows_, asof[role][1])
                    read += [t_at] if t_at else []
                    key_vals[role].append(None if t_ is MISSING else t_)
                    hits = [x for x in hits if t_ is not MISSING and t_ is not None and x[1][asof[role][0]] < t_]
                empty[role] += not hits
                for x in hits:
                    read.append((line_table(eng, reads[role], memo), x[0]))
                    read += x[2]
                for out_c, src_c in cols.items():
                    if src_c.partition(".")[0] == role:
                        vals[out_c] = [x[1][src_c.partition(".")[2]] for x in hits]
                continue
            hit = index[role].get(key)
            found = found and hit is not None
            if hit:
                read.append((line_table(eng, reads[role], memo), hit[0]))
                read += hit[2]
            for out_c, src_c in cols.items():
                if src_c.partition(".")[0] == role:
                    vals[out_c] = hit[1][src_c.partition(".")[2]] if hit else None
        ih = in_hash({"src": {"key": key_vals, **vals}})
        if not found:
            missed += 1
            if miss == "drop":
                continue
            if miss == "fail":
                rec.insert("bitt.run_error", {"bitt_run_hash": run_n, "bitt_in_hash": ih, "src": {"src": m}, "seq": counts["failed"],
                                              "error": f"no {' / '.join(r for r in keys if index[r].get(tuple(key_vals[r])) is None)} row "
                                                       f"for this unit's key"})
                counts["failed"] += 1
                continue
        link_sources(rec, out_t, ih, in_t, m, read)
        key_ = out_hash(work, ih, 0, 0)
        if rec.get_row(out_t, (key_,)) is None:
            rec.insert(out_t, {"bitt_row_hash": key_, "bitt_in_hash": ih, "bitt_recipe_hash": work, "bitt_run_hash": run_n,
                               "bitt_sample": 0, "bitt_part": 0, "bitt_parts": 1, **vals, "bitt_extra": None})
            counts["made"] += 1
            counts["outputs_made"] += 1
        else:
            counts["reused"] += 1
        out.append((key_, sp, i))
    out_set = sets.write_set(rec, out_t, out, "run_out", run_n) if out else None
    end(rec, run_n, counts, "failed" if counts["failed"] else "done", out_set)
    if missed and miss != "fail":
        what = "read as empty" if miss == "empty" else "left out"
        warn(eng, ctx, f"run of {recipes.label(eng, recipe)}: {missed} of {len(es)} units found no {' / '.join(sorted(keys))} row "
                       f"({what})")
    for role, n in empty.items():
        if n:
            warn(eng, ctx, f"run of {recipes.label(eng, recipe)}: {n} of {len(es)} units found no {role} row (read as [])")
    return {"run": run_n}


def line_table(eng, ref, memo):
    return entries_of(eng, ref, memo)[0]


# ---------------------------------------------------------------- a person's answers (C9)
def i_answer(eng, e, ctx, refs):
    rec, run = eng.rec, eng.node(ctx["run"])
    recipe, memo = run["links"]["recipe"], {}
    work, out_t = eng.node(recipe)["spec_h"], run["payload"]["out_table"]
    src = walker(eng, memo).links(ctx["run"], "on")[0]
    _, _, es = entries_of(eng, src, memo)
    prompt = eng.node(recipes.artifacts(eng, recipe)["prompt"])
    cols = eng.node(recipe)["payload"]["cols"]
    asks = run["payload"]["asks"]
    made, kept = 0, 0
    for ref, text in (ctx["answers"] or {}).items():
        hit = [m for m in asks if m.startswith(str(ref))]
        if len(hit) != 1:
            raise Refused(f"run.answer: {ref!r} is {'not a row' if not hit else 'several rows'} of this run (it asks {len(asks)} rows)")
        keys = {}                                                # every unit that asked this row: its own key (what it read)
        for i in [i for i in range(run["payload"]["upto"]) if es[i][0] == hit[0]]:
            ih = in_hash({"src": values_at(eng, src, i, cols, memo)[0]})
            keys[out_hash(work, ih, 0, 0)] = ih
        todo = {k_: ih for k_, ih in keys.items() if rec.get_row(out_t, (k_,)) is None}
        if not todo:
            kept += 1
            continue
        try:
            o = prompts.parse_reply(str(text), prompt["payload"]["contract"], prompt["payload"]["contract"].get("plain"))
        except ValueError as x:
            raise Refused(f"run.answer: the answer for {hit[0][:12]} does not fit the prompt: {x}") from None
        for key, ih in todo.items():
            rec.insert(out_t, {"bitt_row_hash": key, "bitt_in_hash": ih, "bitt_recipe_hash": work, "bitt_run_hash": ctx["run"],
                               "bitt_sample": 0, "bitt_part": 0, "bitt_parts": 1, **o})
        made += 1
    return {"answered": eng.make("answer", ctx, refs, made=made, kept=kept)}


def person_entries(eng, run_n):
    """A person run's entries so far: each unit of its rung whose row has an answer, in unit order (d15.md §3.1)."""
    run, memo = eng.node(run_n), {}
    recipe = run["links"]["recipe"]
    work, out_t, cols = eng.node(recipe)["spec_h"], run["payload"]["out_table"], eng.node(recipe)["payload"]["cols"]
    src = walker(eng, memo).links(run_n, "on")[0]
    _, _, es = entries_of(eng, src, memo)
    out = []
    for i in range(run["payload"]["upto"]):
        key = out_hash(work, in_hash({"src": values_at(eng, src, i, cols, memo)[0]}), 0, 0)
        if eng.rec.get_row(out_t, (key,)) is not None:
            out.append((key, es[i][1], i))
    return out


def i_close(eng, e, ctx, refs):
    rec, run = eng.rec, eng.node(ctx["run"])
    t, got = run["payload"]["out_table"], person_entries(eng, ctx["run"])
    out_set = sets.write_set(rec, t, got, "run_out", ctx["run"]) if got else None
    n = run["payload"]["upto"]
    end(rec, ctx["run"], {"rows_total": n, "made": len(got), "failed": n - len(got)}, "done", out_set)
    return {"closed": eng.make("answer", ctx, refs, closed=True, answered=len(got), of=n)}


def c_person_open(eng, s, scope):
    n = eng.node(s)
    if not n["payload"].get("person"):
        return "fail", "not a person run"
    return ("fail", "the run is closed") if eng.rec.get_row("bitt.run_end", (s,)) else ("pass", "open")


def c_input_complete(eng, s, scope):
    open_ = [x for x in as_list(scope.get("on")) if eng.node(x)["kind"] == "run" and eng.node(x)["payload"].get("person")
             and not eng.rec.get_row("bitt.run_end", (x,))]
    return ("fail", f"run {open_[0][:12]} is a person run still open: its answers so far are partial") if open_ else ("pass", "complete")


def other_task_loose(eng, task, refs):
    """[(input, its task)]: the inputs read from another task that are not a version of its dataset or evalset (#4)."""
    out = []
    for x in refs:
        t = eng.task_of(x)
        if t and t != task and not (eng.node(x)["kind"] in ("dataset", "evalset") and names.version_of(eng, x)):
            out.append((x, t))
    return out


def c_other_task_versioned(eng, s, scope):
    task = eng.task_of(scope["in"])
    loose = other_task_loose(eng, task, [*as_list(scope.get("on")), *(scope.get("read") or {}).values()])
    if loose:
        x, t = loose[0]
        return "fail", (f"{names.label(eng, x) or eng.node(x)['kind'] + ' ' + x[:12]} is task {names.task_name(eng, t)}'s and not a version: "
                        "it may change under you")
    return "pass", "every input from another task is a version"


def c_judged_in_plan(eng, s, scope):
    """SOP Q5 (owner 11-04): how a thing is judged is decided before it is judged. In a working cycle the plan's eval judges; a check run
    outside it (not the eval's own step) is allowed and warned: its verdicts are a hint. Explore cycles are free."""
    cyc = scope.get("in")
    if not cyc or eng.node(cyc)["kind"] != "cycle" or eng.node(cyc)["payload"].get("level") != "working":
        return "pass", "not a working cycle"
    if scope["_stamp"]["actor"].startswith("pipeline:") or eng.stack.count("run.go") > 1:
        return "pass", "a step of an eval"
    return "fail", "a check run outside the plan's eval: its verdicts are a hint, never this cycle's result"


def c_arm_on_version(eng, s, scope):
    """A working cycle's verdict is a result: when an eval judges its plan, an arm runs on versions only (what it walks and reads, up
    to the nearest data), so the decision names frozen data. Explore cycles and person-judged plans are free."""
    from ..walk import Walk
    from .tag import not_a_version
    cyc = scope.get("in")
    if not cyc or eng.node(cyc)["kind"] != "cycle" or eng.node(cyc)["payload"].get("level") != "working":
        return "pass", "not a working cycle"
    plan = eng.latest_plan(cyc)
    arms = as_list(plan["links"].get("arms")) if plan and plan["links"].get("pipeline") else []
    if not (scope.get("recipe") in arms or (scope.get("fills") and scope["fills"] in arms)):
        return "pass", "not an arm of an eval-judged plan"
    w = Walk(eng)
    stands = [d for x in [*as_list(scope.get("on")), *(scope.get("read") or {}).values()] for d in w.frontier(x)]
    from .module import pins_of
    if (p := pins_of(eng, plan["links"]["pipeline"]).get("on")) and set(w.frontier_of(as_list(scope.get("on")))) != {p}:
        return "fail", (f"this plan's eval judges {names.label(eng, p) or p[:12]} only: an arm runs on exactly that "
                        "(for other data, another eval: a wrap that does not pin it)")
    if loose := not_a_version(eng, dict.fromkeys(stands)):
        x = loose[0]
        return "fail", (f"an arm of this working cycle's plan runs on {names.label(eng, x) or eng.node(x)['kind'] + ' ' + x[:12]}, which is "
                        "not a version: its verdict would be a result on data nobody named")
    return "pass", "the arm runs on versions"


def c_pinned(eng, s, scope):
    """A wrap that pins data runs on it and nothing else: `on` stands on exactly the pinned units (a run made from them counts),
    each other pinned role is read as exactly that data."""
    from ..walk import Walk
    from .module import pins_of
    pins = pins_of(eng, eng.node(s)["links"]["module"])
    if not pins:
        return "pass", "pins nothing"
    w, read = Walk(eng), scope.get("read") or {}
    label = lambda x: names.label(eng, x) or eng.node(x)["kind"] + " " + x[:12]  # noqa: E731
    for role, d in sorted(pins.items()):
        got = as_list(scope.get("on")) if role == "on" else ([read[role]] if role in read else [])
        if not got or set(w.frontier_of(got)) != {d}:
            where = "walks" if role == "on" else f"reads as `{role}`"
            return "fail", f"its wrap pins {label(d)}: it {where} that and nothing else"
    return "pass", f"on what its wrap pins ({', '.join(sorted(pins))})"


# ---------------------------------------------------------------- train: in an env, in the background, smoke first
def smoke_done(eng, work, in_set, env):
    return [r for r in eng.rec.find("run") if r["payload"].get("smoke") and r["payload"].get("input_set") == in_set
            and (r["payload"].get("env") or "local") == env and eng.node(r["links"]["recipe"])["spec_h"] == work
            and status_of(eng.rec, r["id"]) == "done"]


def model_line(eng, run):
    return run["payload"].get("model_line") or (eng.node(run["links"]["fills"])["payload"].get("name") if run["links"].get("fills") else None) \
        or f"{recipes.label(eng, run['links']['recipe']).split(':')[0].split('@')[0]}_model"


def model_place(eng, run_n, ctx, env):
    """Where a full train writes its model, in its env: <tasks>/<task>/artifacts/<cycle>/<line>/<run>/ (cycle: c<N>, the task's Nth)."""
    from .where import cycles
    task = eng.task_of(run_n)
    cyc = ctx.get("in")
    c = f"c{cycles(eng, task).index(cyc) + 1}" if cyc and eng.node(cyc)["kind"] == "cycle" else "nocycle"
    tn = names.task_name(eng, task) or task[:12]
    rel = f"{tn}/artifacts/{c}/{model_line(eng, eng.node(run_n))}/{run_n[:12]}"
    return f"{env.tasks_root().rstrip('/')}/{rel}", rel


def train(eng, ctx, refs, h_, src):
    """The first train of a recipe on a dataset in an env is a smoke run (the first row of each split); the next trains in full
    (`skip_smoke`: full now, a warning). The job runs in the background; its model lands at exec.job.sync."""
    rec, recipe = eng.rec, ctx["recipe"]
    env_name = ctx.get("env") or "local"
    env = envs.get(env_name)
    if why := env.guard():
        raise Refused(f"run.go: {why}")
    in_t, in_set, rs = table_rows(eng, src, eng.node(recipe)["payload"]["cols"])
    work = eng.node(recipe)["spec_h"]
    smoke = ctx.get("skip_smoke") != "yes" and not smoke_done(eng, work, in_set, env_name)
    if ctx.get("skip_smoke") == "yes" and not smoke_done(eng, work, in_set, env_name):
        warn(eng, ctx, f"run of {recipes.label(eng, recipe)}: a full train without a passed smoke run in {env_name!r} (skip_smoke)")
    if smoke:
        seen, first = set(), []
        for r, m in rs:
            if r["bitt_split"] not in seen:
                seen.add(r["bitt_split"])
                first.append((r, m))
        rs = first
    run_n = start(eng, ctx, refs, h_, input_set=in_set, of=len(rs), smoke=smoke, env=env_name,
                  **({"model_line": ctx["line"]} if ctx.get("line") else {}))
    spec = job_spec(h_)
    if not smoke:                                                 # a full train writes its model where bitt says, in the env
        spec["model_dir"], spec["model_rel"] = model_place(eng, run_n, ctx, env)
    j, _ = job(eng, ctx, spec, code_of(eng, eng.node(recipe)["links"]["module"]), [r for r, _ in rs], recipes.params(eng, recipe),
               recipes.artifacts(eng, recipe), background=True)
    return {"run": run_n, "job": j}


def run_of_job(eng, job):
    ev = eng.node(eng.node(job)["links"]["caller_event"])
    return next(n["id"] for n in eng.kids(ev["id"], role="event", kind="run"))


def f_go(eng, ctx, caller):
    """A train's job is done: its reported numbers → rows of its report table (d15.md §3.5), and a model (an artifact of kind model: the files the job
    wrote into its model folder, recorded by name, size and sha256 where they sit, never copied) with, when the run named one, its endpoint (a wrap of that module, the model in its `file` role). A smoke run
    proves the wiring and makes no model; a failed job is never a model."""
    rec, run_n = eng.rec, run_of_job(eng, ctx["job"])
    run = eng.node(run_n)
    if run["payload"]["kind"] != "train":
        return {"run": run_n}, []                                # a row / table job: the run itself writes what came back
    d = envs.get(run["payload"].get("env") or "local").fetch(ctx["job"])
    if (d / "reported.jsonl").exists():
        reports(eng, run_n, d / "reported.jsonl", ctx["_event"])
    end(rec, run_n, {"rows_total": run["payload"]["of"], "made": 0 if run["payload"].get("smoke") else 1, "calls": 1}, "done")
    if run["payload"].get("smoke"):
        return {"run": run_n}, []
    mf = d / "output" / "manifest.json"
    files = json.loads(mf.read_text()) if mf.exists() else []
    if not files:
        raise Refused("exec.job.finish: the train job wrote no model files (its model folder is empty)")
    task = eng.task_of(run_n)
    line = model_line(eng, run)
    stamp = {**ctx["_stamp"], "tool": "run", "card": "run.go"}
    root = names.join(eng, task, line, "artifact")
    keep = {k: v for k, v in run["links"].items() if k in ("in", "fills", "evals")}
    fp = json.loads((d / "fingerprint.json").read_text()) if (d / "fingerprint.json").exists() else {}
    spec_ = json.loads((d / "job.json").read_text())
    m = rec.put("artifact", {"artifact_kind": "model", "files": files, "size": sum(f["size"] for f in files),
                             "at": {"env": run["payload"].get("env") or "local", "path": spec_["model_dir"], "rel": spec_["model_rel"]},
                             "contract": {"needs": [], "gives": {}}, "fingerprint": fp,
                             "does": f"a model trained by {recipes.label(eng, run['links']['recipe'])} (run {run_n[:12]})"},
                {"event": ctx["_event"], "run": run_n, **keep, **names.line_link(root)}, stamp)
    names.settle(eng, {"_stamp": stamp}, task, line, m, root)
    out_ = {"model": m, "run": run_n}                          # the model first: what a deferred requirement (control.fills) judges
    if ep := run["links"].get("endpoint"):
        h_ = eng.node(ep)["payload"]["header"]
        w = rec.put("module", {"header": {**h_, "roles": {k: v for k, v in h_["roles"].items() if k != "file"},
                                          "does": f"{names.label(eng, ep) or 'the endpoint'} serving {line}"},
                               "fixed": {"params": {}, "artifacts": {"file": m}}},
                    {"event": ctx["_event"], "wraps": ep, "artifacts": [m], "in": run["links"]["in"]}, stamp)
        names.settle(eng, {"_stamp": stamp}, task, f"{line}_endpoint", w, None)
        out_["endpoint"] = w
    return out_, [("model.created", run["links"].get("in"), "run.go")]


def reports(eng, run_n, path, node):
    """Each `job.report(step=…, …)` line → the row of that step in the train's report table (its run's own rows: keyed by run and step).
    A name the module does not declare fails the landing. Reported values are what the script says: never a check."""
    rec, run = eng.rec, eng.node(run_n)
    recipe = run["links"]["recipe"]
    declared = recipes.header(eng, recipe).get("reports") or {}
    by_step = {}
    for line in (x for x in path.read_text().splitlines() if x.strip()):
        r = json.loads(line)
        step = r.pop("step", 0)
        if extra := sorted(k for k in r if k not in declared):
            raise Failed(f"exec.job.finish: the train reported {extra}, which its module does not declare (it declares "
                         f"{sorted(declared) or 'none'}). next: declare them in BITT[\"reports\"] ({{name: type}}), or stop reporting them")
        by_step.setdefault(step, {}).update(r)
    t = report_table(eng, recipe, node)
    ih = h("in", canonical({"run": run_n}))
    for step, vals in sorted(by_step.items()):
        try:
            rec.insert(t, {"bitt_row_hash": h("report", canonical({"run": run_n, "step": step})), "bitt_in_hash": ih,
                           "bitt_recipe_hash": eng.node(recipe)["spec_h"], "bitt_run_hash": run_n, "bitt_sample": 0, "bitt_part": 0,
                           "bitt_parts": 1, "step": step, **vals})
        except Refused as x:
            raise Failed(f"exec.job.finish: a reported value does not fit its declared type: {x}") from None


def ended(eng, job):
    """Has a running job's env finished it (done or failed)? A read: polling writes nothing, only the landing does."""
    if eng.job_status(job) != "running":
        return False
    try:
        st = envs.get(eng.node(job)["payload"]["needs"].get("env") or "local").status(job)
    except Refused:
        return False
    return st not in ("staged", "running", "unreachable")


def i_sync(eng, e, ctx, refs):
    """exec.job.sync: ask the job's env; a job that ended is finished (done → the caller's finish handler lands it)."""
    j = eng.node(ctx["job"])
    if eng.job_status(ctx["job"]) != "running":
        return {"job_status": eng.make("job_status", ctx, refs, status=eng.job_status(ctx["job"]))}
    env = envs.get(j["payload"]["needs"].get("env") or "local")
    st = env.status(ctx["job"])
    if st in ("staged", "running", "unreachable"):
        return {"job_status": eng.make("job_status", ctx, refs, status=st)}
    d = env.fetch(ctx["job"])
    done = st == "done"
    eng.call("exec.job.finish", {"job": ctx["job"], "outputs": [], "status": "done" if done else "failed",
                                 "reason": None if done else f"{st}: {log_tail(d)}"}, actor="system")
    run_n = run_of_job(eng, ctx["job"])
    if eng.job_status(ctx["job"]) in ("failed", "rejected") and not eng.rec.get_row("bitt.run_end", (run_n,)):
        end(eng.rec, run_n, {"rows_total": eng.node(run_n)["payload"].get("of", 0)}, "failed")   # a failed job, or a refused landing
    return {"job_status": eng.make("job_status", ctx, refs, status=eng.job_status(ctx["job"]))}


def land(eng, job, actor="system", timeout=120):
    """Wait for a background job and land it (one exec.job.sync once it ended): what it made {run, model, endpoint} (tests, replays)."""
    t0 = time.monotonic()
    while eng.job_status(job) == "running" and time.monotonic() - t0 < timeout:
        if ended(eng, job):
            eng.call("exec.job.sync", {"job": job}, actor=actor)
        else:
            time.sleep(0.05)
    run_n = run_of_job(eng, job)
    made = {"run": run_n}
    for n in eng.kids(run_n, role="run", kind="artifact"):
        made["model"] = n["id"]
        for w in eng.kids(n["id"], role="artifacts", kind="module"):
            made["endpoint"] = w["id"]
    return made


# ---------------------------------------------------------------- a policy's rule
def policy_runner(eng, recipe, card, inputs):
    """control.policy: its rule (a row check recipe) judges the call's inputs as one row (its cols bind its roles to input names);
    the call goes on only if every bool verdict is true. A scratch job: it records nothing (the refusal does)."""
    recipe = recipe["id"] if isinstance(recipe, dict) else recipe   # the kernel hands the rule's node
    rn = eng.node(recipe)
    h_ = recipes.header(eng, recipe)
    if h_["kind"] != "check" or h_["scope"] != "row":
        return False, "a policy's rule is a row check recipe"
    row = {role: inputs.get(col) for role, col in rn["payload"]["cols"].items()}
    env = envs.get("local")
    d = env.local_dir(f"policy-{h('policy', canonical([recipe, card, row]))[:24]}")
    envs.write_module_job(d, {**job_spec(h_), "params": recipes.params(eng, recipe)}, code_of(eng, rn["links"]["module"]), [row],
                          env.python())
    if run_dir(env, d) != "done":
        return False, f"the policy's rule did not run: {log_tail(d, 200)}"
    (got,) = read_rows(d, 1)
    if isinstance(got, Exception):
        return False, f"the policy's rule failed on these inputs: {got}"
    bad = [k for k, v in got.items() if h_["writes"].get(k) == "bool" and v is not True]
    return (False, f"{', '.join(bad)} is false for {row}") if bad else (True, "passes")


# ---------------------------------------------------------------- rules (the kind × rule table)
def c_input_fits(eng, s, scope):
    ons = as_list(scope.get("on"))
    if not ons:
        return "fail", "a run reads data: --on <data> (a raw line, a set, a dataset, an evalset, or a run)"
    cols, memo = eng.node(s)["payload"]["cols"], {}
    if recipes.header(eng, s)["kind"] == "join":
        return join_fits(eng, s, ons, scope.get("read") or {}, memo)
    for src in ons:
        try:
            _, _, es = entries_of(eng, src, memo)
        except Refused as x:
            return "fail", str(x)
        if es:
            rows_ = along(eng, src, 0, memo)
            for role, col in cols.items():
                if (p := read_value(rows_, col)[1]):
                    return "fail", f"{role} ← {col}: {p}"
    for role, src in sorted((scope.get("read") or {}).items()):   # a union's or a table derive's named inputs: each one readable
        try:
            entries_of(eng, src, memo)
        except Refused as x:
            return "fail", f"{role}: {x}"
    return "pass", "every bound column is there"


def join_fits(eng, recipe, ons, reads, memo):
    """A join's inputs (docs/v2/inputs.md §3): a key for every lookup and a lookup for every key, each key column on both sides, every
    picked column in its lookup."""
    from .recipe import join_keys
    keys = join_keys(recipes.params(eng, recipe)["key"])
    if extra := sorted(set(reads) - set(keys)):
        return "fail", f"no key for {extra[0]} (the key names {sorted(keys)}). next: --params key='{{\"{extra[0]}\": \"<column>\"}}'"
    if lack := sorted(set(keys) - set(reads)):
        return "fail", f"the key names {lack[0]}, but nothing is read as {lack[0]}. next: --read {lack[0]}=<data>"
    want = {role: [*kv] for role, kv in keys.items()}
    for src in eng.node(recipe)["payload"]["cols"].values():
        role, _, col = src.partition(".")
        want[role].append(col)
    asof = recipes.params(eng, recipe).get("asof") or {}
    for role, (lc, _) in asof.items():
        want[role].append(lc)
    sides = [(ons[0], "the units", [uc for kv in keys.values() for uc in kv.values()] + [uc for _, uc in asof.values()])] + \
            [(reads[r], r, want[r]) for r in sorted(want)]
    for ref, who, cols in sides:
        try:
            _, _, es = entries_of(eng, ref, memo)
        except Refused as x:
            return "fail", str(x)
        if es:
            rows_ = along(eng, ref, 0, memo)
            for col in dict.fromkeys(cols):
                if (p := read_value(rows_, col)[1]):
                    return "fail", f"{who}: {p}"
    return "pass", "every key and picked column is there"


def sensitivity_of(eng, ref):
    """The most sensitive data a node was built from (its raw imports)."""
    worst = "public"
    for x in eng.lineage(ref):
        s = eng.node(x)["payload"].get("sensitivity") if eng.node(x)["kind"] == "raw" else None
        if s and envs.SENSITIVITY.index(s) > envs.SENSITIVITY.index(worst):
            worst = s
    return worst


def c_sensitivity(eng, s, scope):
    env = envs.get(scope.get("env") or "local")
    top = env.c.get("max_sensitivity", "internal")
    for src in [*as_list(scope.get("on")), *(scope.get("read") or {}).values()]:
        worst = sensitivity_of(eng, src)
        if envs.SENSITIVITY.index(worst) > envs.SENSITIVITY.index(top):
            return "fail", f"env {env.name!r} takes data up to {top!r}; the input is {worst!r}"
    return "pass", f"env {env.name!r} takes up to {top!r}"


def c_endpoint_serves(eng, s, scope):
    p = recipes.params(eng, s)
    if not p.get("url") or not p.get("model"):
        return "pass", "no endpoint named (a module that runs in its job)"
    import urllib.request
    req = urllib.request.Request(p["url"].rstrip("/") + "/models")
    if (k := key_env(p)):
        req.add_header("Authorization", f"Bearer {k['BITT_KEY']}")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            served = [m.get("id") for m in json.loads(r.read()).get("data", [])]
    except Exception as x:                                   # noqa: BLE001 — any failure to ask is the answer
        return "fail", f"{p['url']} did not answer /models ({type(x).__name__}: {str(x)[:120]})"
    return ("pass", f"{p['url']} serves {p['model']}") if p["model"] in served else \
        ("fail", f"{p['url']} serves {served}, not {p['model']!r}")


def c_has_eval(eng, s, scope):
    evs = as_list(scope.get("evals"))
    if not evs:
        return "fail", "a train names its eval before it starts"
    bad = [e for e in evs if eng.kind_of(e) != "check"]
    return ("fail", f"{len(bad)} eval(s) are not check recipes") if bad else ("pass", f"{len(evs)} eval(s)")


def c_min_n(eng, s, scope):
    need = int((scope.get("invalid_if") or {}).get("min_n") or 0)
    e = eng.rec.get_row("bitt.run_end", (s,))
    n = e["rows_total"] if e else 0
    return ("pass", f"{n} rows ≥ {need}") if n >= need else ("fail", f"judged {n} rows, fewer than min_n {need}")


def c_inputs_declared(eng, s, scope):
    h_ = recipes.header(eng, s)
    if h_["kind"] == "generate" and not h_["reads"]:
        return "pass", "a connector: the endpoint it calls is its declared input"
    why = untraced_why(code_of(eng, eng.node(s)["links"]["module"]))
    return ("fail", f"untraced: {why}") if why else ("pass", "reaches nothing outside its job folder")


def package():
    from . import rules as g
    from . import pipeline as pl
    return Package(name="run", cards=[CARDS / "run.yaml"], finish={"run.go": f_go}, listeners=[pl.listen], policy_runner=policy_runner,
                   impls={"run.go": i_go, "exec.job.sync": i_sync, "run.answer": i_answer, "run.close": i_close},
                   rules={"run.input_fits": c_input_fits, "run.sensitivity": c_sensitivity, "run.endpoint_serves": c_endpoint_serves,
                           "run.has_eval": c_has_eval, "run.min_n": c_min_n, "run.inputs_declared": c_inputs_declared,
                           "run.person_open": c_person_open, "run.input_complete": c_input_complete, "run.other_task_versioned": c_other_task_versioned, "run.judged_in_plan": c_judged_in_plan, "run.arm_on_version": c_arm_on_version, "run.pinned": c_pinned,
                           "run.contamination": g.c_contamination, "run.leak": g.c_leak, "run.split_assigned": g.c_split_assigned,
                           "run.group_leak": g.c_group_leak, "run.unit_set": g.c_unit_set, "run.frozen_test": g.c_frozen_test,
                           "run.excluded_kept": g.c_excluded_kept, "run.win_clean": pl.c_win_clean})

