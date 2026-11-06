"""The panel (bitt.panel: data, view, serve = `bitt serve`; owner 11-04): home (every task) → a task → a cycle, drawn from the
store on every request, each open page redrawing itself when the store's seq moves; read only; words only confirm the layout."""
import json
import re
import threading
import urllib.error
import urllib.request

from test_cross_task import other, version
from test_run import USR, recipe, world

from bitt.panel import data as panel_data
from bitt.panel import view as panel_view
from bitt.panel.serve import Panel, Store, read_only


def pages(k):
    """{name: html} of every page of a store, with static links."""
    panel_view.L = panel_view.Links()
    S = panel_data.model(k)
    out = {"home": panel_view.home(S)}
    for t in S["tasks"]:
        out[f"task {t['name']}"] = panel_view.task_page(t)
        for c in t["cycles"]:
            out[f"cycle {t['name']}#{c['n']}"] = panel_view.cycle_page(t, c)
    return S, out


def test_home_lists_every_task_and_each_task_its_cycles(opener):
    k, c, t, x, raw = world(opener())
    other(c)
    S, p = pages(k)
    names = [x["name"] for x in S["tasks"]]
    assert len(names) == 2 and all(f"href='task_{n}.html'" in p["home"] for n in names), "home: one lane per task, each a link"
    for task in S["tasks"]:
        for cy in task["cycles"]:
            assert f"href='cycle_{task['name']}_{cy['n']}.html'" in p[f"task {task['name']}"], "a task links each of its cycles"
            assert f"cycle {task['name']}#{cy['n']}" in p


def test_parallel_cycles_are_lanes_and_the_task_map_has_every_cycle(opener):
    """Open cycles side by side, one lane each (their tracks aligned); the task's map: everything any cycle made, each box badged."""
    k, c, t, x, raw = world(opener())
    y = c("control.cycle.open", in_=t, question="a second look", level="explore", because=[t])["cycle"]
    c("run.go", in_=x, recipe=recipe(c, x, "clean", cols={"text": "title"}), on=[raw], full="yes")
    c("run.go", in_=y, recipe=recipe(c, y, "clean", cols={"text": "body"}), on=[raw], full="yes")
    S, p = pages(k)
    task = S["tasks"][0]
    assert p[f"task {task['name']}"].count("<a href='cycle_") >= 2 and "class='par'" in p[f"task {task['name']}"]
    cycs = {n.get("cyc") for n in task["whole"]["nodes"] if n["shape"] == "step"}
    assert len(cycs) == 2, "the map holds both cycles' steps, each badged with its cycle"


def test_the_cycle_page_draws_its_arms_side_by_side(opener):
    from test_pipeline import setup
    from test_tag import qa
    k, c, t, x, raw = world(opener())
    setup(k, c, x)
    w = c("control.cycle.open", USR, in_=t, question="is clean good enough?", level="working", because=[t])["cycle"]
    arm = recipe(c, w, "clean", cols={"text": "title"})
    c("control.plan", USR, in_=w, arms=[arm], win="most outputs are not blank", pipeline="judge_nonempty")
    c("run.go", in_=w, recipe=arm, on=[qa(c, x, raw)], full="yes")
    S, p = pages(k)
    task = S["tasks"][0]
    n = next(cy["n"] for cy in task["cycles"] if cy["question"] == "is clean good enough?")
    page = p[f"cycle {task['name']}#{n}"]
    assert "<table class='arms'>" in page and ">qa@1.0</th>" in page, "one column per data the arm was judged on"
    assert re.search(r"class='(won|lost) num'>", page), "each cell: the decision's rate, won or lost by colour"


