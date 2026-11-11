"""The artifact tool (spec/cards/artifact.yaml): content used whole, on the shelf (foundation.md §B). A prompt's contract is read from
its file (tools/prompts.py): needs (its slots) → gives (its fields); other content has none. A model file is an artifact a train run
makes (run.yaml), never one added here by hand unless it came from outside.

A model made by a train is never in bitt's store: its node holds its files (path, size, sha256) and where it was written (`at`: an env
and a folder there). Where it is now: that place, plus each `copy` (artifact.copy), minus each `removal` (artifact.remove, a person's).
A removed model keeps its record; its files cannot be restored."""
import hashlib
import tempfile
from pathlib import Path

from .. import blobs, names
from ..errors import Refused
from ..kernel import Package
from . import envs, prompts
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


# ---------------------------------------------------------------- a model's places (where its files sit)
def places(eng, a):
    """[{env, path}] where model a's files are now: where it was written, plus copies, minus removals (in the order they happened)."""
    p = eng.node(a)["payload"]
    if not p.get("at"):
        return []
    now = [{"env": p["at"]["env"], "path": p["at"]["path"]}]
    for k in eng.kids(a, role="target"):
        pl = {"env": k["payload"].get("env"), "path": k["payload"].get("path")}
        if k["kind"] == "copy" and pl not in now:
            now.append(pl)
        elif k["kind"] == "removal":
            now = [x for x in now if x != pl]
    return now


def removed(eng, a):
    """The removals of model a, oldest first."""
    return [k for k in eng.kids(a, role="target", kind="removal")]


def made_from(eng, a):
    """What the record says was made from a (every node downstream of it on a lineage role), a itself left out."""
    from ..walk import Walk
    return [x for x in Walk(eng).down(a) if x != a]


def i_copy(eng, e, ctx, refs):
    """Bring a model's files to another env (its task folders, the same relative folder), hash them there, and record the copy only
    when every file matches. Between two remote envs the files pass through this machine."""
    a, dest = ctx["target"], envs.get(ctx["to"])
    p = eng.node(a)["payload"]
    src_pl = sorted(places(eng, a), key=lambda x: x["env"] != "local")[0]
    src = envs.get(src_pl["env"])
    rel = p["at"]["rel"]
    path = f"{dest.tasks_root().rstrip('/')}/{rel}"
    if src.name == "local":
        dest.receive(Path(src_pl["path"]).expanduser(), path)
    elif dest.name == "local":
        src.send(src_pl["path"], Path(path).expanduser())
    else:
        with tempfile.TemporaryDirectory() as tmp:
            src.send(src_pl["path"], Path(tmp) / "m")
            dest.receive(Path(tmp) / "m", path)
    got = dest.manifest(path)
    if got != p["files"]:
        dest.remove(path)
        raise Refused(f"artifact.copy: the files at {dest.name}:{path} do not hash to the model's (copy removed); try again")
    return {"copy": eng.make("copy", ctx, refs, env=dest.name, path=path)}


def i_remove(eng, e, ctx, refs):
    """Delete a model's files in one env; the model's record stays, with this removal on it."""
    a = ctx["target"]
    pl = next(x for x in places(eng, a) if x["env"] == ctx["env"])
    env = envs.get(ctx["env"])
    if env.has(pl["path"]):
        env.remove(pl["path"])
    return {"removal": eng.make("removal", ctx, refs, path=pl["path"])}


def c_is_model(eng, s, scope):
    n = eng.node(s)
    if n["kind"] != "artifact" or not n["payload"].get("at"):
        return "fail", f"{names.label(eng, s) or s[:12]} is not a model a train wrote (only those have files bitt tracks in place)"
    return "pass", "a model with files in place"


def c_on_env(eng, s, scope):
    here = [x for x in places(eng, s) if x["env"] == scope["env"]]
    if not here:
        return "fail", f"it has no files on env {scope['env']!r} (it is on {sorted({x['env'] for x in places(eng, s)}) or 'no env: removed'})"
    return "pass", f"on {scope['env']}: {here[0]['path']}"


def c_not_on_env(eng, s, scope):
    pl = places(eng, s)
    if not pl:
        return "fail", "it was removed everywhere: nothing to copy from"
    if any(x["env"] == scope["to"] for x in pl):
        return "fail", f"it is already on env {scope['to']!r}"
    return "pass", f"from {pl[0]['env']}"


def c_by_person(eng, s, scope):
    actor = scope["_stamp"]["actor"]
    if not actor.startswith("usr"):
        return "fail", f"removing a model's files is a person's call, not {actor}'s"
    return "pass", actor


def c_nothing_made_from(eng, s, scope):
    down = made_from(eng, s)
    if down:
        kinds = {}
        for x in down:
            kinds[eng.node(x)["kind"]] = kinds.get(eng.node(x)["kind"], 0) + 1
        return "fail", (f"the record holds {len(down)} things made from it ({', '.join(f'{v} {k}' for k, v in sorted(kinds.items()))}); "
                        "they stay recorded, but nothing can be rerun from these files")
    return "pass", "nothing recorded was made from it"


def package():
    return Package(name="artifact", cards=[CARDS / "artifact.yaml"],
                   impls={"artifact.add": i_add, "artifact.copy": i_copy, "artifact.remove": i_remove},
                   rules={"artifact.parses": c_parses, "artifact.is_model": c_is_model, "artifact.on_env": c_on_env,
                          "artifact.not_on_env": c_not_on_env, "artifact.by_person": c_by_person,
                          "artifact.nothing_made_from": c_nothing_made_from})
