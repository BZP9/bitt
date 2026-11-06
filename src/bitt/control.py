"""Control: the kernel's own impls (goals, acks, the default impl) and the control.* rules (§3, §6, §8, §10)."""
import re

from . import cards as lint
from . import names
from .errors import Refused  # noqa: F401
from .util import as_list


def generic(eng, e, ctx, refs):
    out = {}
    for k, f in lint.fields(e, "out", "min").items():
        if isinstance(f, dict) and "ref_out" in f and k != "event":
            kind = as_list(f["ref_out"])[0]
            out[k] = eng.make(kind, ctx, refs, **({"state": f["state"]} if "state" in f else {}))
    return out


def i_goal(eng, e, ctx, refs):
    bump = "major"
    if ctx.get("supersedes"):
        olds = as_list(ctx["supersedes"])    # one = refine / change / replace; several = merge
        bump = "minor" if len(olds) == 1 and eng.node(olds[0])["payload"].get("contract") == ctx.get("contract") else "major"
    return {"goal": eng.make("goal", ctx, refs, state="open", bump=bump), "bump": bump}


def i_open_root(eng, e, ctx, refs):
    """A task: a root goal, and its name (its namespace, names.md §2a)."""
    g = eng.make("goal", ctx, refs, state="open")
    names.bind(eng, ctx, "", ctx["name"], g)
    return {"goal": g}


def i_ack(eng, e, ctx, refs):
    """A drift ack (no `rule`) records the goal version it acknowledges, as a value (never a link: it may be another task's goal)."""
    extra = {}
    if ctx.get("rule") in (None, "control.goal_drift"):
        g = eng.goal_of(ctx["subject"])
        extra["goal_version"] = eng.current_goal(g)[-1] if g else None
    return {"ack": eng.make("ack", ctx, refs, **extra)}


def authority(eng, nid):
    """usr actors who may approve under nid's task: the root goal's `authority`, default the usr who opened it."""
    t = eng.task_of(nid) if nid else None
    if not t:
        return None                         # outside any task (a raw import): any usr
    root = eng.node(t)
    opener = root["stamp"]["actor"]
    return root["payload"].get("authority") or ([opener] if opener.startswith("usr") else [])


def c_approval(eng, s, scope):
    """Judged in the task of the call being gated (the task that versions / moves the alias / promotes): a usr in THAT task's authority,
    counting only validations made in that task. Another task's approve or reject never opens or closes this gate."""
    here = scope.get("in")
    gate_task = eng.task_of(here) if here else eng.task_of(s)
    auth = authority(eng, here) if here else authority(eng, s)
    vs = [n for n in eng.kids(s, role="subject", kind="validation") if n["payload"]["verdict"] in ("approve", "reject")
          and n["stamp"]["actor"].startswith("usr") and (auth is None or n["stamp"]["actor"] in auth)
          and eng.task_of(n["id"]) == gate_task]
    if vs and vs[-1]["payload"]["verdict"] == "approve":
        return "pass", "approved"
    return "fail", ("rejected by " + vs[-1]["stamp"]["actor"]) if vs else f"no approve validation by a usr with authority {auth} on the subject"


def c_fills(eng, s, scope):
    sk = eng.node(s)
    want = sk["payload"]["want_kind"]
    outs = [scope.get(k) for k in ("set", "model", "recipe") if isinstance(scope.get(k), str) and scope[k] in eng.rec.nodes]
    fill = next((eng.node(o) for o in outs if lint.kind_matches(want, eng.node(o)["kind"])), eng.node(scope["_main"]))   # v2: a select's set
    if fill["payload"].get("smoke"):
        return "pass", "a smoke run fills nothing"
    if not lint.kind_matches(want, fill["kind"]):
        return "fail", f"want wants {want}, got {fill['kind']}"
    lacking = [k for k in sk["payload"]["contract"].get("must_link", []) if not fill["links"].get(k)]
    return ("fail", f"missing {lacking}") if lacking else ("pass", "contract met")


DELEGABLE = ("close", "earlystop", "validate_pass")


def granted(eng, where, actor, act, at=None):
    """The grant to `actor` for `act` over `where` (a cycle, a goal or the task: a grant covers everything under its `in`) that was
    live at seq `at` (default: now): made before it and not revoked before it. A revoke stops a grant from then on; what it allowed
    before stays allowed."""
    line = {where, *eng.ancestors(where)}
    for g in eng.rec.find("grant"):
        if g["payload"]["to"] != actor or act not in (g["payload"].get("acts") or []) or g["links"].get("in") not in line:
            continue
        if at is not None and g["seq"] > at:
            continue
        if any(at is None or r["seq"] < at for r in eng.kids(g["id"], role="grant", kind="revocation")):
            continue
        return g
    return None


