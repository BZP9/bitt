"""The walker (docs/v2/walk.md): one role registry, one way to walk the record; lineage follows every input kind. On every backend."""
import json

import pytest
from test_join import LABEL, PROFILE, TICKETS, entries, join_recipe, load, world

from bitt import Refused, cards, walk
from bitt.tools.tag import c_upstream_tagged

ALL_TRAIN = (b'"""Keep every row, all on the train side."""\nBITT = {"kind": "derive", "writes": "selection"}\n\n\n'
             b'def all_train(rows: list) -> list:\n    return [(i, "train") for i, r in enumerate(rows)]\n')
OLD_CONTEXT = {"in", "origin", "because", "evidence", "fills", "resolving", "supersedes", "subject", "check", "against", "read", "line",
               "target", "replaces", "during", "evals", "grant"}


def old_lineage(k, nid):
    """The lineage walk before the registry (kernel.py, 10-30): every link but the old context roles."""
    seen, todo = set(), [nid]
    while todo:
        x = todo.pop()
        if x in seen:
            continue
        seen.add(x)
        for role, v in k.node(x)["links"].items():
            if role not in OLD_CONTEXT:
                todo += v if isinstance(v, list) else [v]
    return seen


def joined(c, x, tickets, prof, **kw):
    return c("run.go", in_=x, recipe=join_recipe(c, x), on=[tickets], read={"profile": prof}, **kw)["run"]


def test_walk_up_is_the_old_lineage_where_nothing_was_read(opener):
    k, c, x, tickets, prof = world(opener())
    r = c("recipe.make", in_=x, module="label", cols={"text": "text", "tier": "ticket_id"})["recipe"]
    c("run.go", in_=x, recipe=r, on=[tickets], full="yes")
    for n in list(k.rec.nodes.values()):
        assert walk.Walk(k).up(n["id"]).ids() == old_lineage(k, n["id"]), n["kind"]


def test_lineage_follows_a_joins_lookups(opener):
    k, c, x, tickets, prof = world(opener())
    run = joined(c, x, tickets, prof)
    up = walk.Walk(k).up(run)
    assert prof in up.ids() and prof not in old_lineage(k, run), "a lookup is made-from, not context"
    assert set(up.raw()) == {tickets, prof}


def test_a_later_step_inherits_a_lookups_sensitivity(opener, tmp_path, monkeypatch):
    (tmp_path / "envs.yaml").write_text("wide:\n  type: local\n  max_sensitivity: personal\n")
    monkeypatch.setenv("BITT_ENVS", str(tmp_path / "envs.yaml"))
    k, c, x, tickets, _ = world(opener())
    secret = c("data.load", bytes=json.dumps([dict(r, note="private") for r in PROFILE]), origin="file:secret.json",
               sensitivity="personal", does="synthetic rows for a test", line="secret")["raw"]
    run = joined(c, x, tickets, secret, env="wide")
    r = c("recipe.make", in_=x, module="label", cols={"text": "text", "tier": "tier"})["recipe"]
    with pytest.raises(Refused, match="the input is 'personal'"):
        c("run.go", in_=x, recipe=r, on=[run], full="yes")


def test_a_version_sees_an_untagged_dataset_read_through_a_join(opener):
    k, c, x, tickets, prof = world(opener())
    c("module.define", in_=x, code=ALL_TRAIN, name="all_train")
    split = c("recipe.make", in_=x, module="all_train")["recipe"]
    marks = load(c, [{"ticket_id": f"T{i}", "mark": i} for i in range(6)], "marks")      # one row per ticket: no joined row is shared
    pds = c("run.go", in_=x, recipe=split, on=[marks], as_="dataset", line="marks_ds")["set"]
    jr = c("run.go", in_=x, recipe=c("recipe.make", in_=x, module="join", cols={"mark": "marks.mark"},
                                     params={"key": {"marks": "ticket_id"}})["recipe"], on=[tickets], read={"marks": pds})["run"]
    ds = c("run.go", in_=x, recipe=split, on=[jr], as_="dataset", line="tickets_ds")["set"]
    verdict, why = c_upstream_tagged(k, ds, {})
    assert verdict == "fail" and "marks_ds" in why, why


def test_the_walkers_calls(opener):
    k, c, x, tickets, prof = world(opener())
    run = joined(c, x, tickets, prof)
    w = walk.Walk(k)
    ins = w.inputs(run)
    assert ins["on"] == [tickets] and ins["read"] == {"profile": prof} and k.node(ins["module"])["payload"]["header"]["kind"] == "join"
    rows = w.rows(run)
    assert len(rows) == 6
    assert [u for _, _, _, u in rows] == [row for _, row, _, _ in w.rows(tickets)], "each joined row's unit is its ticket"
    t, first = rows[0][0], rows[0][1]
    assert {tt for tt, _ in w.rows_up(t, first)} == {t, "raw.tickets", "raw.profile"}
    assert (t, first) in w.rows_down("raw.profile", w.rows(prof)[0][1])
    assert w.up(run).runs(kind="join") == [run] and not w.up(run).runs(kind="generate")
    assert x in w.story(run).ids(), "a run's story reaches its cycle"


def test_a_role_in_two_classes_is_refused(tmp_path):
    base = next(f for f in cards.default_files() if f.name == "base.yaml")
    text = base.read_text()
    assert "    story: [in," in text, "the planting anchor moved"
    p = tmp_path / "base.yaml"
    p.write_text(text.replace("    story: [in,", "    story: [\"on\", in,", 1))
    report = cards.lint_report(cards.load([f for f in cards.default_files() if f != base] + [p]))
    cards.load()
    assert any("on is in two role classes" in e for e in report), report


