"""The bitt kernel: one call path over a Record (kernel-contract §5).

    from bitt import Kernel, PostgresRecord
    k = Kernel(PostgresRecord(dsn), packages=[...])
    k.call("control.goal.open_root", {"problem": "..."}, actor="usr")

Tools join through `Package` (§12): their cards, impls, rules, finish handlers and policy runner.
"""
import re
from dataclasses import dataclass, field

from . import cards as lint
from . import names
from .control import (c_act_allowed, c_policy_shape, c_approval, c_can_approve, c_fills, c_goal_drift, c_has_authority,
                      c_human_actor, c_not_root, c_grant_shape, may_act, c_plan_has_eval, plan_confirmed, c_plan_wants, c_same_task, c_task_boundary,
                      c_unique_task_name, generic, i_ack, i_goal, i_open_root)
from .errors import Failed, Refused
from .jobs import i_job_finish
from .record.memory import MemoryRecord
from .hashing import canonical, h as full_hash, normalize, text_hash
from .util import as_list


@dataclass
class Package:
    """A tool package: what it adds to the kernel (§12)."""
    name: str
    cards: list = field(default_factory=list)          # YAML files
    impls: dict = field(default_factory=dict)          # card id → impl(kernel, card, ctx, refs) -> outputs
    rules: dict = field(default_factory=dict)          # rule id → rule(kernel, subject, scope) -> (verdict, detail)
    finish: dict = field(default_factory=dict)         # caller card id → finish(kernel, ctx, caller_event) -> (outputs, emits)
    policy_runner: object = None                       # (kernel, the policy's rule recipe node, card_id, inputs) -> (ok, why)
    listeners: list = field(default_factory=list)      # (kernel, event, outputs): what a committed call sets going (a plan's eval on an arm)
    ack_scope: object = None                           # (kernel, subject) -> more nodes an ack on them covers (a model → the runs it made)
    resolver: object = None                            # (kernel, ref, task, kinds) -> node id or None: names that are not lines (a recipe's label)


KERNEL_IMPLS = {"control.goal.open_root": i_open_root, "control.goal.open": i_goal, "control.ack": i_ack, "exec.job.finish": i_job_finish}
KERNEL_RULES = {
    "control.approval": c_approval, "control.fills": c_fills,
    "control.act_allowed": c_act_allowed, "control.plan_wants": c_plan_wants, "control.human_actor": c_human_actor,
    "control.can_approve": c_can_approve, "control.has_authority": c_has_authority,
    "control.unique_task_name": c_unique_task_name, "control.same_task": c_same_task,
    "control.policy_shape": c_policy_shape, "control.grant_shape": c_grant_shape, "control.plan_has_eval": c_plan_has_eval,
    "control.not_root": c_not_root, "control.goal_drift": c_goal_drift, "control.task_boundary": c_task_boundary,
}
GENERIC_TOOLS = {"base", "control", "exec", "record"}   # the kernel's own cards: one with no impl writes its declared outputs


