"""The command line drives every act (foundation.md §D2): a task end to end through `bitt …`, on a Postgres store of its own."""
import json
import re

import pytest

from bitt import cli

USR, A = ("--as", "usr"), ("--as", "agent:t")


def bitt(capsys, *argv):
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out + out.err


@pytest.fixture
def store(tmp_path, monkeypatch, pg_dsn):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BITT_DSN", pg_dsn)
    monkeypatch.setenv("BITT_BLOBS", str(tmp_path / "blobs"))
    (tmp_path / "tickets.jsonl").write_text("".join(json.dumps({"id": i, "body": " ".join(["w"] * (i + 1)), "title": f"T{i}"}) + "\n"
                                                    for i in range(12)))
    (tmp_path / "words.py").write_text('"""Count the words of a text."""\nBITT = {"kind": "derive"}\n\n\n'
                                       'def words(text: str) -> int:\n    return len(text.split())\n')
    (tmp_path / "title.json").write_text(json.dumps({"bitt": {"does": "Echo the title."}, "messages": [{"role": "user",
                                                                                                    "content": "{title}"}]}))
    return tmp_path


def ok(capsys, *argv):
    code, out = bitt(capsys, *argv)
    assert code == 0, out
    return out


def test_a_task_end_to_end(store, capsys):
    ok(capsys, *USR, "task", "new", "demo", "count words")
    out = ok(capsys, *USR, "cycle", "new", "demo", "how long are tickets?")
    assert "now your current cycle" in out
    out = ok(capsys, *A, "data", "load", "tickets.jsonl", "--does", "synthetic rows for a test", "--line", "tickets", "--sensitivity", "internal")
    assert "12 rows (12 new) into raw.tickets" in out
    out = ok(capsys, *A, "module", "add", "words.py")
    assert "a derive, reads ['text'] → writes {'words': 'int'}" in out and "not committed in git" in out
    code, out = bitt(capsys, *A, "recipe", "words")
    assert code == 2 and "unbound: ['text']" in out and "--cols text=<column>" in out, out
    out = ok(capsys, *A, "recipe", "words", "--cols", "text=body")
    words = re.search(r"recipe (words:[0-9a-f]{8}): lib/words, text ← body", out)[1]
    assert f"next: bitt run go {words} --on <data>" in out, "the label always ends in its hash (C10)"
    code, out = bitt(capsys, *A, "run", "go", "words", "--on", "raw/tickets")
    assert code == 2 and f"next: write one of {words}" in out, "the base alone never resolves"
    out = ok(capsys, *A, "run", "go", words, "--on", "raw/tickets")
    assert "smoke " in out and "rung 1/12: made 1" in out and "rung 10/12: made 9" in out, "one call: the smoke rung, then the sample"
    assert f"then bitt run go {words} --on raw/tickets for the rest" in out
    out = ok(capsys, *A, "run", "go", words, "--on", "raw/tickets", "--full")
    assert "made 2, reused 10" in out and "without its sample" not in out, "the rest, after the sample was looked at: no warning"
    titles = re.search(r"recipe (words:[0-9a-f]{8})", ok(capsys, *A, "recipe", "words", "--cols", "text=title"))[1]
    out = ok(capsys, *A, "run", "go", titles, "--on", "raw/tickets", "--full")
    assert "made 11, reused 1" in out and "without its sample of 10 looked at first" in out, "a warning an impl writes reaches the command"
    ok(capsys, *A, "module", "add", "length")
    length = re.search(r"recipe (\S+:[0-9a-f]{8})", ok(capsys, *A, "recipe", "length", "--cols", "text=body", "--params", "max=6"))[1]
    out = ok(capsys, *A, "run", "go", length, "--on", "raw/tickets")
    assert "made 12" in out and "length_ok" not in out, "a check makes its verdict rows, no metric line"
    judged = re.search(r"run (\w{12}) of length", out)[1]
    ok(capsys, *A, "module", "add", "rate")
    rate = re.search(r"recipe (\S+:[0-9a-f]{8})", ok(capsys, *A, "recipe", "rate", "--cols", "x=length_ok", "--name", "share_short"))[1]
    assert rate.startswith("rate:") and "(alias share_short)" in ok(capsys, *A, "recipe", "list"), "an alias beside the label"
    out = ok(capsys, *A, "run", "go", "share_short", "--on", judged)
    row = next(x for x in out.splitlines() if x.strip().startswith("row: "))
    assert {"rate = 0.5", "n = 12"} <= set(row.strip()[5:].split(", ")), "across rows: the rate module's one row (any column order)"
    ok(capsys, *A, "module", "add", "echo")
    out = ok(capsys, *A, "artifact", "add", "title.json", "--kind", "prompt")
    assert "needs ['title'] → gives" in out
    out = ok(capsys, *A, "recipe", "echo", "--fill", "prompt=title", "--cols", "title=title")
    title = re.search(r"recipe (title:[0-9a-f]{8}):", out)[1]                         # a generate recipe starts with its prompt
    out = ok(capsys, *A, "run", "go", title, "--on", "raw/tickets", "--full")
    assert "rung 1/12: made 1" in out and "rung 12/12: made 11" in out, "full: the smoke rung, then the other 11"
    (store / "title.json").write_text(json.dumps({"bitt": {"does": "Echo the title, shouting."}, "messages": [{"role": "user",
                                                                                                         "content": "{title}!"}]}))
    ok(capsys, *A, "artifact", "add", "title.json", "--kind", "prompt")
    assert "prompt: title, unversioned 1" in ok(capsys, *A, "show", title), "a recipe shows the version it pinned, not the newest"
    out = ok(capsys, *A, "data", "tables")
    assert "made.words" in out and "made.title" in out and "raw.tickets" in out
    out = ok(capsys, *A, "show", "words")
    assert "a derive module: Count the words of a text." in out
    out = ok(capsys, *A, "log", "-n", "50")
    assert "run.go" in out and "recipe.make" in out
    code, out = bitt(capsys, *A, "tag", "words", "--version")
    assert code == 2 and "because" in out, "a version tag says why"