def may_act(eng, cyc, actor, act, at=None):
    """A person with authority on the task, or an agent a person granted `act` over `cyc` (kernel.md §3)."""
    return actor in (authority(eng, cyc) or []) or (actor.startswith("usr") and authority(eng, cyc) is None) \
        or granted(eng, cyc, actor, act, at) is not None


def c_grant_shape(eng, s, scope):
    acts, to = scope.get("acts"), str(scope.get("to") or "")
    if not re.fullmatch(r"agent:[\w.-]+", to):
        return "fail", f"a grant goes to an agent (agent:<name>), not {to!r}"
    if not isinstance(acts, list) or not acts or any(a not in DELEGABLE for a in acts):
        return "fail", f"acts must be a list of {list(DELEGABLE)}, not {acts!r}"
    return "pass", f"{to}: {acts}"


DATA_ARMS = ("want:dataset", "want:evalset", "dataset", "evalset", "selection")


def c_plan_has_eval(eng, s, scope):
    if scope.get("pipeline"):
        return "pass", "an eval judges the arms"
    if scope.get("judged_by") == "person":
        return "pass", "a person judges the arms"
    kinds = []
    for a in as_list(scope.get("arms")):
        n = eng.node(a)
        kinds.append(f"want:{n['payload'].get('want_kind')}" if n["kind"] == "want" else n["kind"].split(":")[0])
    other = [k for k in kinds if k not in DATA_ARMS]
    return ("pass", "data arms only: a person validates them") if not other else \
        ("fail", f"no eval for arms that are not data ({sorted(set(other))}): a working cycle judges them with an eval")


def plan_confirmed(eng, plan):
    """An agent proposes a plan; a person with authority confirms it (kernel.md §7). Made by such a person, or their latest verdict
    on it is approve."""
    auth = authority(eng, plan["id"]) or []
    if plan["stamp"]["actor"] in auth:
        return True
    vs = [v for v in eng.kids(plan["id"], role="subject", kind="validation") if v["stamp"]["actor"] in auth
          and v["payload"]["verdict"] in ("approve", "reject")]
    return bool(vs) and vs[-1]["payload"]["verdict"] == "approve"


def c_act_allowed(eng, s, scope):
    st, o = eng.cstate(s), scope["outcome"]
    if eng.node(s)["kind"] == "goal":
        if o not in ("close", "abandon"):
            return "fail", f"a goal takes only close / abandon, not `{o}`"
        a, auth = scope["_stamp"]["actor"], authority(eng, s) or []
        return ("pass", f"{o} a goal") if a in auth else ("fail", f"closing / abandoning a goal is the usr's ({auth}), not {a}'s")
    ok = {"close": st in ("ACT", "EXPLORE"), "iterate": st == "ACT", "spawn": st == "ACT",
          "resume": st == "PARKED", "park": st != "PARKED", "abandon": True, "earlystop": st != "PARKED"}[o]
    if not ok:
        return "fail", f"`{o}` is not open in {st}; next: {eng.states[st]['exit']}"
    a = scope["_stamp"]["actor"]
    if o in ("close", "earlystop") and eng.node(s)["payload"].get("level") == "working" and not may_act(eng, s, a, o):
        return "fail", (f"{a} may not {o} a working cycle: that is a person's, or an agent's a person granted it. next: ask a "
                        f"person (bitt grant {a} {o} --on <cycle | goal | task> --reason \"…\"), or log a finding and stop")
    return "pass", f"{o} in {st}"


def c_plan_wants(eng, s, scope):
    if eng.cstate(s) == "EXPLORE":
        return "pass", "explore: anything goes"
    if eng.stack.count("run") > 1:
        return "pass", "a step of a pipeline run acts for its plan"
    want = scope["_req"]["kind"]
    plan = eng.latest_plan(s)
    kinds = []
    for a in as_list(plan["links"].get("arms") if plan else None):
        n = eng.node(a)
        kinds.append(n["payload"]["want_kind"] if n["kind"] == "want" else n["kind"])
    if want == "model":                                   # a train needs a model arm (a model artifact, or a recipe / want wanting one)
        match = [k for k in kinds if k in ("artifact", "recipe", "run")]
    else:                                                 # `data`: a derive needs a dataset / evalset arm
        match = [k for k in kinds if k in ("dataset", "evalset")]
    return ("pass", "the plan wants it") if match else \
        ("fail", f"this cycle's plan has no {want} arm (arms: {kinds}); next: add the arm with a new `plan`, or `cycle.open` a branch")