def test_every_link_role_in_a_store_has_one_class(opener):
    k, c, x, tickets, prof = world(opener())
    run = joined(c, x, tickets, prof)
    c("run.go", in_=x, recipe=c("recipe.make", in_=x, module="label", cols={"text": "text", "tier": "tier"})["recipe"], on=[run], full="yes")
    roles = {role for n in k.rec.nodes.values() for role in n["links"]}
    assert not [r for r in roles if cards.role_class(r) is None], roles


def test_a_link_role_in_no_class_is_refused(tmp_path):
    run = next(f for f in cards.default_files() if f.name == "run.yaml")
    text = run.read_text()
    anchor = "        read: {ref_map: [raw, selection, dataset, evalset, run]}"
    assert anchor in text, "the planting anchor moved"
    p = tmp_path / "run.yaml"
    p.write_text(text.replace(anchor, anchor + "\n        hidden: {ref: [run]}", 1))
    report = cards.lint_report(cards.load([f for f in cards.default_files() if f != run] + [p]))
    cards.load()
    assert any("run.go.hidden: link role hidden is in no role class" in e for e in report), report


def test_no_rule_walks_the_record_itself():
    """The rules ask the walker (walk.md §4): no link, `__src` or set membership is read in tools/rules.py."""
    from pathlib import Path
    import re
    src = (Path(__file__).resolve().parents[1] / "src" / "bitt" / "tools" / "rules.py").read_text()
    found = re.findall(r'\["links"\]|__src|sources_of|sets\.members|sets\.entries|\.children\(|\.kids\(', src)
    assert not found, found


def test_nothing_in_src_walks_the_record_but_the_walker():
    """W3 (walk.md §4): no file under src/ but the walker and the storage layer (record/, sets.py, tables.py) walks the row graph, reads
    set membership, or follows a run's inputs (`on`, `read`) itself."""
    from pathlib import Path
    import re
    root = Path(__file__).resolve().parents[1] / "src" / "bitt"
    keep = {root / "walk.py", root / "sets.py", root / "tables.py"}
    pat = re.compile(r'__src|sources_of\(|sets\.members\(|sets\.entries\(|links"\]\["(on|read)"\]|links"\]\.get\("(on|read)"\)')
    found = [f"{p.relative_to(root)}:{i}" for p in root.rglob("*.py") if p not in keep and "record" not in p.parts
             for i, line in enumerate(p.read_text().splitlines(), 1) if pat.search(line)]
    assert not found, found


SORTED_11_03 = {"made_from": {"parent", "set"},
                "story": {"about", "agreement", "arms", "cycle", "dataset", "decision", "fill", "goal", "pipeline", "policy", "prev", "want",
                          "ref", "rule"}}


def test_the_roles_sorted_in_the_scenario_walk(opener):
    """#9 (owner 11-03): the 16 'unsorted' roles each have a class; a finding's `about` is context (no longer lineage), a version's
    `parent` is what it was made from (still lineage)."""
    from bitt.builtins import SHIPPED
    from test_run import recipe as rcp, world as run_world
    k, c, t, x, raw = run_world(opener())
    for klass, roles in SORTED_11_03.items():
        assert {r for r in roles if cards.role_class(r) != klass} == set(), klass
    c("module.define", in_=x, code=SHIPPED["exclude"].read_bytes(), name="exclude")
    v1 = c("run.go", in_=x, recipe=rcp(c, x, "split", cols={"qid": "qid"}), on=[raw], as_="dataset", line="qa")["set"]
    v1_run = walk.Walk(k).links(v1, "run")[0]
    f = c("control.log.finding", in_=x, text="v1 has duplicates", about=v1, evidence=[v1_run])["finding"]
    assert v1 not in walk.Walk(k).up(f).ids(), "about (and evidence) are story: a finding is not made from what it is about"
    drop = [m for m, _ in __import__("bitt").sets.members(k.rec, k.node(v1)["payload"]["set"])][:1]
    v2 = c("run.go", in_=x, recipe=rcp(c, x, "exclude", params={"drop": drop}), on=[v1], as_="dataset", line="qa", parent=v1)["set"]
    assert v1 in walk.Walk(k).up(v2).ids(), "parent is made_from: a new version is built on its parent"


def test_sql_and_the_walker_walk_alike(opener):
    """W5 (charter guarantee 7): bitt.lineage / bitt.downstream in Postgres return what walk.up / walk.down return, for every node of a
    store with a join (units, a read input, a recipe, a module, runs, sets)."""
    rec = opener()
    if not hasattr(rec, "db"):
        pytest.skip("the SQL walks are Postgres's")
    k, c, x, tickets, prof = world(rec)
    run = c("run.go", in_=x, recipe=join_recipe(c, x), on=[tickets], read={"profile": prof})["run"]
    c("run.go", in_=x, recipe=c("recipe.make", in_=x, module="label", cols={"text": "text", "tier": "tier"})["recipe"], on=[run], full="yes")
    w, checked = walk.Walk(k), 0
    for nid in list(k.rec.nodes):
        up = {r[0] for r in rec.db.execute("SELECT id FROM bitt.lineage(%s)", (nid,)).fetchall()}
        down = {r[0] for r in rec.db.execute("SELECT id FROM bitt.downstream(%s)", (nid,)).fetchall()}
        assert up == set(w.up(nid).ids()), (k.node(nid)["kind"], up ^ set(w.up(nid).ids()))
        assert down == set(w.down(nid).ids()), (k.node(nid)["kind"], down ^ set(w.down(nid).ids()))
        checked += 1
    assert checked > 20