def test_inspect_shows_a_tasks_own_rows(store, capsys):
    """A23: `data inspect --task T` shows only the rows T's runs made or reused (two tasks, the same work, overlapping data)."""
    ok(capsys, *USR, "task", "new", "one", "count words")
    ok(capsys, *USR, "task", "new", "two", "count words too")
    ok(capsys, *A, "data", "load", "tickets.jsonl", "--does", "synthetic rows for a test", "--line", "tickets", "--sensitivity", "internal")
    ok(capsys, *USR, "cycle", "new", "one", "all of them")
    ok(capsys, *A, "module", "add", "words.py")
    words = re.search(r"recipe (words:[0-9a-f]{8})", ok(capsys, *A, "recipe", "words", "--cols", "text=body"))[1]
    run = re.search(r"run (\w{12}) of", ok(capsys, *A, "run", "go", words, "--on", "raw/tickets", "--full"))[1]
    lines = (store / "tickets.jsonl").read_text().splitlines()
    (store / "some.jsonl").write_text("\n".join(lines[:5] + [json.dumps({"id": 90 + i, "body": "x " * (20 + i), "title": "N"})
                                                               for i in range(3)]) + "\n")
    ok(capsys, *A, "data", "load", "some.jsonl", "--does", "synthetic rows for a test", "--line", "some", "--sensitivity", "internal")
    ok(capsys, *USR, "cycle", "new", "two", "five of them, and three new")
    assert words in ok(capsys, *A, "recipe", "words", "--cols", "text=body"), "the same work in the other task"
    ok(capsys, *A, "run", "go", words, "--on", "raw/some", "--full")              # 5 rows reused, 3 made
    out = ok(capsys, *A, "data", "inspect", run, "--task", "two", "-n", "20")
    assert out.splitlines()[0] == "5 of 12 rows are task two's" and out.count("words=") == 5, out
    out = ok(capsys, *A, "data", "inspect", run, "--task", "one", "-n", "20")
    assert out.splitlines()[0] == "12 of 12 rows are task one's" and out.count("words=") == 12, out


