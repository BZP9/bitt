"""The join step (docs/v2/inputs.md): a run's `on` is its units, `read` names the other inputs; a join looks each unit's row up by key,
keeps the units and links every row it read. On every backend."""
import json

import pytest

from bitt import Kernel, Refused, sets
from bitt.builtins import SHIPPED
from bitt.tools import packages
from bitt.tools.run import status_of

USR, A = "usr", "agent:t"
LABEL = (b'"""Say a ticket and its tier together."""\nBITT = {"kind": "derive"}\n\n\n'
         b'def label(text: str, tier: str) -> str:\n    return f"{text}|{tier}"\n')
TICKETS = [{"ticket_id": f"T{i}", "customer_id": f"C{i % 3}", "text": f"ticket {i}"} for i in range(6)]
PROFILE = [{"customer_id": "C0", "tier": "gold", "region": "north"}, {"customer_id": "C1", "tier": "silver", "region": "south"},
           {"customer_id": "C2", "tier": "bronze", "region": "east"}]


@pytest.fixture(autouse=True)
def blobs(tmp_path, monkeypatch):
    monkeypatch.setenv("BITT_BLOBS", str(tmp_path / "blobs"))


def world(rec, profile=PROFILE):
    k = Kernel(rec, packages=packages())

    def c(card, actor=A, **a):
        return k.call(card, {{"in_": "in", "as_": "as"}.get(x, x): v for x, v in a.items()}, actor)
    t = c("control.goal.open_root", USR, problem="x", name="t")["goal"]
    x = c("control.cycle.open", in_=t, question="q", level="explore", because=[t])["cycle"]
    tickets = load(c, TICKETS, "tickets")
    prof = load(c, profile, "profile")
    c("module.define", in_=x, code=SHIPPED["join"].read_bytes(), name="join")
    c("module.define", in_=x, code=LABEL, name="label")
    return k, c, x, tickets, prof


def load(c, rows, line):
    return c("data.load", bytes=json.dumps(rows), origin=f"file:{line}.json", sensitivity="internal", does="synthetic rows for a test", line=line)["raw"]


def join_recipe(c, x, cols=None, **params):
    return c("recipe.make", in_=x, module="join", cols=cols or {"tier": "profile.tier"},
             params={"key": {"profile": "customer_id"}, **params})["recipe"]


def entries(k, run):
    e = k.rec.get_row("bitt.run_end", (run,))
    t = k.rec.get_row("bitt.set", (e["out_set"],))["tbl"]
    return t, [(k.rec.get_row(t, (m,)), src) for m, _, src in sets.entries(k.rec, e["out_set"])]


def test_a_join_keeps_the_units_and_links_both_sides(opener):
    k, c, x, tickets, prof = world(opener())
    run = c("run.go", in_=x, recipe=join_recipe(c, x), on=[tickets], read={"profile": prof})["run"]
    t, es = entries(k, run)
    assert [src for _, src in es] == list(range(6)), "entry i of a join's output belongs to unit i"
    assert [r["tier"] for r, _ in es] == ["gold", "silver", "bronze"] * 2
    assert k.node(run)["payload"]["reads"] == {"profile": k.node(prof)["payload"]["set"]}, "the run records the version it read"
    linked = sets.sources_of(k.rec, t, es[1][0]["bitt_in_hash"])
    assert set(linked) == {"raw.tickets", "raw.profile"}, linked
    # a later row step reads a unit column up the chain and a looked-up column from the join
    r = c("recipe.make", in_=x, module="label", cols={"text": "text", "tier": "tier"})["recipe"]
    out = c("run.go", in_=x, recipe=r, on=[run], full="yes")["run"]
    assert [row["label"] for row, _ in entries(k, out)[1]] == [f"ticket {i}|{['gold', 'silver', 'bronze'][i % 3]}" for i in range(6)]


def test_a_repeated_key_in_a_lookup_is_refused(opener):
    k, c, x, tickets, prof = world(opener(), profile=PROFILE + [{"customer_id": "C1", "tier": "gold", "region": "west"}])
    with pytest.raises(Refused, match=r"profile has 2 rows for customer_id 'C1'"):
        c("run.go", in_=x, recipe=join_recipe(c, x), on=[tickets], read={"profile": prof})


