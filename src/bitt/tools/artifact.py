"""The artifact tool (spec/cards/artifact.yaml): content used whole, on the shelf (foundation.md §B). A prompt's contract is read from
its file (tools/prompts.py): needs (its slots) → gives (its fields); other content has none. A model file is an artifact a train run
makes (run.yaml), never one added here by hand unless it came from outside."""
import hashlib
from pathlib import Path

from .. import blobs, names
from ..kernel import Package
from . import prompts
from .module import _line

from ..cards import CARDS  # noqa: E402  (a release: inside the package)


def contract(raw, kind, name):
    """(contract, problem): a prompt's needs → gives; any other kind: none."""
    if kind == "prompt":
        return prompts.parse(raw, name)
    return {"needs": [], "gives": {}}, None


def i_add(eng, e, ctx, refs):
    raw = ctx["content"] if isinstance(ctx["content"], bytes) else ctx["content"].encode()
    c, _ = contract(raw, ctx["artifact_kind"], ctx["name"])
    root, parent = _line(eng, ctx, "artifact")
    does = ctx.get("does") or (c or {}).get("does")
    links = {**names.line_link(root), **({"prev": parent["id"]} if parent and not ctx.get("parent") else {})}
    a = eng.make("artifact", ctx, refs, content_blob=blobs.put(raw), contract=c, _links=links, **({"does": does} if does else {}))
    names.settle(eng, ctx, "lib", ctx["name"], a, root)
    return {"artifact": a}


def c_parses(eng, s, scope):
    n = eng.node(s)
    raw = blobs.get(n["payload"]["content_blob"])
    if hashlib.sha256(raw).hexdigest() != n["payload"]["content_blob"]:
        return "fail", "the content no longer hashes to its node"
    c, problem = contract(raw, n["payload"]["artifact_kind"], names.label(eng, s).split("/")[-1])
    if problem and not (n["payload"].get("does") and problem.startswith("a prompt says what it is for")):
        return "fail", problem
    if not n["payload"].get("does"):
        return "fail", "an artifact says what it is for: --does \"<one sentence>\" (a prompt: \"bitt\": {\"does\": …} in the file)"
    return "pass", n["payload"]["does"]


def package():
    return Package(name="artifact", cards=[CARDS / "artifact.yaml"], impls={"artifact.add": i_add}, rules={"artifact.parses": c_parses})