class Kernel:
    """The one call path (kernel-contract §5) over a Record, with the cards of the kernel and of every registered package."""

    def __init__(self, record=None, packages=(), card_files=None):
        files = list(card_files or lint.default_files())
        for p in packages:
            files += [f for f in p.cards if f not in files]
        cards, roots, errors = lint.load(files)
        if errors:
            raise Failed(f"cards do not lint: {errors[:5]}")
        self.cards, self.roots, self.states = cards, roots, dict(lint.STATES)
        self.story_roles = set(lint.STORY_ROLES)
        self.write_states = list(lint.DEFAULT_OPEN_IN)      # open_in absent = these (base.yaml default_open_in)
        self.version = lint.META["contract_version"]
        self.eff = {cid: lint.effective(cid, cards) for cid in cards}
        self.rec = record if record is not None else MemoryRecord()
        self.rec.bind(self)                                   # the record derives spec_h / task / name with the kernel's cards
        self.impls, self.rules, self.finish = dict(KERNEL_IMPLS), dict(KERNEL_RULES), {}
        self.policy_runner, self.listeners, self.ack_scopes, self.resolvers = None, [], [], []
        for p in packages:                                    # a package's own rules win
            self.impls.update(p.impls)
            self.rules.update(p.rules)
            self.finish.update(p.finish)
            self.policy_runner = p.policy_runner or self.policy_runner
            self.listeners += p.listeners
            self.ack_scopes += [p.ack_scope] if p.ack_scope else []
            self.resolvers += [p.resolver] if p.resolver else []
        missing = [c for c, e in self.eff.items() if e["kind"] == "rule" and c not in self.rules]
        self.unimplemented_rules = missing                  # refused at call time if a requirement reaches one
        self.trace_log = []  # (depth, card, actor, result)
        self.depth = 0
        self.stack = []      # cards currently being called (for internal-card rules)
        self._actors = []    # the actor of each call on the stack (a nested call inherits it)
        self.queue = []      # emitted events waiting for the outer call to commit

    # ---------------------------------------------------------------- refs, ancestry
    def node(self, nid):
        return self.rec.get(nid)

    def kids(self, nid, role=None, kind=None):
        return self.rec.children(nid, role=role, kind=kind)

    def resolve(self, ref, task=None, kinds=None):
        """A hash, a unique ≥8-character prefix, a name (docs/v2/names.md), or what a tool reads (a recipe's label): (node id, the name as
        typed or None)."""
        if isinstance(ref, str) and ref not in self.rec.nodes:
            for r in self.resolvers:
                if hit := r(self, ref, task, kinds):
                    return hit, ref
        return names.resolve(self, ref, task, kinds)

    def ancestors(self, nid):
        chain, cur = [], nid
        while cur:
            cur = self.rec.nodes[cur]["links"].get("in")
            if cur:
                chain.append(cur)
        return chain

    def upstream(self, nid):
        seen, todo = set(), [nid]
        while todo:
            x = todo.pop()
            if x not in seen:
                seen.add(x)
                todo += self.rec.parents(x)
        return seen

    def lineage(self, nid):
        """Build lineage only: what the content was made from (docs/v2/walk.md: every role class but story)."""
        from .walk import Walk
        return Walk(self).up(nid).ids()

    def downstream(self, nid):
        seen, todo = set(), [nid]
        while todo:
            x = todo.pop()
            if x not in seen:
                seen.add(x)
                todo += [n["id"] for n in self.kids(x)]
        return seen - {nid}

    def when(self, expr, scope):
        """`when:` grammar (kernel-contract §4.2): clause ("and" clause)*;
        clause = FIELD given | FIELD == WORD | FIELD in [WORD, ...] | FIELD in SETNAME. No code is ever evaluated."""
        for clause in expr.split(" and "):
            c = clause.strip()
            if m := re.fullmatch(r"(\w+) given", c):
                ok = scope.get(m[1]) is not None
            elif m := re.fullmatch(r"(\w+) == (\w+)", c):
                ok = scope.get(m[1]) == m[2]
            elif m := re.fullmatch(r"(\w+) in \[([\w, ]+)\]", c):
                ok = scope.get(m[1]) in [w.strip() for w in m[2].split(",")]
            elif m := re.fullmatch(r"(\w+) in (\w+)", c):
                ok = scope.get(m[1]) in lint.NAMED_SETS[m[2]]
            elif m := re.fullmatch(r"(\w+) is (\w+)", c):          # v2: the node the field names is of that kind
                v = scope.get(m[1])
                ok = isinstance(v, str) and v in self.rec.nodes and lint.kind_matches(m[2], self.node(v)["kind"])
            else:
                raise Failed(f"`when:` clause {c!r} is not in the grammar")
            if not ok:
                return False
        return True

    # ---------------------------------------------------------------- derived states
    def state(self, nid):
        """Artifact-level state, used by `state:` on refs (state-required)."""
        n = self.node(nid)
        if n["kind"] in ("goal", "cycle"):
            return "closed" if self.cstate(nid) in ("CLOSED", "EARLYSTOPPED") else "open"
        if n["kind"] == "want":
            return "filled" if self.kids(nid, role="fills") else "open"
        return n["payload"].get("state")

    def outcomes(self, nid):
        return [o["payload"]["outcome"] for o in self.kids(nid, role="in", kind="outcome")]

    def latest_plan(self, cyc):
        outs = self.kids(cyc, role="in", kind="outcome")
        since = max([o["seq"] for o in outs if o["payload"]["outcome"] == "iterate"], default=-1)
        plans = [p for p in self.kids(cyc, role="in", kind="plan") if p["seq"] > since]
        return plans[-1] if plans else None

    def cstate(self, nid):
        """Cycle-level state (state-locked verbs). Derived from outcome / plan / fill / score / finding nodes."""
        n = self.node(nid)
        outs = self.outcomes(nid)
        if any(o in ("close", "abandon") for o in outs):
            return "CLOSED"
        if any(o in ("close", "abandon") for a in self.ancestors(nid) for o in self.outcomes(a)):
            return "CLOSED"                 # a closed / abandoned goal closes every cycle under it
        if "earlystop" in outs:
            return "EARLYSTOPPED"
        if n["kind"] == "goal":
            return "GOAL"
        pr = [o for o in outs if o in ("park", "resume")]
        if pr and pr[-1] == "park":
            return "PARKED"
        if n["payload"]["level"] == "explore":
            return "EXPLORE"
        plan = self.latest_plan(nid)
        if not plan:
            return "FRAME"
        if any(self.arm_state(a, plan) != "measured" for a in as_list(plan["links"].get("arms"))):
            return "WORK"
        newest = max([plan["seq"]] + [self.arm_measure(a, plan)[1] or 0 for a in as_list(plan["links"].get("arms"))])
        conclusions = [f for f in self.kids(nid, role="in", kind="finding")
                       if f["payload"].get("finding_kind") == "conclusion" and f["seq"] > newest]
        return "ACT" if conclusions else "JUDGE"

    def fill_of(self, arm):
        n = self.node(arm)
        if n["kind"] != "want":
            return arm
        fills = [f for f in self.kids(arm, role="fills") if f["kind"] not in ("event", "ruling", "warning") and not self._no_fill(f)]
        return fills[-1]["id"] if fills else None

    def _no_fill(self, n):
        """A smoke run proves the wiring, a failed run made nothing, and a train run's fill is the model it lands: none fills an arm."""
        if n["kind"] != "run":
            return False
        e = self.rec.get_row("bitt.run_end", (n["id"],))
        return n["payload"].get("kind") == "train" or bool(n["payload"].get("smoke")) or bool(e and e["status"] == "failed")

    def jobs_for(self, arm):
        return [j for j in self.rec.find("job") if self.node(j["links"]["caller_event"])["links"].get("fills") == arm]

    def job_status(self, job):
        fin = [x for x in self.kids(job, role="job", kind="event") if x["payload"].get("card") == "exec.job.finish"]   # a sync is no end
        if not fin:
            return "running"
        return fin[-1]["payload"]["args"].get("status", "done")      # done | failed | rejected

    def running_job(self, arm):
        for j in self.jobs_for(arm):
            if self.job_status(j["id"]) == "running":
                return j["id"]
        return None

    def arm_state(self, arm, plan):
        return self.arm_measure(arm, plan)[0]

    def _latest_validation(self, fill, task):
        """The latest verdict on `fill` in `task` decides (as for approvals): measured iff it is pass / approve. The measurement time
        is the FIRST pass / approve of the trailing run, so later approvals (e.g. for a version) do not re-measure the arm."""
        vs = [v for v in self.kids(fill, role="subject", kind="validation") if self.task_of(v["id"]) == task
              and not (v["payload"]["verdict"] == "pass" and not v["stamp"]["actor"].startswith("usr")
                       and not may_act(self, v["links"]["in"], v["stamp"]["actor"], "validate_pass", at=v["seq"]))]   # an ungranted agent's pass counts as nothing
        run = []
        for v in reversed(vs):
            if v["payload"]["verdict"] not in ("pass", "approve"):
                break
            run.append(v)
        return run[-1] if run else None

    def plan_confirmed(self, plan):
        return plan_confirmed(self, plan)

    def arm_measure(self, arm, plan):
        """(state, seq of the node that measured it). A measurement must belong to the arm's current fill. Nothing is measured under
        a plan no person has confirmed (an agent's plan is a proposal: kernel.md §7)."""
        if not plan_confirmed(self, plan):
            return ("filled" if self.fill_of(arm) else "wanted"), None
        fill = self.fill_of(arm)
        if self.running_job(arm):
            return "running", None              # more is landing for this arm: it is not judged until every job is in
        if not fill:
            jobs = self.jobs_for(arm)
            return ("failed" if jobs and self.job_status(jobs[-1]["id"]) in ("failed", "rejected") else "wanted"), None
        task = self.task_of(plan["id"])
        pipe = plan["links"].get("pipeline")                  # the plan's eval: its decision on the fill measures it; else a validation
        if pipe and self.node(fill)["kind"] in ("run", "recipe", "artifact", "module"):
            def about(d):                                     # on the fill, or on a run of it (a recipe arm is judged by its runs)
                return any(x == fill or (self.node(x)["kind"] == "run" and self.node(x)["links"].get("recipe") == fill)
                           for x in as_list(d["links"].get("subject")))
            ds = [d for d in self.rec.find("decision") if d["seq"] > plan["seq"] and d["payload"].get("final")
                  and about(d) and d["links"].get("eval") == pipe]
            return ("measured", ds[0]["seq"]) if ds else ("filled", None)
        v = self._latest_validation(fill, task)
        return ("measured", v["seq"]) if v else ("filled", None)

    def open_verbs(self, st):
        return sorted(cid for cid, e in self.eff.items() if e["kind"] == "maneuver"
                      and st in (e.get("open_in") or self.write_states) and st != "CLOSED")

    # ---------------------------------------------------------------- the one call path
    def call(self, cid, args, actor, caller=None):
        e = self.eff.get(cid)
        if e is None:
            raise Refused(f"no card {cid!r}")
        parent = self.stack[-1] if self.stack else None
        outer = self.depth == 0             # nested calls (export, job, generate) join the outer call's proposal
        if not outer:
            # a nested call's actor and DAG caller come from the kernel's own stack, never from what an impl passes (§3, §4.1)
            actor = "system" if cid == "exec.job.finish" else self._actors[-1]
            caller = self.eff[parent]["tool"]
        if caller and lint.DAG.index(e["tool"]) < lint.DAG.index(caller):
            raise Failed(f"{caller} → {e['tool']} ({cid}) goes against the DAG")
        self.depth += 1
        self.stack.append(cid)
        self._actors.append(actor)
        pmark, qmark = len(self.rec.proposal), len(self.queue)
        try:
            if e["kind"] not in ("maneuver", "internal"):
                raise Refused(f"{cid} is a {e['kind']} card, not callable")
            if e["kind"] == "internal":
                if cid == "exec.job.finish" and actor != "system":
                    raise Refused("exec.job.finish is Exec's report: actor must be `system`")
                if cid != "exec.job.finish" and (not parent or cid not in self.eff[parent].get("calls", [])):
                    raise Refused(f"{cid} is internal: only a card that lists it in `calls` may call it (called from {parent})")
            if not re.fullmatch(r"usr(:[\w.-]+)?|agent:[\w.-]+|system|pipeline:\w+|policy:\w+", actor):
                raise Refused(f"actor {actor!r} is not one of usr[:name] · agent:<name> · system · pipeline:<plan> · policy:<id>")
            self._policies(cid, args)
            ctx, refs = self._check_in(cid, e, {**args, "actor": actor} if "actor" in lint.fields(e, "in", "min") else args)
            if e.get("kind_of"):                  # the module kind of that input: `kind` in `when:`, and the state lock by kind
                ctx["kind"] = self.kind_of(ctx.get(e["kind_of"]))
            self._state_lock(cid, e, ctx)
            stamp = {"tool": e["tool"], "card": cid, "contract": self.version, "actor": actor}
            ctx["_stamp"] = stamp
            ctx["_event"] = self.rec.put("event", {"card": cid, "args": self._payload(ctx, refs), "via": ctx["_via"]},
                                         dict(refs), stamp, root=cid in self.roots)
            ctx["_emit"] = [(ev, ctx.get("in"), cid) for ev in e.get("emits", [])]
            marks = self._requires(cid, e, ctx, {}, phase="pre")      # judged on the state *before* this call
            out = self._impl(cid, e)(self, e, ctx, refs)
            self._check_outputs(cid, e, ctx, out, pmark)
            said = [self.node(x)["payload"].get("detail") for x in self.rec.proposal[pmark:]
                    if self.node(x)["kind"] == "warning" and self.node(x)["links"].get("event") == ctx["_event"]]
            if said:                              # warnings an impl wrote: the caller sees them like the rules' own
                out.setdefault("warnings", []).extend(d for d in said if d)
            out.update(event=ctx["_event"], stamp=stamp)
            marks += self._requires(cid, e, ctx, out, phase="post")   # judged on the proposal
            missing = [k for k in lint.fields(e, "out", "min") if out.get(k) is None]
            if missing:
                raise Failed(f"{cid}: MIN out missing {missing}")
            self._write_marks(ctx, out, marks)
        except Exception as x:                   # anything an impl raises: Refused stays Refused, the rest becomes Failed
            if not isinstance(x, (Refused, Failed)):
                orig, x = x, Failed(f"{cid}: {type(x).__name__}: {x}")
                x.__cause__ = orig
            self.trace_log.append((self.depth, cid, actor, f"{type(x).__name__}: {x}"))
            self.depth -= 1
            self.stack.pop()
            self._actors.pop()
            self.rec.drop_since(pmark)          # this call's part of the proposal is never written (outer or nested)
            self.queue = self.queue[:qmark]     # and only its own emitted events go with it
            if cid == "exec.job.finish" and args.get("status") not in ("failed", "rejected") \
                    and (getattr(x, "deferred", False) or isinstance(x, Failed)):
                # the job is over either way: a refused landing → `rejected`; a broken finish handler → `failed` (never stuck running)
                return self.call("exec.job.finish", {"job": args["job"], "outputs": [],
                                                     "status": "rejected" if getattr(x, "deferred", False) else "failed",
                                                     "reason": str(x)[:500]}, actor="system", caller=caller)
            if outer:
                self.rec.drop_proposal()
                self._record_refusal(cid, args, actor, x)
            raise x
        self.trace_log.append((self.depth, cid, actor, "ok"))
        self.queue += [(ev, in_, origin, out, getattr(self, "_chain", ())) for ev, in_, origin in ctx["_emit"]]
        self.depth -= 1
        self.stack.pop()
        self._actors.pop()
        if outer:
            try:
                self.rec.commit()
            except Exception as x:              # the store refused the commit: nothing is half-written, the kernel stays usable
                self.rec.drop_proposal()
                self.queue = self.queue[:qmark]
                failed = Failed(f"{cid}: the store refused the commit: {type(x).__name__}: {str(x)[:300]}")
                self._record_refusal(cid, args, actor, failed)
                raise failed from x
            self._drain()
        return out

    def _check_outputs(self, cid, e, ctx, out, pmark):
        """Every `ref_out` MIN output must be a node this call created, of the declared kind (§12.2)."""
        new = set(self.rec.proposal[pmark:])
        for k, f in lint.fields(e, "out", "min").items():
            if k == "event" or not isinstance(f, dict) or "ref_out" not in f or out.get(k) is None:
                continue
            v = out[k]
            if v not in new:
                raise Failed(f"{cid}: output `{k}` is not a node this call created")
            kinds = as_list(f["ref_out"])
            if not any(lint.kind_matches(w, self.node(v)["kind"]) for w in kinds):
                raise Failed(f"{cid}: output `{k}` is a {self.node(v)['kind']}, the card declares {kinds}")

    def _record_refusal(self, cid, args, actor, x):
        try:
            safe = normalize({k: v for k, v in args.items() if not k.startswith("_")})
        except ValueError:
            safe = {k: repr(v)[:200] for k, v in args.items() if not k.startswith("_")}   # the args themselves were unstorable
        entry = {"card": cid, "actor": actor, "reason": f"{type(x).__name__}: {x}"[:2000], "args": safe}
        try:
            up = self.resolve(args["in"])[0] if args.get("in") else None
        except Refused:
            up = None
        try:
            if up:
                self.rec.put("refusal", entry, {"in": up}, {"tool": "base", "card": cid, "contract": self.version, "actor": actor})
                self.rec.commit()
            else:
                self.rec.log_refusal(entry)
        except Exception as e:                  # the store refuses this write too (a lost connection, another writer): keep the
            self.rec.drop_proposal()            # caller's error, never this one; the refusal stays in memory only
            self.rec.refusals.append({**entry, "unrecorded": f"{type(e).__name__}: {str(e)[:200]}"})

    # ---------------------------------------------------------------- steps of the call path
    def _check_in(self, cid, e, args):
        mins, opts = lint.fields(e, "in", "min"), lint.fields(e, "in", "opt")
        for k in args:
            if k not in mins and k not in opts and not k.startswith("_"):
                raise Refused(f"{cid}: input `{k}` is not in the contract")
        for k in mins:
            if args.get(k) is None:
                raise Refused(f"{cid}: missing MIN in `{k}`")
        ctx, refs, via = {}, {}, {}
        task = None
        if isinstance(args.get("in"), str):
            try:
                task = self.task_of(self.resolve(args["in"])[0])
            except Refused:
                pass
        for k, spec in {**mins, **opts}.items():
            v = args.get(k)
            ctx[k] = None
            if v is None:
                continue
            if "ref_map" in spec:                  # {role: ref}: each resolved; links hold the ids (by role order), the payload the map
                if not isinstance(v, dict) or not all(isinstance(r, str) for r in v):
                    raise Refused(f"{cid}.{k}: takes {{role: ref}}")
                got = {}
                for role, r in sorted(v.items()):
                    names.check(role, f"{cid}.{k} role")
                    nid, _ = self.resolve(r, task, as_list(spec["ref_map"]))
                    if not any(lint.kind_matches(w, self.node(nid)["kind"]) for w in as_list(spec["ref_map"])):
                        raise Refused(f"{cid}.{k}.{role}: a `{self.node(nid)['kind']}` is not one of {spec['ref_map']}")
                    got[role] = nid
                ctx[k], refs[k] = got, list(got.values())
                continue
            if "ref" in spec or spec.get("type") == "ref" or "or_ref" in spec:
                kinds = as_list(spec.get("ref")) + as_list(spec.get("or_ref"))
                if "or_ref" in spec and not (isinstance(v, str) and (v in self.rec.nodes or names.REF.fullmatch(v))):
                    ctx[k] = v                     # the plain-value branch (e.g. scorer code)
                    continue
                if isinstance(v, list) and not spec.get("many"):
                    raise Refused(f"{cid}.{k}: takes one ref, got a list")
                hs = []
                for r in as_list(v):
                    nid, alias = self.resolve(r, task, kinds)
                    if alias:
                        via[k] = alias
                    kind = self.node(nid)["kind"]
                    if kinds and not any(lint.kind_matches(w, kind) for w in kinds):
                        raise Refused(f"{cid}.{k}: a `{kind}` is not one of {kinds}")
                    if spec.get("state") and k != "in" and self.state(nid) not in spec["state"]:   # `in` → _state_lock
                        raise Refused(f"{cid}.{k}: {kind} is `{self.state(nid)}`, needs {spec['state']}")
                    hs.append(nid)
                if spec.get("many") and len(hs) < spec.get("min", 0):
                    raise Refused(f"{cid}.{k}: needs ≥{spec['min']}")
                ctx[k] = refs[k] = hs if spec.get("many") else hs[0]
            else:
                if spec.get("type") == "name":
                    names.check(v, f"{cid}.{k}")         # a name: checked here, never stored in a node body (names.md §1)
                if spec.get("type") == "enum" and v not in spec["values"]:
                    raise Refused(f"{cid}.{k}: {v!r} not in {spec['values']}")
                if spec.get("pattern") and not re.fullmatch(spec["pattern"], str(v)):
                    raise Refused(f"{cid}.{k}: {v!r} does not match {spec['pattern']}")
                ctx[k] = v
        for k, spec in {**mins, **opts}.items():
            if spec.get("required_when") and ctx.get(k) is None and self.when(spec["required_when"], ctx):
                flag = f"--{k.replace('_', '-')}"
                kinds = as_list(spec.get("ref"))              # a ref takes an id, never text
                how = (f"{flag} <the id of a {' / '.join(kinds)}>" + (": a finding is `bitt note \"…\" --evidence <a run>`"
                       if "finding" in kinds else "") if kinds else f"{flag} \"…\"")
                raise Refused(f"{cid}: `{k}` is required when {spec['required_when']}. next: give `{k}` too (on the command line: {how})")
        for k, spec in {**mins, **opts}.items():         # `as: <role>`: an input stored under another (context) role, e.g. a load's
            if spec.get("as") and k in refs:               # `in` kept as `during`: a hint that sets no task and no state lock
                ctx[spec["as"]], refs[spec["as"]] = ctx.pop(k), refs.pop(k)
                ctx[k] = None
        bad = [k for k in args if k.startswith("_") and k != "_fake"]
        if bad:
            raise Refused(f"{cid}: inputs starting with `_` are reserved ({bad}); `_fake` is the test scaffolding")
        ctx.update({k: v for k, v in args.items() if k.startswith("_")})
        ctx["_via"] = via                   # aliases are stored "via alias"; links hold hashes only
        return ctx, refs

    def _state_lock(self, cid, e, ctx):
        if not ctx.get("in"):
            return                          # roots and internal cards carry no intent of their own
        if cid in self.stack[:-1]:
            return                          # a step of the same act already running (a pipeline's runs): its lock covers it
        st = self.cstate(ctx["in"])
        allowed = (e.get("open_in_by_kind") or {}).get(ctx.get("kind")) or e.get("open_in") or self.write_states
        if st in ("CLOSED", "EARLYSTOPPED") or st not in allowed:
            nxt = self.states.get(st, {}).get("exit", "")
            raise Refused(f"{cid} is locked in {st} (open in {allowed}). next: {nxt}. "
                          f"open here: {', '.join(v for v in self.open_verbs(st) if v.split('.')[0] in ('data', 'recipe', 'run', 'tag'))}")

    def kind_of(self, nid):
        """The module kind of a recipe or a module (derive, check, generate, train, pipeline, load), or None."""
        n = self.node(nid) if nid else None
        if n and n["kind"] == "recipe":
            n = self.node(n["links"]["module"])
        return n["payload"]["header"]["kind"] if n and n["kind"] == "module" else None

    def _is_post(self, e, r):
        """Requirements are judged on the proposal (safe: a refusal drops it). Only rules that read the state *before*
        this call (`reads: before`, e.g. act_allowed) run ahead of the impl."""
        return self.cards[r["rule"]].get("reads") != "before"

    def _requires(self, cid, e, ctx, out, phase):
        scope = {**ctx, **out, "_main": self._main(e, out)}
        marks = []
        for r in e.get("requires", []):
            if r.get("subject") == "every ref" or r.get("on_fail") == "skip" or r.get("deferred"):
                continue                            # resolve ran in _check_in; deferred → job.finish
            if self._is_post(e, r) != (phase == "post"):
                continue
            if "when" in r and not self.when(r["when"], scope):
                continue
            if r["subject"] == "every input":
                subjects = self._inputs(ctx)
            elif r["subject"] == "every ref input":
                subjects = [x for k, v in ctx.items() if k != "in" and not k.startswith("_") and k in self._refkeys(ctx)
                            for x in (list(v.values()) if isinstance(v, dict) else as_list(v)) if x in self.rec.nodes]
            else:
                subjects = self._subjects(r["subject"], scope)
            for subj in subjects:
                verdict, detail, chk = self.run_rule(r["rule"], subj, {**scope, "_req": r})
                if verdict == "pass":
                    continue
                effect = r.get("on_unknown", r["on_fail"]) if verdict == "unknown" else r["on_fail"]
                if effect == "skip":
                    continue
                if effect == "refuse" and r.get("if_acked"):
                    if self._acked(subj, r["rule"], task=self.task_of(ctx["in"]) if ctx.get("in") else None):
                        effect = r["if_acked"] + "+acked"
                    else:
                        raise Refused(f"{cid}: {r['rule']} → {verdict} ({detail}). next: `control.ack` the subject with rule={r['rule']} to proceed anyway (the result will be marked {r['if_acked']}), or drop it")
                if effect == "refuse":
                    raise Refused(f"{cid}: {r['rule']} → {verdict} ({detail})" + self.next_of(r["rule"], detail))
                marks.append((effect, r["rule"], verdict, detail, chk, subj))
        return marks

    def next_of(self, rule, detail=""):
        """`. next: …` of a rule card (what to do when it fails), unless the rule's own detail already says it."""
        nx = (self.eff.get(rule) or {}).get("next")
        return f". next: {nx}" if nx and "next:" not in str(detail) else ""

    def _acked(self, subj, rule, task=None):
        """An ack counts when it names this rule, (if it names `against`) the other pair member, and was made in `task`
        (judgments are task-local: another task's ack never opens this task's gate)."""
        members = [s for s in (subj if isinstance(subj, tuple) else (subj,)) if s in self.rec.nodes]
        members += [m for s in list(members) for scope in self.ack_scopes for m in scope(self, s)]   # e.g. a model → its runs
        for s in members:
            for a in self.kids(s, role="subject", kind="ack"):
                if a["payload"].get("rule") == rule and a["links"].get("against") in (None, *members) \
                        and (task is None or self.task_of(a["id"]) == task):
                    return True
        return False

    def _write_marks(self, ctx, out, marks):
        """flag / warning nodes, written once the main output exists (they point at it)."""
        main = self._main(self.eff[ctx["_stamp"]["card"]], out)
        for effect, rule, verdict, detail, chk, subj in marks:
            acked = effect.endswith("+acked")
            effect = effect.removesuffix("+acked")
            kind = {"mark_invalid": "flag", "warn": "warning"}[effect]
            target = (list(subj) if isinstance(subj, tuple) else subj) if effect == "warn" else main
            nx = self.next_of(rule, detail).removeprefix(". next: ") or None
            self.rec.put(kind, {"rule": rule, "verdict": verdict, "detail": detail, "effect": effect, "acked": acked, "next": nx},
                         {"in": ctx.get("in"), "subject": target, "ruling": chk, "event": ctx["_event"]}, ctx["_stamp"])
            if effect == "warn":
                out.setdefault("warnings", []).append(detail + (f" (next: {nx})" if nx else ""))

    def _refkeys(self, ctx):
        e = self.eff[ctx["_stamp"]["card"]]
        return {k for k, s in {**lint.fields(e, "in", "min"), **lint.fields(e, "in", "opt")}.items()
                if isinstance(s, dict) and ("ref" in s or "or_ref" in s or "ref_map" in s or s.get("type") == "ref")}

    def task_of(self, nid):
        chain = [nid] + self.ancestors(nid)
        roots = [x for x in chain if self.rec.nodes[x]["kind"] == "goal" and not self.rec.nodes[x]["links"].get("in")]
        return roots[-1] if roots else None

    def _inputs(self, ctx):
        """`every input` = each ref input except intent / reason links (citing an old node as `because` is fine)."""
        skip = lint.STORY_ROLES            # `every input` = ref inputs whose role is lineage (never a hidden list)
        e = self.eff[ctx["_stamp"]["card"]]
        refkeys = [k for k, s in {**lint.fields(e, "in", "min"), **lint.fields(e, "in", "opt")}.items()
                   if isinstance(s, dict) and ("ref" in s or "or_ref" in s or "ref_map" in s or s.get("type") == "ref") and k not in skip]
        vals = lambda v: list(v.values()) if isinstance(v, dict) else as_list(v)  # noqa: E731
        return [x for k in refkeys for x in vals(ctx.get(k)) if x in self.rec.nodes]

    def _subjects(self, expr, scope):
        if "×" in expr:
            a, b = (x.strip() for x in expr.split("×"))
            return [(x, y) for x in self._subjects(a, scope) for y in self._subjects(b, scope)]
        if "," in expr:
            return [tuple(self._subjects(p.strip(), scope)[0] for p in expr.split(","))]
        m = re.fullmatch(r"([\w.]+)(?:\[(.+)\])?", expr)
        path, sel = m[1].split("."), m[2]
        v = scope.get(path[0])
        for p in path[1:]:
            v = self.node(v)["links"].get(p) if v else None
        if sel is None:
            if v is None and len(path) > 1:
                return []                   # a dotted path to a link the node doesn't have = no subjects
            return v if isinstance(v, list) else [v]
        items = as_list(v)
        if sel == "*":
            return items
        if sel.startswith("claims has "):
            c = sel.split()[-1]
            return [i for i in items if c in (self.node(i)["payload"].get("claims") or [])]
        return [i for i in items if self.node(i)["payload"].get(sel)]

    def run_rule(self, rule_id, subj, scope):
        card = self.cards[rule_id]
        key = full_hash("ruling", canonical([rule_id, subj]))
        if card.get("cache", "subject") != "never":
            hit = [n for n in self.rec.find("ruling") if n["payload"]["key"] == key]
            if hit:
                n = hit[-1]
                return n["payload"]["verdict"], n["payload"]["detail"], n["id"]
        if rule_id not in self.rules:
            raise Refused(f"rule {rule_id} has no implementation registered (a tool package must provide it)")
        verdict, detail = self.rules[rule_id](self, subj, scope)
        if verdict == "pass" and card.get("cache", "subject") == "never":
            return verdict, detail, None    # an uncached pass is reused by nobody: no node (only failures / cached results are kept)
        subj_ids = [s for s in (subj if isinstance(subj, tuple) else (subj,)) if s in self.rec.nodes]
        chk = self.rec.put("ruling", {"rule": rule_id, "verdict": verdict, "detail": detail, "key": key},
                           {"subject": subj_ids, "event": scope["_event"]},
                           {**scope["_stamp"], "tool": card["tool"], "card": rule_id})
        return verdict, detail, chk

    def _policies(self, cid, args):
        if "in" not in args:
            return
        try:
            line = [self.resolve(args["in"])[0]]
        except Refused:
            return
        line += self.ancestors(line[0])
        e = self.eff[cid]
        ns = {k: None for k in {**lint.fields(e, "in", "min"), **lint.fields(e, "in", "opt")}} | args
        for p in self.live_policies():
            pl = p["payload"]
            if pl["on_event"] == cid and p["links"]["in"] in line and p["links"].get("rule"):
                g = self.node(p["links"]["rule"])
                if self.policy_runner is None:
                    raise Refused(f"policy {p['id']} has a rule but no policy runner is registered (a tool package provides it)")
                ok, why = self.policy_runner(self, g, cid, ns)     # runs the task-written rule on the call's inputs
                if not ok:
                    raise Refused(f"policy {p['id']} rule {g['payload'].get('impl')!r} refused {cid}: {why}")

    def live_policies(self):
        return [p for p in self.rec.find("policy") if not self.kids(p["id"], role="policy", kind="policy_retired")]

    def _drain(self):
        """What a committed call sets going (a listener of a tool package: a plan's eval on the arm a run filled). Policies are rules
        only: "after X do Y" is a pipeline, never a trigger."""
        while self.queue:
            ev, in_, origin, out, chain = self.queue.pop(0)
            for listen in self.listeners:
                listen(self, ev, out)

    # ---------------------------------------------------------------- impl helpers
    def _impl(self, cid, e):
        for c in [cid] + list(reversed(e.get("_chain", []))):
            if c in self.impls:
                return self.impls[c]
        if e.get("tool") in GENERIC_TOOLS:
            return generic
        raise Refused(f"{cid}: no tool implements this card (the {e.get('tool')} tool)")

    def _payload(self, ctx, refs):
        """Non-ref inputs as stored on nodes. A `type: bytes` input is external content: stored as its hash, never inline (§2.2)."""
        e = self.eff.get((ctx.get("_stamp") or {}).get("card"), {})
        spec = {**lint.fields(e, "in", "min"), **lint.fields(e, "in", "opt")} if e else {}
        out = {}
        for k, v in ctx.items():
            if isinstance(spec.get(k), dict) and "ref_map" in spec[k] and v:
                out[k] = v                     # {role: id}: which slot each linked node fills
                continue
            if k in refs or v is None or (k.startswith("_") and k != "_fake") or (isinstance(spec.get(k), dict) and spec[k].get("type") == "name"):
                continue                       # names live in the registry (names.py), never in a node body
            if isinstance(spec.get(k), dict) and spec[k].get("type") == "bytes":
                v = {"bytes_h": text_hash(v if isinstance(v, (str, bytes)) else canonical(v).decode()), "n": len(v)}   # a file: its own bytes
            out[k] = v
        return out

    def _main(self, e, out):
        for k, f in lint.fields(e, "out", "min").items():
            if k != "event" and isinstance(f, dict) and "ref_out" in f:
                return out.get(k)

    def make(self, kind, ctx, refs, **payload):
        extra = payload.pop("_links", {})
        bad = [r for r in extra if r not in lint.IMPL_ROLES]
        if bad:
            raise Failed(f"{ctx['_stamp']['card']}: an impl may add only impl roles {sorted(lint.IMPL_ROLES)}, not {bad}")
        links = {"event": ctx["_event"], **refs, **extra}
        return self.rec.put(kind, {**self._payload(ctx, refs), **payload}, links, ctx["_stamp"])

    def goal_of(self, nid):
        """The goal version a node was framed under: the first goal on its `in` chain (itself if it is a goal)."""
        for x in [nid] + self.ancestors(nid):
            if self.rec.nodes[x]["kind"] == "goal":
                return x
        return None

    def current_goal(self, g):
        """[g, ..., a current version]: follows the latest superseder (status display)."""
        chain = [g]
        while True:
            nxt = [n for n in self.kids(chain[-1], role="supersedes", kind="goal")]
            if not nxt:
                return chain
            chain.append(nxt[-1]["id"])

    def goal_descendants(self, g):
        """Every goal that supersedes g, directly or not, on every branch (a split has several)."""
        seen, todo = [], [g]
        while todo:
            for n in self.kids(todo.pop(), role="supersedes", kind="goal"):
                if n["id"] not in seen:
                    seen.append(n["id"])
                    todo.append(n["id"])
        return seen

Engine = Kernel   # the walking want's name