def test_another_tasks_input_is_a_box_of_that_task(opener):
    """#4: a step here that reads another task's version: the version is drawn as that task's, fed from a box standing for it."""
    k, c, t, x, raw = world(opener())
    ds = c("run.go", in_=x, recipe=recipe(c, x, "split", cols={"qid": "qid"}), on=[raw], as_="dataset", line="qa")["set"]
    version(c, x, ds)
    u, y = other(c)
    c("run.go", in_=y, recipe=recipe(c, y, "clean", cols={"text": "title"}), on=["t/qa@1.0"], full="yes")
    S, _ = pages(k)
    fl = next(x for x in S["tasks"] if x["name"] == "u")["cycles"][0]["flow"]
    box = next(n for n in fl["nodes"] if n["id"] == ds[:12])
    assert box["lines"][0].startswith("dataset · from task t"), "drawn as t's, with its owner"
    ext = [n for n in fl["nodes"] if n["shape"] == "ext"]
    assert [n["to"][0] for n in ext] == ["t"] and [e for e in fl["edges"] if e[0] == ext[0]["id"] and e[1] == ds[:12]], "fed from t's box"


def test_every_input_role_has_its_named_arrow(opener):
    """J4 (docs/v2/inputs.md): a step that reads several inputs has an arrow from each, named by its role (`on` and each --read)."""
    from bitt.builtins import SHIPPED
    k, c, t, x, raw = world(opener())
    chat = c("data.load", bytes=json.dumps([{"qid": "q9", "title": "a chat", "body": "w"}]), origin="file:chat.json", sensitivity="internal",
             does="synthetic rows for a test", line="chat")["raw"]
    c("module.define", in_=x, code=SHIPPED["union"].read_bytes(), name="union")
    run = c("run.go", in_=x, recipe=c("recipe.make", in_=x, module="union", cols={}, params={})["recipe"], on=[raw], read={"chat": chat})["run"]
    S, _ = pages(k)
    fl = S["tasks"][0]["cycles"][0]["flow"]
    into = {e[0]: e[2] for e in fl["edges"] if e[1] == run[:12]}
    assert into.get(raw[:12], "").startswith("on") and into.get(chat[:12], "").startswith("chat"), into