def test_a_join_from_the_command_line(store, capsys):
    """docs/v2/inputs.md: `--read role=data` names a join's lookup; the run says how many units found no row."""
    (store / "profile.jsonl").write_text("".join(json.dumps({"id": i, "tier": f"tier{i}"}) + "\n" for i in range(10)))
    ok(capsys, *USR, "task", "new", "demo", "join tickets to a profile")
    ok(capsys, *USR, "cycle", "new", "demo", "do tickets get a tier?")
    ok(capsys, *A, "data", "load", "tickets.jsonl", "--does", "synthetic rows for a test", "--line", "tickets", "--sensitivity", "internal")
    ok(capsys, *A, "data", "load", "profile.jsonl", "--does", "synthetic rows for a test", "--line", "profile", "--sensitivity", "internal")
    ok(capsys, *A, "module", "add", "join")
    out = ok(capsys, *A, "recipe", "join", "--cols", "tier=profile.tier", "--params", 'key={"profile": "id"}')
    join = re.search(r"recipe (join:[0-9a-f]{8})", out)[1]
    code, out = bitt(capsys, *A, "run", "go", join, "--on", "raw/tickets", "--read", "profile")
    assert code == 2 and "--read takes role=data" in out, out
    out = ok(capsys, *A, "run", "go", join, "--on", "raw/tickets", "--read", "profile=raw/profile")
    assert "2 of 12 units found no profile row (read as empty)" in out, out


def test_an_eval_prints_its_decision_and_the_row_it_read(store, capsys):
    """An eval (a pipeline with a win rule) prints what it decided and the one row its rule read (the decision's `row`)."""
    (store / "short_share.py").write_text('"""Most tickets are short."""\nBITT = {"kind": "pipeline", "win": "rate >= 0.4"}\n\n\n'
                                          'def short_share(b, on):\n    v = b.run("length", on=on, cols={"text": "body"}, params={"max": 6})\n'
                                          '    return b.run("rate", on=v, cols={"x": "length_ok"})\n')
    ok(capsys, *USR, "task", "new", "demo", "are tickets short?")
    ok(capsys, *USR, "cycle", "new", "demo", "how many are short?")
    ok(capsys, *A, "data", "load", "tickets.jsonl", "--does", "synthetic rows for a test", "--line", "tickets", "--sensitivity", "internal")
    for m in ("length", "rate", "short_share.py"):
        ok(capsys, *A, "module", "add", m)
    ev = re.search(r"recipe (\S+:[0-9a-f]{8})", ok(capsys, *A, "recipe", "short_share"))[1]
    out = ok(capsys, *A, "run", "go", ev, "--on", "raw/tickets", "--full")
    assert "decision: won (rate >= 0.4; row {" in out and '"n": 12' in out, out


def test_show_counts_a_selections_rows(store, capsys):
    """`bitt show` on a selection (the plain set: words.md W17) says how many rows it holds, like a dataset."""
    ok(capsys, *USR, "task", "new", "demo", "pick tickets")
    ok(capsys, *USR, "cycle", "new", "demo", "which tickets?")
    ok(capsys, *A, "data", "load", "tickets.jsonl", "--does", "synthetic rows for a test", "--line", "tickets", "--sensitivity", "internal")
    ok(capsys, *A, "module", "add", "exclude")
    keep = re.search(r"recipe (exclude:[0-9a-f]{8})", ok(capsys, *A, "recipe", "exclude", "--params", "drop=[]"))[1]
    out = ok(capsys, *A, "run", "go", keep, "--on", "raw/tickets", "--as", "selection")
    sel = re.search(r"\b(selection|set) (\w{12})", out)[2]
    assert "12 rows of raw.tickets" in ok(capsys, *A, "show", sel)


def test_log_all_shows_every_refusal_in_order(store, capsys):
    """`bitt log` shows the last few refusals; `--all` shows every event, refusal and warning in order, with the time, so an agent's
    failed tries can be read back (the skill's issue step saves it)."""
    ok(capsys, *USR, "task", "new", "demo", "count words")
    ok(capsys, *USR, "cycle", "new", "demo", "how long are tickets?")
    ok(capsys, *A, "data", "load", "tickets.jsonl", "--does", "synthetic rows for a test", "--line", "tickets", "--sensitivity", "internal")
    ok(capsys, *A, "module", "add", "words.py")
    for _ in range(4):
        assert bitt(capsys, *A, "recipe", "words")[0] == 2                  # refused: unbound
    ok(capsys, *A, "recipe", "words", "--cols", "text=body")
    assert ok(capsys, *A, "log", "demo", "-n", "50").count("refused") <= 3
    out = ok(capsys, *A, "log", "demo", "--all")
    lines = out.splitlines()
    refused = [i for i, x in enumerate(lines) if "refused recipe.make" in x]
    made = [i for i, x in enumerate(lines) if "recipe.make" in x and "refused" not in x]
    assert len(refused) == 4 and made and max(refused) < made[-1], out
    assert re.search(r"\d{4}-\d\d-\d\d", lines[refused[0]]), "every line carries its time"


