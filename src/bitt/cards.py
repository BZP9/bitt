"""Cards: load, inherit, lint (kernel-contract §4, §12.1).

ERROR = the cards contradict their own grammar (exit 1).
GAP   = the pieces don't connect yet (a kind nobody produces, etc.).

The loaded card set is module state (one card set per process): STATES, ROLES (+ LINEAGE_ROLES, STORY_ROLES), NAMED_SETS, DEFAULT_OPEN_IN, META.
Run: `bitt lint` (or `uv run python -m bitt.cards`).
"""
import copy
import re
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]          # monorepo root (src/bitt/cards.py → ../..)
# the cards: inside the package in a release (pyproject force-include spec/cards → bitt/cards), spec/cards in a dev tree
CARDS = Path(__file__).resolve().parent / "cards" if (Path(__file__).resolve().parent / "cards").is_dir() else REPO / "spec" / "cards"


def default_files():
    """The contract's cards (spec/cards; docs/v2/kernel.md). A tool package adds its own through `Package.cards`."""
    return sorted(CARDS.glob("*.yaml"))


DAG = ["control", "tag", "run", "recipe", "data", "artifact", "module", "exec", "record"]
DEFAULT_DAG = list(DAG)                              # a card set's base file may set its own (`dag:`)
MULTI_OWNER_OK = {"ruling", "event", "flag", "warning"}
STATES = {}
ROLES = {}           # role class → [roles] (base.yaml `roles`, docs/v2/walk.md §2)
LINEAGE_ROLES = set()
STORY_ROLES = set()
IMPL_ROLES = set()
NAMED_SETS = {}
DEFAULT_OPEN_IN = []
META = {}  # every tool's rules/writes produce these


def load(files=None):
    cards, roots = {}, set()
    errors = []
    for g in (STATES, ROLES, LINEAGE_ROLES, STORY_ROLES, IMPL_ROLES, NAMED_SETS, DEFAULT_OPEN_IN, META):
        g.clear()
    DAG[:] = DEFAULT_DAG
    for f in (files or default_files()):
        f = Path(f)
        doc = yaml.safe_load(f.read_text())
        roots |= set(doc.get("roots", []))
        for klass, rs in (doc.get("roles") or {}).items():
            for r in rs:
                if (was := next((k for k, v in ROLES.items() if r in v), None)) is not None:
                    errors.append(f"role {r} is in two role classes ({was}, {klass}): a role means one thing")
            ROLES.setdefault(klass, []).extend(rs)
        IMPL_ROLES.update(doc.get("impl_roles", []))
        NAMED_SETS.update(doc.get("named_sets", {}))
        DEFAULT_OPEN_IN.extend(doc.get("default_open_in", []))
        if "dag" in doc:
            DAG[:] = doc["dag"]
        if "contract_version" in doc:
            META["contract_version"] = doc["contract_version"]
        if "states" in doc:
            STATES.update(doc["states"])
        for c in doc["cards"]:
            c.setdefault("tool", doc["tool"])
            c["_file"] = str(f.relative_to(REPO)) if f.is_relative_to(REPO) else f.name
            if c["id"] in cards:
                errors.append(f"duplicate id {c['id']}")
            cards[c["id"]] = c
    STORY_ROLES.update(ROLES.get("story", []))
    LINEAGE_ROLES.update(r for k, rs in ROLES.items() if k != "story" for r in rs)
    return cards, roots, errors


def role_class(role):
    """The one class of a link role (docs/v2/walk.md §2), or None."""
    return next((k for k, rs in ROLES.items() if role in rs), None)


WHEN_CLAUSE = re.compile(r"\w+ given|\w+ == \w+|\w+ in \[[\w, ]+\]|\w+ in \w+|\w+ is \w+")   # `x is kind`: the node x names is of that kind (v2)
SUBJECT_PATH = r"\w+(\.\w+)*(\[(\*|\w+|claims has \w+)\])?"


def when_ok(expr):
    """§4.2: clause ( " and " clause )*."""
    return all(WHEN_CLAUSE.fullmatch(c.strip()) for c in str(expr).split(" and "))


def subject_ok(expr):
    """§4.3: every ref | every ref input | every input | path × path | path, path, … | path."""
    if expr in ("every ref", "every ref input", "every input"):
        return True
    parts = [p.strip() for p in (expr.split("×") if "×" in expr else expr.split(","))]
    return 1 <= len(parts) and all(re.fullmatch(SUBJECT_PATH, p) for p in parts)


def merge(base, child):
    out = copy.deepcopy(base)
    for k, v in child.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = merge(out[k], v)
        elif k == "requires":
            out[k] = out.get(k, []) + v
        else:
            out[k] = v
    return out


