"""Pipeline modules (foundation.md §C3, §K): Python that orders steps, each `b.run(...)` a run of its own recipe.

  b.run(name, on=…, with_=…, cols=…, params=…)   a step: `name` is a module (its recipe), or a prompt run `with_` a generate module;
                                                 every name was pinned when the pipeline's recipe was made (C11), so one recipe is
                                                 always the same work; the step's rows, table and reuse are its own
The ladder goes through the steps: the first step climbs (smoke → its sample, then all), a later step runs in full over what the step before it
made, and a failed step ends the run. An eval is a pipeline whose header declares one `win` rule over a column of the one row its
function's run made (an aggregate's, d15.md §3.4): its run makes a decision (control) that keeps the row it read. A plan's eval runs on
each arm when it is filled.

The pipeline's function runs inside bitt (it only orders kernel calls: no `while`, module.header), with nothing but `b` and `on`.
"""
from .. import names
from ..errors import Refused
from ..util import as_list
from ..walk import Walk
from . import header as headers
from . import recipe as recipes
from .module import code_of


class StepFailed(Exception):
    pass


def pins(eng, module, task, params):
    """{name: id}: every module or artifact the pipeline's steps name (as text, or through a text param), resolved now."""
    h_ = eng.node(module)["payload"]["header"]
    want = list(h_.get("steps", [])) + [v for v in params.values() if isinstance(v, str)]
    out = {}
    for n in dict.fromkeys(want):
        try:
            nid = eng.resolve(n, task, ["module", "artifact"])[0]
        except Refused:
            if n in h_.get("steps", []):
                raise Refused(f"recipe.make: the pipeline's step names {n!r}, which is not a module or an artifact here. next: add it "
                              "first (bitt module add / bitt artifact add)") from None
            continue                                            # a text param that names nothing (a column, a label)
        out[n] = nid
    return out


class B:
    def __init__(self, eng, ctx, pinned):
        self.eng, self.ctx, self.pinned, self.steps = eng, ctx, pinned, []
        self.mine, self.warnings = set(), []
        self.read = dict(ctx.get("read") or {})                # the run's other inputs, by role: for a join step (docs/v2/inputs.md)

    def _pin(self, name):
        if name not in self.pinned:
            raise Refused(f"run.go: a step names {name!r}, which the pipeline's recipe did not pin (a step names a module or an artifact as "
                          "text, or through a text param)")
        return self.pinned[name]

    def run(self, name, on, with_=None, cols=None, params=None, artifacts=None, read=None):
        eng, ctx = self.eng, self.ctx
        target = self._pin(name)
        if eng.node(target)["kind"] == "artifact":
            if not with_:
                raise Refused(f"run.go: step {name!r} is an artifact: name the module that runs it (with_=…)")
            module, arts = self._pin(with_), {"prompt": target, **(artifacts or {})}
        else:
            module, arts = target, dict(artifacts or {})
        args = {"in": ctx["in"], "module": module, "params": params or {}, "cols": cols or {}}
        if arts:
            args["artifacts"] = {r: self._pin(a) if a in self.pinned else a for r, a in arts.items()}
        r = eng.call("recipe.make", args, actor=ctx["_stamp"]["actor"])["recipe"]
        later = any(x in self.mine for x in as_list(on))
        got = eng.call("run.go", {"in": ctx["in"], "recipe": r, "on": as_list(on), **({"read": read} if read else {}),
                                  **({"full": "yes"} if later or ctx.get("full") == "yes" else {})}, actor=ctx["_stamp"]["actor"])
        run = got["run"]
        self.warnings += [w for w in got.get("warnings", []) if not (later and "ladder was skipped" in w)]   # a later step runs in full by design
        self.steps.append(run)
        self.mine.add(run)
        from .run import status_of
        if status_of(eng.rec, run) == "failed":
            raise StepFailed(f"step {recipes.label(eng, r)} failed")
        return run


def run_pipeline(eng, ctx, refs, h_):
    from .run import end, start
    recipe = ctx["recipe"]
    ons = as_list(ctx.get("on"))
    pinned = eng.node(recipe)["payload"].get("pins") or {}
    params = recipes.params(eng, recipe)
    env = {"__builtins__": SAFE_BUILTINS}
    exec(compile(code_of(eng, eng.node(recipe)["links"]["module"]), "pipeline", "exec"), env)   # its function only orders `b.run`
    b, failed, result = B(eng, ctx, pinned), None, None
    try:
        result = env[h_["fn"]](b, ons[0] if len(ons) == 1 else ons, **params)
    except StepFailed as x:
        failed = str(x)
    run_n = start(eng, ctx, refs, h_, input_set=None, of=len(b.steps), _links={"steps": b.steps},
                  **({"result": result} if isinstance(result, str) and result in eng.rec.nodes else {}))
    end(eng.rec, run_n, {"rows_total": len(b.steps), "made": len(b.steps), "calls": len(b.steps)}, "failed" if failed else "done")
    out = {"run": run_n, **({"warnings": list(dict.fromkeys(b.warnings))} if b.warnings else {})}
    if failed:
        eng.make("warning", ctx, {"in": ctx["in"]}, detail=f"pipeline {recipes.label(eng, recipe)}: {failed}; the run ends there")
    elif h_.get("win"):
        out["decision"] = decide(eng, ctx, refs, h_, run_n, result, ons)
    return out


