"""Tags (foundation.md §C2, W14): a tag on the unchanged thing; versions major / minor against the previous tag; aliases; trust per
task; deprecated. On every backend."""
import pytest

from bitt import Refused, names
from bitt.tools.tag import trust_of, trusted_elsewhere
from test_run import CLEAN, recipe, world

SRC = {"path": "mods/clean.py", "repo": "x", "commit": "abc123"}
EVERY_OTHER = (b'"""Keep every other row; the rest is test."""\nBITT = {"kind": "derive", "writes": "selection", "reads": ["n"]}\n\n\n'
               b'def every_other(rows: list, *, keep: int = 2) -> list:\n'
               b'    return [(i, "test" if i % 3 == 0 else "train") for i, r in enumerate(rows) if i % keep == 0]\n')


def finding(c, x, ev):
    return c("control.log.finding", in_=x, text="seen", evidence=[ev])["finding"]


def qa(c, x, raw):
    """A dataset version of the tickets: what a module's evidence is measured on (tag.evidence_versioned)."""
    ds = c("run.go", in_=x, recipe=recipe(c, x, "split", cols={"qid": "qid"}), on=[raw], as_="dataset", line="qa")["set"]
    v = c("control.validate", USR, in_=x, subject=ds, verdict="approve")["validation"]
    c("tag.make", in_=x, target=ds, tag="version", because=[c("control.log.finding", in_=x, text="holds", evidence=[v])["finding"]])
    return ds


def test_a_version_is_computed_and_set_once(opener):
    k, c, t, x, raw = world(opener())
    c1 = k.resolve("clean", t)[0]
    run = c("run.go", in_=x, recipe=recipe(c, x, "clean", cols={"text": "title"}), on=[qa(c, x, raw)])["run"]
    f = finding(c, x, run)
    with pytest.raises(Refused, match="module.in_git → fail.*not committed"):
        c("tag.make", in_=x, target=c1, tag="version", because=[f])
    c1 = c("module.define", in_=x, code=CLEAN, name="clean", source=SRC)["module"]          # the same bytes, now committed
    out = c("tag.make", in_=x, target=c1, tag="version", because=[f])                      # a module's first version: an agent's
    assert (out["bump"], names.ref_of(k, c1)) == ("first", "lib/clean@1.0")
    with pytest.raises(Refused, match="tag.once → fail.*already"):
        c("tag.make", in_=x, target=c1, tag="version", because=[f])
    c2 = c("module.define", in_=x, code=CLEAN.replace(b".lower()", b".casefold()"), name="clean", source=SRC)["module"]
    assert c("tag.make", in_=x, target=c2, tag="version", because=[f])["bump"] == "minor", "code only: a minor, an agent may tag it"
    c3 = c("module.define", in_=x, code=CLEAN.replace(b"text: str", b"txt: str").replace(b"in text", b"in txt")
           .replace(b"text.strip", b"txt.strip"), name="clean", source=SRC)["module"]
    with pytest.raises(Refused, match="control.approval"):
        c("tag.make", in_=x, target=c3, tag="version", because=[f])                        # another contract: a major
    assert [k.resolve(r, t)[0] for r in ("clean@1.0", "clean@1.1", "clean@1", "clean")] == [c1, c2, c2, c3]
    with pytest.raises(Refused, match="is not a version"):
        k.resolve("clean@2", t)
    with pytest.raises(Refused, match=r"--because <the id of a finding / decision / validation>: a finding is `bitt note"):
        c("tag.make", in_=x, target=c3, tag="version")                                     # an id, never text