def effective(cid, cards, seen=()):
    c = cards[cid]
    parent = c.get("extends")
    if not parent:
        return copy.deepcopy(c)
    if parent in seen or parent not in cards:
        return copy.deepcopy(c)
    eff = merge(effective(parent, cards, seen + (cid,)), {k: v for k, v in c.items() if k != "extends"})
    for path in c.get("drop", []):
        node = eff
        *head, last = path.split(".")
        for h in head:
            node = node.get(h, {})
        node.pop(last, None)
    eff["_chain"] = effective(parent, cards).get("_chain", []) + [parent]
    return eff


def fields(eff, side, tier):
    return (eff.get(side, {}) or {}).get(tier, {}) or {}


def as_list(x):
    return x if isinstance(x, list) else [x]


def kind_matches(want, have):
    return want == have or have.startswith(want + ":") or want.startswith(have + ":")


def check(loaded):
    """(errors, gaps, cards, produced) for a loaded card set."""
    cards, roots, errors = loaded
    errors = list(errors)
    gaps = []
    eff = {}
    for cid, c in cards.items():
        if c.get("extends") and c["extends"] not in cards:
            errors.append(f"{cid}: extends unknown {c['extends']}")
        for k, v in c.items():
            if isinstance(k, bool) or isinstance(v, bool) and k not in ("bounded", "nullable"):
                errors.append(f"{cid}: YAML bool trap at {k!r}")
        for side in ("in", "out"):
            for tier in ("min", "opt"):
                if any(isinstance(k, bool) for k in ((c.get(side) or {}).get(tier) or {})):
                    errors.append(f"{cid}: YAML bool trap in {side}.{tier} (quote a field named on / off / yes / no)")
        eff[cid] = effective(cid, cards)

    produced = {}  # kind -> set(tools)
    for cid, e in eff.items():
        for f in list(fields(e, "out", "min").values()) + list(fields(e, "out", "opt").values()):
            if isinstance(f, dict) and "ref_out" in f and "via" not in f:
                for k in as_list(f["ref_out"]):
                    produced.setdefault(k, set()).add(e["tool"])
        if e.get("kind") == "rule":
            produced.setdefault("ruling", set()).add(e["tool"])

    for cid, e in eff.items():
        kind = e.get("kind")
        chain = e.get("_chain", [])
        # root rule
        if kind == "rule" and not e.get("next"):              # every wrong step says how to put it right (scenarios.md E6)
            errors.append(f"{cid}: a rule card declares `next:` (what to do when it fails)")
        if "base.root" in chain and cid not in roots:
            errors.append(f"{cid}: extends base.root but is not listed in roots")
        if kind == "maneuver" and cid not in roots and "base.write" in chain:
            if "in" not in fields(e, "in", "min"):
                errors.append(f"{cid}: write without `in` upstream")
        if kind == "maneuver" and "base.write" not in chain:
            errors.append(f"{cid}: maneuver does not extend base.write")
        if kind == "internal" and not any("ref" in f or f.get("type") == "links" for f in fields(e, "in", "min").values() if isinstance(f, dict)):
            errors.append(f"{cid}: internal card with no upstream ref")
        if kind == "maneuver":
            own = [f for n, f in fields(e, "out", "min").items() if n != "event" and isinstance(f, dict) and "ref_out" in f]
            if not own:
                errors.append(f"{cid}: maneuver has no MIN out node besides its event")
        for st in e.get("open_in", []):
            if st not in STATES:
                errors.append(f"{cid}: open_in names unknown state {st}")
        if e.get("open_in") and kind != "maneuver":
            errors.append(f"{cid}: only maneuvers are state-locked")
        # a card that takes `fills` must cite control.fills (never-dup: the want contract is checked in one place)
        if kind == "maneuver" and "fills" in {**fields(e, "in", "min"), **fields(e, "in", "opt")} \
                and not any(r.get("rule") == "control.fills" for r in e.get("requires", [])):
            errors.append(f"{cid}: takes `fills` but does not cite control.fills")
        # an output field may not shadow an input field (`when:` sees both; found by M3 in control.act)
        clash = (set(fields(e, "in", "min")) | set(fields(e, "in", "opt"))) & (set(fields(e, "out", "min")) - {"event", "stamp"})
        if clash and kind in ("maneuver", "internal"):
            errors.append(f"{cid}: in/out field names clash {sorted(clash)}")
        # requires
        for r in e.get("requires", []):
            target = r.get("rule")
            if target not in cards:
                errors.append(f"{cid}: requires unknown rule {target}")
            elif cards[target]["kind"] != "rule":
                errors.append(f"{cid}: {target} is a {cards[target]['kind']}, required as a rule")
            if r.get("on_fail") not in ("refuse", "mark_invalid", "warn", "skip"):
                errors.append(f"{cid}: requires {target} has bad on_fail {r.get('on_fail')!r}")
            for k in ("if_acked", "on_unknown"):
                if k in r and r[k] not in ("refuse", "mark_invalid", "warn", "skip"):
                    errors.append(f"{cid}: requires {target} has bad {k} {r[k]!r}")
            if "when" in r and not when_ok(r["when"]):
                errors.append(f"{cid}: requires {target}: `when: {r['when']}` is not in the grammar (§4.2)")
            if not subject_ok(r.get("subject", "")):
                errors.append(f"{cid}: requires {target}: subject {r.get('subject')!r} is not in the grammar (§4.3)")
            if r.get("deferred") and "exec.job.submit" not in e.get("calls", []):
                errors.append(f"{cid}: `deferred` needs a card that submits a job (it runs at exec.job.finish)")
            extra = set(r) - {"rule", "subject", "on_fail", "when", "if_acked", "on_unknown", "kind", "deferred"}
            if extra:
                errors.append(f"{cid}: requires {target} has unknown keys {sorted(extra)}")
        for st in e.get("open_in", []):
            if st in ("CLOSED", "EARLYSTOPPED"):
                errors.append(f"{cid}: open_in may not name {st} (nothing is written there)")
        for r in e.get("requires", []):
            for m in re.finditer(r"\w+ in (\w+)$|\w+ in (\w+) and", r.get("when", "")):
                name = m.group(1) or m.group(2)
                if name not in NAMED_SETS:
                    errors.append(f"{cid}: `when:` names unknown set {name!r} (base.yaml named_sets)")
            if r.get("deferred") and r.get("on_fail") != "refuse":
                errors.append(f"{cid}: a deferred requirement must be on_fail: refuse (a landing is accepted or rejected)")
        if kind == "rule" and e.get("cache", "subject") not in ("subject", "never"):
            errors.append(f"{cid}: cache must be `subject` or `never`, not {e.get('cache')!r}")
        if kind == "rule" and e.get("reads") not in (None, "before"):
            errors.append(f"{cid}: reads must be `before` (or absent)")
        for side in ("in",):
            for tier in ("min", "opt"):
                for fname, f in fields(e, side, tier).items():
                    if isinstance(f, dict) and f.get("pattern"):
                        try:
                            re.compile(f["pattern"])
                        except re.error:
                            errors.append(f"{cid}.{fname}: bad pattern")
        # calls follow the DAG
        for t in e.get("calls", []):
            if t not in cards:
                errors.append(f"{cid}: calls unknown {t}")
                continue
            a, b = e["tool"], cards[t]["tool"]
            if a in DAG and b in DAG and DAG.index(b) < DAG.index(a):
                errors.append(f"{cid}: call {a} -> {b} goes against the DAG")
        # every consumed kind is produced somewhere
        for side_tier in (("in", "min"), ("in", "opt")):
            for name, f in fields(e, *side_tier).items():
                if not isinstance(f, dict):
                    continue
                for k in as_list(f.get("ref", [])) + as_list(f.get("or_ref", [])) + as_list(f.get("ref_map", [])):
                    if not any(kind_matches(k, p) for p in produced):
                        gaps.append(f"{cid}.{name}: consumes `{k}`, which no card produces")

    known = {r for rs in ROLES.values() for r in rs}            # every role a card or an impl can write has one class
    for cid, e in eff.items():
        for side_tier in (("in", "min"), ("in", "opt")):
            for name, f in fields(e, *side_tier).items():
                if isinstance(f, dict) and ("ref" in f or "or_ref" in f or "ref_map" in f or f.get("type") == "ref") and name not in known:
                    errors.append(f"{cid}.{name}: link role {name} is in no role class (base.yaml roles)")
    errors += [f"impl role {r} is in no role class (base.yaml roles)" for r in sorted(IMPL_ROLES - known)]

    for k, tools in sorted(produced.items()):
        if len(tools) > 1 and k not in MULTI_OWNER_OK:
            gaps.append(f"kind `{k}` has {len(tools)} writers: {sorted(tools)}")

    return errors, gaps, cards, roots, produced


def lint_report(loaded):
    """The lint errors of a loaded card set (empty = clean)."""
    return sorted(set(check(loaded)[0]))


def main():
    errors, gaps, cards, roots, produced = check(load())
    by_kind = {}
    for c in cards.values():
        by_kind[c["kind"]] = by_kind.get(c["kind"], 0) + 1
    print("cards:", len(cards), dict(sorted(by_kind.items())), "| roots:", sorted(roots))
    print("kinds produced:", len(produced))
    for x in sorted(set(errors)):
        print("ERROR", x)
    for x in sorted(set(gaps)):
        print("GAP  ", x)
    print(f"{len(set(errors))} errors, {len(set(gaps))} gaps")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