def c_can_approve(eng, s, scope):
    """The validating usr needs authority in the task the validation is written in (it gates that task's versions), not the subject's."""
    a, auth = scope["_stamp"]["actor"], authority(eng, scope.get("in") or s)
    if a.startswith("usr") and (auth is None or a in auth):
        return "pass", a
    return "fail", f"{a} may not approve / reject here (authority: {auth}); a `pass` validation or a vote is fine"


def c_has_authority(eng, s, scope):
    auth = authority(eng, s) or []
    if auth and all(re.fullmatch(r"usr(:[\w.-]+)?", a) for a in auth):
        return "pass", str(auth)
    return "fail", f"authority {auth} must be a non-empty list of usr actors; open the task as a usr, or give `authority=[usr...]`"


def c_unique_task_name(eng, s, scope):
    """A task's name is free among task names (a renamed one included: never reused). That it can be its views' schema follows from
    names.problem (lower case, at most 40 characters, the schemas and pg_ reserved; tests/test_rule_pins.py pins it)."""
    name = scope.get("name")
    b = names.binding(eng, "", name)
    if b and b["links"]["target"] != s:
        return "fail", f"task name {name!r} is taken"
    return "pass", "unique"


def c_same_task(eng, s, scope):
    mine, theirs = eng.task_of(scope["in"]) if scope.get("in") else None, eng.task_of(s)
    if theirs is None or mine == theirs:
        return "pass", "same task"
    plan = eng.latest_plan(scope["in"]) if eng.node(scope["in"])["kind"] == "cycle" else None
    arms = set(as_list(plan["links"].get("arms"))) if plan else set()
    fills = {eng.fill_of(a) for a in arms} - {None}
    if s in arms or s in fills:
        return "pass", "adopted as an arm of this cycle's plan: judged here, for this task only"
    if eng.node(s)["kind"] == "score" and eng.node(s)["links"].get("target") in arms | fills:
        return "pass", "a score of an adopted arm: judged here, for this task only"
    return "fail", "that node belongs to another task: judge it with a finding here, or act in its own task"


def c_policy_shape(eng, s, scope):
    p = eng.node(s)["payload"]
    e = eng.eff.get(p.get("on_event"))
    if not e or e["kind"] != "maneuver":
        return "fail", f"a policy's on_event must be a maneuver card id, not {p.get('on_event')!r}"
    return "pass", f"a rule on {p['on_event']}"


def c_human_actor(eng, s, scope):
    a, auth = scope["_stamp"]["actor"], authority(eng, scope.get("in"))
    if a.startswith("usr") and (auth is None or a in auth):
        return "pass", a
    return "fail", f"{a} is not a usr with authority {auth} on this task (next: log a proposal for the usr)"


def c_not_root(eng, s, scope):
    return ("pass", "subgoal") if eng.node(s)["links"].get("in") else ("fail", "the root task is never versioned")


def c_goal_drift(eng, s, scope):
    g = eng.goal_of(s)
    if not g:
        return "pass", "no goal (a root import)"
    later = eng.goal_descendants(g)
    if not any(eng.node(x)["payload"].get("bump") == "major" for x in later):
        return "pass", "no goal major since (on any branch)"
    cur = eng.current_goal(g)[-1]
    for a in eng.kids(s, role="subject", kind="ack"):
        if a["payload"].get("rule") not in (None, "control.goal_drift"):
            continue
        v = a["payload"].get("goal_version")
        if v in [g] + later and not any(eng.node(x)["payload"].get("bump") == "major" for x in eng.goal_descendants(v)):
            return "pass", "acked; no goal major since the ack"
    return "fail", (f"{eng.node(s)['kind']} {s} was built under goal {g} "
                    f"({eng.node(g)['payload'].get('contract')}); current {cur} ({eng.node(cur)['payload'].get('contract')})")


def c_task_boundary(eng, s, scope):
    if not scope.get("in"):
        return "pass", "no intent of its own"
    n = eng.node(s)
    if n["kind"] not in ("goal", "cycle", "plan", "want"):
        return "pass", "an output / finding: pinning or citing it is fine"
    mine, theirs = eng.task_of(scope["in"]), eng.task_of(s)
    if mine == theirs:
        return "pass", "same task"
    return "fail", (f"{n['kind']} {s} is another task's intent ({eng.node(theirs)['payload']['problem']}); "
                    "pin its outputs or cite its findings instead")