def test_data_versions_follow_their_rows_and_their_upstream(opener):
    k, c, t, x, raw = world(opener())
    c("module.define", in_=x, code=EVERY_OTHER, name="every_other")
    allr = c("run.go", in_=x, recipe=recipe(c, x, "split", cols={"qid": "qid"}), on=[raw], as_="dataset", line="qa")
    f = finding(c, x, allr["run"])
    c("control.validate", USR, in_=x, subject=allr["set"], verdict="approve")
    assert c("tag.make", in_=x, target=allr["set"], tag="version", because=[f])["bump"] == "major"
    fewer = c("run.go", in_=x, recipe=recipe(c, x, "every_other", cols={"n": "qid"}), on=[allr["set"]], as_="dataset",
              line="qa_half")["set"]
    with pytest.raises(Refused, match="tag.upstream_tagged|control.approval"):
        c("tag.make", in_=x, target=fewer, tag="version", because=[f])
    sub = c("run.go", in_=x, recipe=recipe(c, x, "every_other", cols={"n": "qid"}), on=[raw], as_="dataset", line="sub")["set"]
    sub2 = c("run.go", in_=x, recipe=recipe(c, x, "every_other", cols={"n": "qid"}, params={"keep": 4}), on=[raw], as_="dataset",
             line="sub")["set"]
    c("control.validate", USR, in_=x, subject=sub, verdict="approve")
    c("tag.make", in_=x, target=sub, tag="version", because=[f])
    with pytest.raises(Refused, match="control.approval"):
        c("tag.make", in_=x, target=sub2, tag="version", because=[f])                      # rows removed, but test rows too: a major


def test_an_alias_moves_on_versions(opener):
    k, c, t, x, raw = world(opener())
    run = c("run.go", in_=x, recipe=recipe(c, x, "clean", cols={"text": "title"}), on=[qa(c, x, raw)])["run"]
    f = finding(c, x, run)
    c1 = c("module.define", in_=x, code=CLEAN, name="clean", source=SRC)["module"]
    with pytest.raises(Refused, match="alias_on_version"):
        c("tag.make", in_=x, target=c1, tag="alias", value="best")
    c("control.validate", USR, in_=x, subject=c1, verdict="approve")
    c("tag.make", in_=x, target=c1, tag="version", because=[f])
    c("tag.make", in_=x, target=c1, tag="alias", value="best")
    with pytest.raises(Refused, match="tag.once → fail.*an alias is a name"):
        c("tag.make", in_=x, target=c1, tag="alias", value="2")
    c2 = c("module.define", in_=x, code=CLEAN.replace(b".lower()", b".casefold()"), name="clean", source=SRC)["module"]
    c("tag.make", in_=x, target=c2, tag="version", because=[f])
    assert k.resolve("clean@best", t)[0] == c1
    c("tag.make", in_=x, target=c2, tag="alias", value="best")
    assert k.resolve("clean@best", t)[0] == c2, "an alias points at one version at a time: the newest wins"
    with pytest.raises(Refused, match="control.approval"):
        c("tag.make", "agent:t", in_=x, target=c2, tag="alias", value="live")             # a release is a person's
    if hasattr(k.rec, "db"):                                   # Postgres: bitt.resolve() reads names the way the kernel does
        refs = ["clean", "clean@1", "clean@1.0", "clean@best", "lib/clean", "raw/tickets", "raw/tickets@1", "t"]
        sql = {r: k.rec.db.execute("SELECT bitt.resolve(%s, %s)", (r, t)).fetchone()[0] for r in refs}
        names_ = {r: k.rec.db.execute("SELECT bitt.name_of(%s), bitt.version_of(%s)", (sql[r], sql[r])).fetchone() for r in refs[:4]}
        k.rec.db.commit()
        assert sql == {r: k.resolve(r, t)[0] for r in refs}, sql
        assert names_["clean@best"] == ("lib/clean", names.version_of(k, c2))