def test_no_words_where_layout_speaks_and_the_script_parses(opener, tmp_path):
    import shutil
    import subprocess
    k, c, t, x, raw = world(opener())
    c("run.go", in_=x, recipe=recipe(c, x, "split", cols={"qid": "qid"}), on=[raw], as_="dataset", line="tickets_split")
    _, p = pages(k)
    for name, page in p.items():
        low = re.sub(r"<[^>]+>", " ", re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", page, flags=re.S)).lower()   # what a reader sees
        assert "legend" not in low and "click " not in low and "explain" not in low, f"{name}: words where the layout speaks"
    if shutil.which("node"):
        for i, js in enumerate(re.findall(r"<script[^>]*>(.*?)</script>", p[f"task {next(iter(pages(k)[0]['tasks']))['name']}"], re.S)):
            (tmp_path / f"s{i}.js").write_text(js)
            r = subprocess.run(["node", "--check", str(tmp_path / f"s{i}.js")], capture_output=True, text=True)
            assert r.returncode == 0, r.stderr


def serve(k):
    """`bitt serve`'s server over a memory store, on a free port."""
    st = Store(lambda: k, lambda: max(n["seq"] for n in k.rec.nodes.values()))
    srv = Panel(lambda: {"mine": st}, home="mine").server(0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}"


def get(url):
    with urllib.request.urlopen(url) as r:
        return r.read().decode()


def test_live_every_page_from_the_store_and_a_seq_that_moves(opener):
    k, c, t, x, raw = world(opener())
    srv, base = serve(k)
    try:
        home = get(base + "/")
        task = re.search(r"href='(/s/mine/t/[^']+)'", home)[1]
        tpage = get(base + task)
        cyc = re.search(r"href='(/s/mine/t/[^']+/c/\d+)'", tpage)[1]
        assert "is it" in get(base + cyc) or "<h1>" in get(base + cyc)
        assert "fetch('/s/mine/seq'" in tpage, "an open page asks its store's seq"
        before, nodes = int(get(base + "/s/mine/seq")), len(k.rec.nodes)
        for path in ("/", task, cyc, "/s/mine/seq"):
            get(base + path)
        assert len(k.rec.nodes) == nodes, "reading writes nothing"
        c("run.go", in_=x, recipe=recipe(c, x, "clean", cols={"text": "title"}), on=[raw], full="yes")
        assert int(get(base + "/s/mine/seq")) > before, "a write moves the seq the page watches"
        try:
            urllib.request.urlopen(urllib.request.Request(base + "/", data=b"x", method="POST"))
            assert False, "a POST was answered"
        except urllib.error.HTTPError as e:
            assert e.code == 501, "GET only"
    finally:
        srv.shutdown()


def test_what_changed_flashes_a_ring_that_hugs_it_and_the_page_shows_its_last_check(opener):
    css = panel_view.CSS
    halo = re.search(r"@keyframes halo\{.*?\}\}", css, re.S)
    assert halo and "scale" not in halo[0], "the ring spreads a fixed few px, never scaled (a wide row would balloon)"
    assert re.search(r"\.pulse\{animation:halo [^}]* 3\}", css), "a new row flashes three times, then stops"
    assert "infinite" in re.search(r"\.nag\{[^}]*\}", css)[0], "a cycle waiting on you keeps breathing"
    assert "classList.add('pulse')" in panel_view.LIVE_JS
    k, c, t, x, raw = world(opener())
    srv, base = serve(k)
    try:
        home = get(base + "/")
        assert "id='chk'" in home and "'checked '" in home, "a served page shows when it last asked the store"
    finally:
        srv.shutdown()
    panel_view.L = panel_view.Links()
    assert "id='chk'" not in panel_view.home(panel_data.model(k)), "a static snapshot checks nothing, so shows no check"


def test_an_empty_store_still_draws_its_home(opener):
    from bitt.kernel import Kernel
    from bitt.tools import packages
    panel_view.L = panel_view.Links()
    k = Kernel(opener(), packages=packages())
    assert "class='lane'" in panel_view.home(panel_data.model(k)), "an empty store's home is not a blank page"


def test_the_eval_list_reads_a_finished_store_once_and_draws_lanes(monkeypatch, tmp_path):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import viz_serve as vs
    for name, grade in (("data_basics-20261104-162024", "m: 8/8 · 20 tool calls"), ("data_basics-20261104-170000", "m: 3/8 · 9 tool calls"),
                        ("run_basics-20261104-171000", None)):
        (tmp_path / name).mkdir()
        if grade:
            (tmp_path / name / "grade.txt").write_text(grade + "\n")
    reads = []
    monkeypatch.setattr(vs, "stores", lambda: {d.name: ("dsn", d) for d in sorted(tmp_path.iterdir())})
    monkeypatch.setattr(vs, "running_dirs", lambda: {"run_basics-20261104-171000"})
    monkeypatch.setattr(vs, "kernel", lambda dsn, d: reads.append(d.name) or object())
    monkeypatch.setattr(vs, "tasks", lambda k: ["demo"])
    monkeypatch.setattr(vs, "last_at", lambda k, d: 1.0)
    monkeypatch.setattr(vs, "CACHE", {})
    vs.rows(); vs.rows()
    assert reads.count("data_basics-20261104-162024") == 1, "a graded store is read once, then cached"
    assert reads.count("run_basics-20261104-171000") == 2, "a running store is read every time"
    page = vs.index()
    assert "<title>Agent evals</title>" in page and "ev-full" in page and "ev-miss" in page and "ev-run" in page
    assert page.count("class='lane") == 2, "one lane per eval"
    assert "fetch('/stores/seq'" in page and "id='chk'" in page, "the list is live and shows its last check"


def test_every_store_opens_read_only():
    assert "default_transaction_read_only=on" in read_only("dbname=x host=localhost")


def test_bitt_serve_without_a_store_says_what_to_do(monkeypatch, capsys):
    from bitt import cli
    monkeypatch.delenv("BITT_DSN", raising=False)
    assert cli.main(["serve"]) == 2 and "bitt --dsn <dsn> serve" in capsys.readouterr().err


def test_a_run_that_skipped_its_smoke_run_shows_it(opener):
    """Owner 11-04 (SOP Q3): skip_smoke stays; which run skipped it is seen at a glance: a dashed layer behind its card."""
    from bitt.builtins import SHIPPED
    from bitt.tools.run import land
    k, c, t, x, raw = world(opener())
    ds = c("run.go", in_=x, recipe=recipe(c, x, "split", cols={"qid": "qid"}), on=[raw], as_="dataset", line="qa")["set"]
    for n in ("nb_train", "nb_predict"):
        c("module.define", in_=x, code=SHIPPED[n].read_bytes(), name=n)
    tr = recipe(c, x, "nb_train", cols={"text": "title", "label": "qid"})
    ev = recipe(c, x, "exact_match", cols={"a": "pred", "b": "tickets.qid"})
    land(k, c("run.go", in_=x, recipe=tr, on=[ds], evals=[ev], skip_smoke="yes", endpoint="nb_predict", line="clf")["job"])
    S, p = pages(k)
    lad = [r for st in S["tasks"][0]["cycles"][0]["ladder"] for r in st["rungs"] if r.get("skipped_smoke")]
    assert lad and "class='ly ghost'" in p[f"cycle {S['tasks'][0]['name']}#1"]


def test_a_smoke_run_folds_into_the_run_after_it_on_the_rail(opener):
    """Owner 11-04: on the rail a train's smoke run is a layer of the run after it (as the ladder stacks its rungs), not a line of its
    own; until that run comes, the smoke run keeps its line."""
    from test_train import setup
    from bitt.tools.run import land
    k, c, t, x, raw = world(opener())
    ds, tr, ev = setup(k, c, x, raw)
    land(k, c("run.go", in_=x, recipe=tr, on=[ds], evals=[ev], endpoint="nb_predict", line="clf")["job"])
    S, _ = pages(k)
    assert any("(smoke run)" in a["text"] for a in S["tasks"][0]["acts"]), "alone, the smoke run has its line"
    land(k, c("run.go", in_=x, recipe=tr, on=[ds], evals=[ev], endpoint="nb_predict", line="clf")["job"])
    S, p = pages(k)
    rail = S["tasks"][0]["acts"]
    trains = [a for a in rail if a["kind"] == "run" and "nb_train" in a["text"]]
    assert not any("(smoke run)" in a["text"] for a in rail), "the smoke run has no line of its own"
    assert len(trains) == 1 and "(smoke run)" in trains[0]["after"], "the run after it carries it"
    assert "stacked'" in p[f"task {S['tasks'][0]['name']}"], "drawn as a layer behind the run's dot"


def test_a_row_ladders_smoke_rung_folds_into_the_next_rung(opener):
    k, c, t, x, raw = world(opener())
    c("run.go", in_=x, recipe=recipe(c, x, "clean", cols={"text": "title"}), on=[raw])
    S, p = pages(k)
    runs = [a for a in S["tasks"][0]["acts"] if a["kind"] == "run"]
    assert len(runs) == 1 and runs[0].get("after"), "smoke (1 row) then the sample: one stacked line"


def test_a_step_is_one_stacked_box_in_the_graph_not_one_per_run(opener):
    """Owner 11-04: a train's smoke run and its full train are one step; the graph draws one box, stacked by its runs, as the card does."""
    from test_train import setup
    from bitt.tools.run import land
    k, c, t, x, raw = world(opener())
    ds, tr, ev = setup(k, c, x, raw)
    land(k, c("run.go", in_=x, recipe=tr, on=[ds], evals=[ev], endpoint="nb_predict", line="clf")["job"])
    land(k, c("run.go", in_=x, recipe=tr, on=[ds], evals=[ev], endpoint="nb_predict", line="clf")["job"])
    S, p = pages(k)
    nodes = [b for b in S["tasks"][0]["cycles"][0]["flow"]["nodes"] if b["label"].startswith("train")]
    assert len(nodes) == 1 and nodes[0]["rungs"] == 2, "one box for the train step: its smoke run and its full run stacked"


def test_a_rail_line_a_box_or_a_run_card_opens_its_node_in_the_inspector(opener):
    """Inspect (owner 11-06): every rail line, graph box and run card on a served page carries its node's full id; the drawer shows
    the node, what it links (with the role) and what links it (its history), and the SQL that reads the same. A snapshot has none."""
    k, c, t, x, raw = world(opener())
    run = c("run.go", in_=x, recipe=recipe(c, x, "clean", cols={"text": "title"}), on=[raw], full="yes")["run"]
    srv, base = serve(k)
    try:
        task = re.search(r"href='(/s/mine/t/[^']+)'", get(base + "/"))[1]
        cyc = re.search(r"href='(/s/mine/t/[^']+/c/\d+)'", get(base + task))[1]
        page = get(base + cyc)
        assert "id='ins'" in page and "data-url='/s/mine/n/__N__'" in page, "a served page has the drawer"
        ids = re.findall(r"data-n='([0-9a-f]+)'", page)
        assert ids and all(i in k.rec.nodes for i in ids), "each pick carries a full node id"
        assert re.search(rf"<li[^>]*data-n='{run}'", page), "the run's rail line opens it"
        assert re.search(rf"<g class='bx' data-n='{run}'", page), "the run's graph box opens it"
        assert re.search(rf"class='stk'[^>]*data-n='{run}'", page), "the run's card opens it"
        nodes = len(k.rec.nodes)
        d = get(base + f"/s/mine/n/{run[:12]}")                        # a prefix will do
        assert run in d and "<h2>links</h2>" in d and f"data-n='{raw}'" in d, "the run links its input, which opens in turn"
        assert re.search(r"<span class='r'>on</span><span>raw ", d), "each link says its role"
        import html
        assert "made from (tree)" in d and f"bitt.tree('{run}', 'up')" in html.unescape(d) and "its rows" in d, "the SQL for the node, its tree, its rows"
        r = get(base + f"/s/mine/n/{raw}")
        assert re.search(rf"<h2>linked by · \d+.*data-n='{run}'", r, re.S), "the raw import's history holds the run that read it"
        try:
            get(base + "/s/mine/n/0123456789abcdef")
            assert False, "an unknown node was answered"
        except urllib.error.HTTPError as e:
            assert e.code == 404
        assert len(k.rec.nodes) == nodes, "inspecting writes nothing"
    finally:
        srv.shutdown()
    _, p = pages(k)
    assert not any("data-n=" in pg or "id='ins'" in pg for pg in p.values()), "a snapshot has no server to ask, so nothing to pick"


def test_the_inspectors_sql_runs_on_the_store_and_reads_the_same_node(opener):
    """Every query the drawer offers is real SQL on a bitt store (the navigation functions every store has): the node query finds
    the node, the history query finds every node that links it, the rows query finds the run's rows."""
    from bitt.panel.data import inspect
    k, c, t, x, raw = world(opener())
    run = c("run.go", in_=x, recipe=recipe(c, x, "clean", cols={"text": "title"}), on=[raw], full="yes")["run"]
    kinds = {}
    for n in k.rec.nodes.values():
        kinds.setdefault(n["kind"], n["id"])
    if not hasattr(k.rec, "db"):
        d = inspect(k, run)
        assert [q for q, _ in d["sql"]][-1] == "its rows" and all(run in s for q, s in d["sql"] if q != "its rows")
        return
    for kind, nid in kinds.items():
        d = inspect(k, nid)
        for title, q in d["sql"]:
            with k.rec.db.transaction(force_rollback=True):
                got = k.rec.db.execute(q).fetchall()
            if title == "the node":
                assert len(got) == 1, (kind, title)
            if title == "history: what links it":
                assert len(got) >= d["n_history"], (kind, title)
            if title == "its rows":
                assert got, (kind, title)
    assert "its rows" in [q for q, _ in inspect(k, run)["sql"]]