SAFE_BUILTINS = {n: __builtins__[n] if isinstance(__builtins__, dict) else getattr(__builtins__, n)
                 for n in ("len", "range", "enumerate", "zip", "min", "max", "sum", "sorted", "list", "dict", "str", "int", "float",
                           "bool", "isinstance", "ValueError")}


def decide(eng, ctx, refs, h_, run_n, result, subjects):
    """The eval's one rule over a column of the one row the run its function returned made → a decision that keeps that whole row."""
    from .run import one_row
    m = headers.WIN.fullmatch(h_["win"])
    if not (isinstance(result, str) and result in eng.rec.nodes and eng.node(result)["kind"] == "run"):
        raise Refused(f"run.go: an eval's function returns the run its win reads ({h_['win']}), not {type(result).__name__}")
    read = one_row(eng, result)
    if read is None:
        raise Refused(f"run.go: the win reads one row: return the aggregate's run (b.run(\"rate\", on=<the check's run>, …)); run "
                      f"{result[:12]} made no row or several")
    if m["column"] not in read:
        raise Refused(f"run.go: the win reads {m['column']!r}; the row it read has {sorted(read)}")
    got = read[m["column"]]
    if not isinstance(got, (int, float)) or isinstance(got, bool):
        raise Refused(f"run.go: the win reads {m['column']!r}, which is not a number ({got!r})")
    bar = float(m["bar"])
    won = {">=": got >= bar, ">": got > bar, "<=": got <= bar, "<": got < bar}[m["op"]]
    return eng.make("decision", ctx, {"in": ctx["in"]}, won=bool(won), rule=h_["win"], row=read,
                    final=True, _links={"subject": as_list(subjects), "eval": eng.node(ctx["recipe"])["links"]["module"],
                                        "run": run_n, "judged": [result]})


def c_win_clean(eng, s, scope):
    """A decision is clean only over a check trusted here: the check the aggregate ran on (its `on`), else the aggregate's own module."""
    from .tag import trust_of
    from .rules import judged_module
    w, warn = Walk(eng), []
    for r in w.links(s, "judged"):
        ons = [x for x in w.links(r, "on") if eng.node(x)["kind"] == "run"]
        judged = ons[0] if ons and eng.node(ons[0])["payload"].get("kind") == "check" else r
        if (t := trust_of(eng, judged_module(eng, judged), eng.task_of(scope["in"]))) == "hint":
            warn.append(f"the check is a hint in this task (trust {t}): promote it, or read the decision as a hint")
    return ("fail", "; ".join(warn)) if warn else ("pass", "a trusted check")


# ---------------------------------------------------------------- a plan's eval runs on each arm when it is filled
def listen(eng, ev, out):
    if ev == "validated":
        return on_approval(eng, out.get("validation"))
    made = out.get("model") or out.get("run")
    if ev not in ("run.done", "model.created") or not made:
        return
    if eng.node(made)["stamp"]["actor"].startswith("pipeline:") or eng.node(made)["payload"].get("kind") == "pipeline":
        return                                                  # an eval's own runs never start an eval (no loops)
    if ev == "run.done" and eng.node(made)["payload"].get("kind") == "train":
        return                                                  # a train's arm is measured when its model lands
    sk = eng.node(made)["links"].get("fills")
    rcp = eng.node(made)["links"].get("recipe")
    for cyc in (n["id"] for n in eng.rec.find("cycle")):
        if eng.cstate(cyc) not in ("WORK", "EXPLORE"):
            continue
        plan = eng.latest_plan(cyc)
        if not plan or not plan["links"].get("pipeline") or not eng.plan_confirmed(plan):
            continue                                            # an agent's plan is a proposal: its eval waits for the approve
        arms = as_list(plan["links"].get("arms"))
        if made in arms or (sk and sk in arms) or (rcp and rcp in arms):
            actor = f"pipeline:{plan['id'][:16]}"
            try:
                r = eng.call("recipe.make", {"in": cyc, "module": plan["links"]["pipeline"]}, actor=actor)["recipe"]
                eng.call("run.go", {"in": cyc, "recipe": r, "on": [made]}, actor=actor)
            except Refused:
                pass                                            # recorded as a refusal; the arm stays `filled`


def on_approval(eng, v):
    """A person approved an agent's plan: its eval runs now on every arm the agent already filled (owner 11-04: nothing is judged
    before the approve, nothing filled is lost after it)."""
    if not v or eng.node(v)["payload"]["verdict"] != "approve":
        return
    plan = eng.node(eng.node(v)["links"]["subject"])
    if plan["kind"] != "plan" or not plan["links"].get("pipeline") or not eng.plan_confirmed(plan):
        return
    cyc = plan["links"]["in"]
    if (eng.latest_plan(cyc) or {}).get("id") != plan["id"]:
        return
    for arm in as_list(plan["links"].get("arms")):
        if eng.arm_state(arm, plan) != "filled":
            continue
        n = eng.node(arm)
        if n["kind"] == "recipe":                               # a ref arm: its latest run in this cycle that fills
            runs = [r for r in eng.kids(arm, role="recipe", kind="run") if r["links"].get("in") == cyc and not eng._no_fill(r)]
            made = runs[-1]["id"] if runs else None
        else:
            made = eng.fill_of(arm)
        if made and eng.node(made)["kind"] in ("run", "artifact"):
            listen(eng, "model.created" if eng.node(made)["kind"] == "artifact" else "run.done",
                   {"model" if eng.node(made)["kind"] == "artifact" else "run": made})


__all__ = ["names"]