def test_trust_is_per_task_and_measured(opener):
    k, c, t, x, raw = world(opener())
    eq = k.resolve("exact_match", t)[0]
    assert trust_of(k, eq, t) == "builtin", "what bitt ships is builtin everywhere"
    mine = c("module.define", in_=x, code=b'"""Do two labels agree?"""\nBITT = {"kind": "check"}\n\n\n'
             b'def same(a: str, b: str) -> bool:\n    return a == b\n', name="same", source=SRC)["module"]
    verdicts = c("run.go", in_=x, recipe=recipe(c, x, "same", cols={"a": "qid", "b": "qid"}), on=[qa(c, x, raw)])["run"]
    agree = c("run.go", in_=x, recipe=recipe(c, x, "agreement", cols={"a": "same", "b": "tickets.qid"}), on=[verdicts])["run"]
    other = c("run.go", in_=x, recipe=recipe(c, x, "agreement", cols={"a": "qid", "b": "qid"}), on=[raw])["run"]
    f = finding(c, x, agree)
    c("control.validate", USR, in_=x, subject=mine, verdict="approve")
    with pytest.raises(Refused, match="agreement_about → fail.*another module"):
        c("tag.make", USR, in_=x, target=mine, tag="trust", value="trusted", because=[f], agreement=other)
    c("tag.make", USR, in_=x, target=mine, tag="trust", value="trusted", because=[f], agreement=agree)
    assert trust_of(k, mine, t) == "trusted"
    t2 = c("control.goal.open_root", USR, problem="y", name="t2")["goal"]
    assert trust_of(k, mine, t2) == "hint" and trusted_elsewhere(k, mine, t2) == ["t"], "trusted in t, a hint in t2 (D16)"
    with pytest.raises(Refused, match="trust is said of a check"):
        c("tag.make", USR, in_=x, target=k.resolve("clean", t)[0], tag="trust", value="trusted", because=[f], agreement=agree)
    c("tag.make", USR, in_=x, target=mine, tag="trust", value="hint", because=[f])
    assert trust_of(k, mine, t) == "hint", "a demote: the newest trust in the task counts"


def test_deprecated_warns_new_recipes(opener):
    k, c, t, x, raw = world(opener())
    run = c("run.go", in_=x, recipe=recipe(c, x, "clean", cols={"text": "title"}), on=[raw])["run"]
    c("tag.make", in_=x, target=k.resolve("clean", t)[0], tag="deprecated", value="use clean_v2's line", because=[finding(c, x, run)])
    out = c("recipe.make", in_=x, module="clean", cols={"text": "body"})
    assert any("deprecated: use clean_v2" in w for w in out.get("warnings", [])), out


USR = "usr"


def test_a_claim_stands_on_versions(opener):
    """Owner 11-04: a module is code, so tag.upstream_tagged found no data upstream of it, and a module could be versioned (or
    trusted) on evidence measured over data nobody named. The evidence a version or a trust cites stands on versions only."""
    k, c, t, x, raw = world(opener())
    c1 = c("module.define", in_=x, code=CLEAN, name="clean", source=SRC)["module"]
    loose = c("run.go", in_=x, recipe=recipe(c, x, "split", cols={"qid": "qid"}), on=[raw], as_="evalset", line="loose")["set"]
    on_loose = finding(c, x, c("run.go", in_=x, recipe=recipe(c, x, "clean", cols={"text": "title"}), on=[loose])["run"])
    with pytest.raises(Refused, match=r"tag.evidence_versioned → fail \(the evidence stands on t/loose, which is not a version"):
        c("tag.make", in_=x, target=c1, tag="version", because=[on_loose])
    on_raw = finding(c, x, c("run.go", in_=x, recipe=recipe(c, x, "clean", cols={"text": "title"}), on=[raw])["run"])
    with pytest.raises(Refused, match=r"stands on raw/tickets, which is not a version \(a raw import"):
        c("tag.make", in_=x, target=c1, tag="version", because=[on_raw])
    ok = finding(c, x, c("run.go", in_=x, recipe=recipe(c, x, "clean", cols={"text": "title"}), on=[qa(c, x, raw)])["run"])
    assert c("tag.make", in_=x, target=c1, tag="version", because=[ok])["bump"] == "first"
