"""exec.job.finish (§8.7): finish handlers are registered by the caller's tool; deferred requirements run on what lands."""
from .errors import Refused


def i_job_finish(eng, e, ctx, refs):
    """Exec reports a job. `done` → the caller tool's finish handler writes the deferred outputs; the caller card's `deferred`
    requires run on them."""
    if [x for x in eng.kids(ctx["job"], role="job", kind="event") if x["id"] != ctx["_event"]
            and x["payload"].get("card") == "exec.job.finish"]:              # only a finish ends a job (a sync event links it too)
        raise Refused(f"exec.job.finish: job {ctx['job']} already finished")
    caller = eng.node(eng.node(ctx["job"])["links"]["caller_event"])
    ctx["_emit"] = []
    if ctx.get("status") in ("failed", "rejected") or caller["payload"]["card"] not in eng.finish:
        return {}                           # failed: the arm shows `failed`; todo asks to retry or drop it
    out, ctx["_emit"] = eng.finish[caller["payload"]["card"]](eng, ctx, caller)
    main = next(iter(out.values()))
    for r in eng.eff[caller["payload"]["card"]].get("requires", []):
        scope = {**caller["payload"]["args"], **caller["links"]}
        if r.get("deferred") and (r.get("when") is None or eng.when(r["when"], scope)):
            v, detail, _ = eng.run_rule(r["rule"], caller["links"].get(r["subject"]), {**ctx, "_main": main})
            if v != "pass":
                x = Refused(f"exec.job.finish: deferred {r['rule']} of {caller['payload']['card']} → {v} ({detail})")
                x.deferred = True
                raise x
    return out