@pytest.mark.parametrize("miss, n, status", [("empty", 6, "done"), ("drop", 4, "done"), ("fail", 4, "failed")])
def test_a_unit_with_no_match(opener, miss, n, status):
    k, c, x, tickets, prof = world(opener(), profile=PROFILE[:2])          # C2 is unknown: tickets 2 and 5
    got = c("run.go", in_=x, recipe=join_recipe(c, x, miss=miss), on=[tickets], read={"profile": prof})
    _, es = entries(k, got["run"])
    assert len(es) == n and status_of(k.rec, got["run"]) == status
    if miss == "empty":
        assert [r["tier"] for r, _ in es][2] is None
    if miss != "fail":
        assert any("2 of 6 units found no profile row" in w for w in got["warnings"]), got["warnings"]
    else:
        assert len(k.rec.table_rows("bitt.run_error", bitt_run_hash=got["run"])) == 2


def test_a_new_lookup_version_remakes_only_the_units_whose_picked_values_changed(opener):
    k, c, x, tickets, prof = world(opener())
    r = join_recipe(c, x)
    first = c("run.go", in_=x, recipe=r, on=[tickets], read={"profile": prof})["run"]
    e = k.rec.get_row("bitt.run_end", (first,))
    assert (e["made"], e["reused"]) == (3, 3), "units that read the same values share one stored row (storage dedups)"
    changed = [dict(PROFILE[0], tier="platinum"), dict(PROFILE[1], region="far"), PROFILE[2]]   # C0 picked value, C1 unpicked
    again = c("run.go", in_=x, recipe=r, on=[tickets], read={"profile": load(c, changed, "profile")})["run"]
    e = k.rec.get_row("bitt.run_end", (again,))
    assert (e["made"], e["reused"]) == (1, 5), "only C0's two tickets read a changed value (one new row, shared)"


def test_read_is_taken_only_by_a_join(opener):
    k, c, x, tickets, prof = world(opener())
    r = c("recipe.make", in_=x, module="label", cols={"text": "text", "tier": "ticket_id"})["recipe"]
    with pytest.raises(Refused, match="join it first"):
        c("run.go", in_=x, recipe=r, on=[tickets], read={"profile": prof})


def test_two_inputs_without_a_join_point_at_the_join(opener):
    k, c, x, tickets, prof = world(opener())
    r = c("recipe.make", in_=x, module="label", cols={"text": "text", "tier": "ticket_id"})["recipe"]
    with pytest.raises(Refused, match="bitt recipe join"):
        c("run.go", in_=x, recipe=r, on=[tickets, prof])


@pytest.mark.parametrize("cols, params, role, expect", [
    ({"tier": "crm.tier"}, {}, "profile", "crm is not a lookup"),
    ({"tier": "tier"}, {}, "profile", "<lookup role>.<column>"),
    (None, {"key": {"profile": "cust"}}, "profile", "no column 'cust'"),
    (None, {}, "other", "no key for other"),
])
def test_a_join_that_cannot_be_read_is_refused(opener, cols, params, role, expect):
    k, c, x, tickets, prof = world(opener())
    with pytest.raises(Refused, match=expect):
        c("run.go", in_=x, recipe=join_recipe(c, x, cols=cols, **params), on=[tickets], read={role: prof})


# ---------------------------------------------------------------- J2: many rows per key, as of the unit's time
HIST = [{"customer_id": "C0", "queue": "billing", "closed_at": "2026-01-02"}, {"customer_id": "C0", "queue": "login", "closed_at": "2026-01-05"},
        {"customer_id": "C1", "queue": "refund", "closed_at": "2026-01-03"}, {"customer_id": "C0", "queue": "refund", "closed_at": "2026-01-01"}]
TIMED = [{"ticket_id": f"T{i}", "customer_id": f"C{i % 3}", "text": f"ticket {i}", "created_at": f"2026-01-0{i + 1}"} for i in range(6)]


def history_join(c, x, tickets, hist, **params):
    r = c("recipe.make", in_=x, module="join", cols={"queues": "hist.queue"},
          params={"key": {"hist": "customer_id"}, "many": ["hist"], **params})["recipe"]
    return c("run.go", in_=x, recipe=r, on=[tickets], read={"hist": hist})


def test_many_reads_every_matching_row_as_a_list(opener):
    k, c, x, tickets, prof = world(opener())
    got = history_join(c, x, tickets, load(c, HIST, "hist"))
    rows = [r["queues"] for r, _ in entries(k, got["run"])[1]]
    assert rows[0] == ["billing", "login", "refund"] and rows[1] == ["refund"], rows
    assert rows[2] == [], "a many role never misses: no row is an empty list"
    assert any("2 of 6 units found no hist row (read as [])" in w for w in got["warnings"]), got.get("warnings")