def test_find_data_by_what_it_is_for(store, capsys):
    """A24 (owner 11-06): "iirc there should be a dataset about client questions": every load says what the data is (`--does`), and
    `bitt data list <words>` finds a line by its words (name, what it is for, columns, source) even when its columns say otherwise;
    a dataset says what made it (its module's `does`). The rows are then read with `bitt data inspect`."""
    with pytest.raises(SystemExit) as no:
        cli.main([*A, "data", "load", "tickets.jsonl", "--line", "tickets", "--sensitivity", "internal"])
    assert no.value.code == 2 and "--does" in capsys.readouterr().err, "a load says what the data is"
    (store / "faq.jsonl").write_text("".join(json.dumps({"question": f"how do I {v}?", "answer": "see the page"}) + "\n" for v in ("pay", "log in")))
    ok(capsys, *USR, "task", "new", "demo", "route tickets")
    ok(capsys, *USR, "cycle", "new", "demo", "what do clients ask")
    ok(capsys, *A, "data", "load", "tickets.jsonl", "--line", "helpdesk", "--sensitivity", "internal",
       "--does", "questions clients sent to the help desk, one per row")
    ok(capsys, *A, "data", "load", "faq.jsonl", "--line", "faq", "--sensitivity", "public", "--does", "our public FAQ page, written by staff")
    ok(capsys, *A, "module", "add", "words.py")
    words = re.search(r"recipe (words:[0-9a-f]{8})", ok(capsys, *A, "recipe", "words", "--cols", "text=body"))[1]
    ok(capsys, *A, "run", "go", words, "--on", "raw/helpdesk", "--full")
    out = ok(capsys, *A, "data", "list")
    assert "raw/helpdesk" in out and "raw/faq" in out and "questions clients sent" in out, out
    out = ok(capsys, *A, "data", "list", "client", "questions")
    first = out.splitlines()[0]
    assert first.startswith("raw/helpdesk") and "12 rows" in first, "the line whose does says it ranks first, not the one with a question column"
    assert "next: bitt data inspect raw/helpdesk" in out
    assert "no data line mentions" in ok(capsys, *A, "data", "list", "invoices")
    rows = ok(capsys, *A, "data", "inspect", "raw/helpdesk", "-n", "3")
    assert rows.count("body=") == 3 or rows.count("title=") >= 3, rows


def test_a_dataset_says_what_made_it_and_every_raw_line_what_it_is(opener):
    """A24: `bitt data list` reads each line's purpose from what the record holds: a raw line's `does`, a dataset's module and its
    `does` and the data it was made from; `--task` keeps that task's datasets (and every raw line: raw is no task's)."""
    from test_cross_task import other
    from test_run import recipe, world
    k, c, t, x, raw = world(opener())
    c("run.go", in_=x, recipe=recipe(c, x, "split", cols={"qid": "qid"}), on=[raw], as_="dataset", line="qa")
    u, y = other(c)
    lines = {it["line"]: it for it in cli.data_lines(k)}
    assert lines["raw/tickets"]["does"] == "synthetic rows for a test" and lines["raw/tickets"]["source"] == "file:t.json"
    qa = next(it for name, it in lines.items() if name.endswith("qa"))
    assert qa["kind"] == "dataset" and qa["does"].startswith("made by ") and qa["source"] == "from raw/tickets", qa
    assert qa["rows"] == 12 and qa["task"] == "t"
    assert [it["kind"] for it in cli.data_lines(k, u)] == ["raw"], "another task sees every raw line, not t's datasets"
    found = cli.match_lines(cli.data_lines(k), ["synthetic"])
    assert [it["line"] for it in found] == ["raw/tickets"], "found by what it is for, not only by its name"