def test_asof_reads_only_rows_before_the_unit_and_a_future_row_remakes_nothing(opener):
    k, c, x, _, prof = world(opener())
    tickets = load(c, TIMED, "timed")
    asof = {"hist": ["closed_at", "created_at"]}
    run = history_join(c, x, tickets, load(c, HIST, "hist"), asof=asof)["run"]
    rows = [r["queues"] for r, _ in entries(k, run)[1]]
    # T0 (C0, 01-01): nothing strictly before; T3 (C0, 01-04): refund 01-01, billing 01-02, in time order; T1 (C1, 01-02): nothing
    assert (rows[0], rows[3], rows[1], rows[4]) == ([], ["refund", "billing"], [], ["refund"]), rows
    later = HIST + [{"customer_id": "C0", "queue": "shipping", "closed_at": "2026-02-01"}]
    again = history_join(c, x, tickets, load(c, later, "hist"), asof=asof)["run"]
    e = k.rec.get_row("bitt.run_end", (again,))
    assert e["made"] == 0, "a row after every unit's time changes nothing anyone read"


@pytest.mark.parametrize("params, expect", [
    ({"many": ["crm"]}, "many names crm, which is not a lookup"),
    ({"many": [], "asof": {"profile": ["tier", "text"]}}, "asof is for a many role"),
])
def test_many_and_asof_that_do_not_fit_are_refused(opener, params, expect):
    k, c, x, tickets, prof = world(opener())
    with pytest.raises(Refused, match=expect):
        join_recipe(c, x, **params)


ENRICH = (b'"""Join each ticket to its profile, then label it with its tier."""\nBITT = {"kind": "pipeline"}\n\n\n'
          b'def enrich(b, on):\n'
          b'    j = b.run("join", on=on, read={"profile": b.read["profile"]}, cols={"tier": "profile.tier"},\n'
          b'              params={"key": {"profile": "customer_id"}})\n'
          b'    return b.run("label", on=j, cols={"text": "text", "tier": "tier"})\n')


def test_a_pipeline_hands_its_read_inputs_to_a_join_step(opener):
    k, c, x, tickets, prof = world(opener())
    c("module.define", in_=x, code=ENRICH, name="enrich")
    p = c("recipe.make", in_=x, module="enrich")["recipe"]
    run = c("run.go", in_=x, recipe=p, on=[tickets], read={"profile": prof})["run"]
    assert status_of(k.rec, run) == "done"
    last = k.node(run)["links"]["steps"][-1]
    assert [r["label"] for r, _ in entries(k, last)[1]] == [f"ticket {i}|{['gold', 'silver', 'bronze'][i % 3]}" for i in range(6)]


def test_a_dataset_over_shared_rows_says_split_first(opener):
    """Units that read the same values share one stored row, so a select over such a run cannot list each row once: the refusal says
    to split the units first, then join (a join keeps the splits)."""
    k, c, x, tickets, prof = world(opener())
    c("module.define", in_=x, code=(b'"""Keep every row, all on the train side."""\nBITT = {"kind": "derive", "writes": "selection"}\n\n\n'
                                    b'def all_train(rows: list) -> list:\n    return [(i, "train") for i, r in enumerate(rows)]\n'),
      name="all_train")
    split = c("recipe.make", in_=x, module="all_train")["recipe"]
    run = c("run.go", in_=x, recipe=join_recipe(c, x), on=[tickets], read={"profile": prof})["run"]
    with pytest.raises(Refused, match=r"6 units share 3 stored rows.*split raw/tickets@1 first.*then join on that dataset"):
        c("run.go", in_=x, recipe=split, on=[run], as_="dataset", line="joined_ds")
    ds = c("run.go", in_=x, recipe=split, on=[tickets], as_="dataset", line="tickets_ds")["set"]
    again = c("run.go", in_=x, recipe=join_recipe(c, x), on=[ds], read={"profile": prof})["run"]
    assert [sp for _, sp, _ in sets.entries(k.rec, k.rec.get_row("bitt.run_end", (again,))["out_set"])] == ["train"] * 6, \
        "split first, then join: the join keeps the splits"
