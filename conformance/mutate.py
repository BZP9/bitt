"""Mutation coverage of the contract (spec/cards): switch one rule off, run the suite; it must notice (an assert or a test fails: a
crash alone proves nothing). Exit 1 if any mutation survives or is stale.

  uv run python conformance/mutate.py [--only '<substring>|<substring>…'] [--fresh]      (BITT_BACKEND applies; memory by default)

Two kinds: every check switched to `pass` (BITT_MUTATE_OFF, conformance/mutant.py: the replays first, pytest when they miss), and
source patches (a copy of the repo with one rule changed: the replays, then the pytest selection named with it).

What caught each mutation (a replay or a test id) is kept in _output/mutate_killers.json: the next sweep runs that one first, and the
full path only when it no longer catches (one failing assert is enough; the baseline still runs whole). --fresh ignores it."""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPLAYS = ("replay_vk.py", "replay_gw.py")
PY = str(ROOT / ".venv" / "bin" / "python")
KILLERS = ROOT / "_output" / "mutate_killers.json"

# (file, old, new, pytest -k): one rule changed in a copy of the repo; the replays run, then pytest ("" = the whole suite)
SRC = {
    "an eval agent may file real bitt issues": ('evals/haiku/_store.py', '"BITT_ISSUES": "off",\n', '\n', "issue_reporting"),
    "an eval agent inherits the owner's store": ('evals/haiku/_store.py', 'if not k.startswith(("BITT_", "PG"))', '', "evals_store_never"),
    "a test may write the user's task folders": ('tests/conftest.py', '    monkeypatch.setenv("BITT_TASKS", str(tmp_path / "tasks"))', '    pass', "task_folders_pinned"),
    "an eval agent writes models into the owner's task folders": ('evals/haiku/_store.py', ', "BITT_TASKS": str(d / "tasks")}', '}', "evals_store_never"),
    "a model's files are deleted before the person check": ('spec/cards/artifact.yaml', "    summary: the call is a person's (actor usr)\n    reads: before\n",
        "    summary: the call is a person's (actor usr)\n", "removing_a_model"),
    "jobs clean deletes a running job": ('src/bitt/cli.py', '            running += 1\n            continue\n', '            running += 1\n', "jobs_clean"),
    "a model is copied into the job folder": ('src/bitt/tools/run.py', '        if p.get("at"):\n            dirs[role] = model_dir_in(eng, a, env)\n            continue\n', '', "model_place"),
    "a test may write the user's blob store": ('tests/conftest.py', '    monkeypatch.setenv("BITT_BLOBS", str(tmp_path / "blobs"))', '    pass', "blobs_pinned"),
    "an unknown name's hint names a command that does not exist": ('src/bitt/names.py', '. next: the names are listed by `bitt module list`, "',
        '. next: `bitt names` lists them; also `bitt module list`, "', ""),
    "a required ref's hint asks for text": ('src/bitt/kernel.py', '                how = (f"{flag} <the id of a', '                how = (f"{flag} \\"…\\"" or f"{flag} <the id of a', ""),
    "a module's first version is a person's": ('src/bitt/tools/tag.py', '        first = "major" if eng.node(target)["kind"] in ("dataset", "evalset") else "first"',
        '        first = "major"', ""),
    "a dataset's first version is an agent's": ('src/bitt/tools/tag.py', '        first = "major" if eng.node(target)["kind"] in ("dataset", "evalset") else "first"',
        '        first = "first"', ""),
    'a plan needs no way to judge': ('src/bitt/control.py', '    return ("pass", "data arms only: a person validates them") if not other else \\',
        '    return ("pass", "data arms only: a person validates them") if True else \\', ""),
    "an agent's plan counts unconfirmed": ('src/bitt/kernel.py', '        if not plan_confirmed(self, plan):\n            return (',
        '        if False:\n            return (', ""),
    'a reject leaves a plan confirmed': ('src/bitt/control.py', '    return bool(vs) and vs[-1]["payload"]["verdict"] == "approve"',
        '    return bool(vs)', ""),
    "a policy's rule may watch anything": ('src/bitt/control.py', '    if not e or e["kind"] != "maneuver":\n        return "fail", f"a policy\'s',
        '    if False:\n        return "fail", f"a policy\'s', ""),
    'an agent closes any working cycle': ('src/bitt/control.py', '    if o in ("close", "earlystop") and eng.node(s)["payload"].get("level") == "working" and not may_act(eng, s, a, o):',
        '    if False:', ""),
    'a revoked grant still counts': ('src/bitt/control.py', '        if any(at is None or r["seq"] < at for r in eng.kids(g["id"], role="grant", kind="revocation")):',
        '        if False:', ""),
    'a grant counts back in time': ('src/bitt/control.py', '        if at is not None and g["seq"] > at:\n            continue',
        '        if False:\n            continue', ""),
    'a grant may delegate anything': ('src/bitt/control.py', '    if not isinstance(acts, list) or not acts or any(a not in DELEGABLE for a in acts):',
        '    if not isinstance(acts, list) or not acts:', ""),
    "an ungranted agent's pass measures": ('src/bitt/kernel.py', '              and not (v["payload"]["verdict"] == "pass" and not',
        '              and not (False and not', ""),
    'the ladder is skipped (every run is the full set)': ('src/bitt/tools/run.py',
        '    return sorted({k for k in (1, *(() if full else (sample_rows,))) if k < n} | {n})', '    return [n]', "test_run"),
    "a call stops at the smoke rung (the kernel never climbs)": ('src/bitt/tools/run.py',
        '    return {"run": run_n, "climb": k == 1 and k < n and not errors and not check_all}', '    return {"run": run_n, "climb": False}', "test_run"),
    "a failed smoke rung climbs on to the sample": ('src/bitt/tools/run.py',
        '    return {"run": run_n, "climb": k == 1 and k < n and not errors and not check_all}',
        '    return {"run": run_n, "climb": k == 1 and k < n and not check_all}', "test_run"),
    "the recipe's sample size is ignored": ('src/bitt/tools/run.py',
        '    return int(eng.node(recipe)["payload"].get("sample_rows") or SAMPLE_ROWS)', '    return SAMPLE_ROWS', "test_run"),
    'made outputs are made again (no keyed reuse)': ('src/bitt/tools/run.py', '        if rec.get_row(out_t, (key,)) is not None or key in queued:',
        '        if key in queued:', ""),
    "names ignore the input's kind": ('src/bitt/names.py', 'want = [m for m in ms if (any(lint.kind_matches(k, m["kind"]) for k in kinds) if kinds else family(m["kind"]) == fam)]',
        'want = [m for m in ms if family(m["kind"]) == fam]', ""),
    'group leak reads the row only (not its lineage)': ('src/bitt/tools/rules.py', '        for ut, u in w.rows_up(t, m):',
        '        for ut, u in [(t, m)]:', ""),
    'a short name falls through to other tasks': ('src/bitt/names.py', '    elif task:                               # the task',
        '    elif False:                              # the task', ""),
    'a job may finish twice': ('src/bitt/jobs.py', 'if [x for x in eng.kids(ctx["job"], role="job", kind="event") if x["id"] != ctx["_event"]\n',
        'if False and [x for x in eng.kids(ctx["job"], role="job", kind="event") if x["id"] != ctx["_event"]\n', ""),
    'unknown inputs accepted': ('src/bitt/kernel.py', 'if k not in mins and k not in opts and not k.startswith("_"):',
        'if False:', ""),
    'a list accepted for a single ref': ('src/bitt/kernel.py', 'if isinstance(v, list) and not spec.get("many"):',
        'if False:', ""),
    'warnings point at the output': ('src/bitt/kernel.py', 'target = (list(subj) if isinstance(subj, tuple) else subj) if effect == "warn" else main',
        'target = main', ""),
    'iterate keeps the old plans': ('src/bitt/kernel.py', 'since = max([o["seq"] for o in outs if o["payload"]["outcome"] == "iterate"], default=-1)',
        'since = -1', ""),
    'retired policies still apply': ('src/bitt/kernel.py', 'return [p for p in self.rec.find("policy") if not self.kids(p["id"], role="policy", kind="policy_retired")]',
        'return self.rec.find("policy")', ""),
    'internal cards callable by anyone': ('src/bitt/kernel.py', 'if e["kind"] == "internal":',
        'if False:', ""),
    'abstract cards callable': ('src/bitt/kernel.py', 'if e["kind"] not in ("maneuver", "internal"):',
        'if False:', ""),
    'a reject does not revoke': ('src/bitt/control.py', 'if vs and vs[-1]["payload"]["verdict"] == "approve":',
        'if any(v["payload"]["verdict"] == "approve" for v in vs):', ""),
    'the first verdict decides an arm, not the latest': ('src/bitt/kernel.py', '            if v["payload"]["verdict"] not in ("pass", "approve"):\n                break',
        '            if False:\n                break', ""),
    "a verdict older than the arm's measurement counts": ('src/bitt/kernel.py', 'newest = max([plan["seq"]] + [self.arm_measure(a, plan)[1] or 0 for a in as_list(plan["links"].get("arms"))])',
        'newest = plan["seq"]', ""),
    'a running job does not hold its arm': ('src/bitt/kernel.py', '        if self.running_job(arm):\n            return "running", None              # more is landing',
        '        if False:\n            return "running", None              # more is landing', ""),
    'a closed goal leaves its cycles open': ('src/bitt/kernel.py', 'if any(o in ("close", "abandon") for a in self.ancestors(nid) for o in self.outcomes(a)):',
        'if False:', ""),
    'judgments count across tasks': ('src/bitt/kernel.py', 'vs = [v for v in self.kids(fill, role="subject", kind="validation") if self.task_of(v["id"]) == task\n',
        'vs = [v for v in self.kids(fill, role="subject", kind="validation") if True\n', ""),
    'acks from any task count': ('src/bitt/kernel.py', 'and (task is None or self.task_of(a["id"]) == task):',
        ':', ""),
    'a rejected job does not fail its arm': ('src/bitt/kernel.py', 'self.job_status(jobs[-1]["id"]) in ("failed", "rejected")',
        'self.job_status(jobs[-1]["id"]) == "failed"', ""),
    'actor kinds unchecked': ('src/bitt/kernel.py', 'if not re.fullmatch(r"usr(:[\\w.-]+)?|agent:[\\w.-]+|system|pipeline:\\w+|policy:\\w+", actor):',
        'if False:', ""),
    'text patterns unchecked (aliases)': ('src/bitt/kernel.py', 'if spec.get("pattern") and not re.fullmatch(spec["pattern"], str(v)):',
        'if False:', ""),
    "another task's approval opens the gate": ('src/bitt/control.py', 'and eng.task_of(n["id"]) == gate_task]',
        ']', ""),
    "the approver's authority comes from the subject's task": ('src/bitt/control.py', 'authority(eng, scope.get("in") or s)',
        'authority(eng, s)', ""),
    'names are not checked': ('src/bitt/kernel.py', 'if spec.get("pattern") and not re.fullmatch(',
        'if False and not re.fullmatch(', ""),
    'NaN is stored': ('src/bitt/hashing.py', 'if obj != obj or obj in (float("inf"), float("-inf")):',
        'if False:', ""),
    'NUL is stored': ('src/bitt/hashing.py', 'if "\\x00" in obj:',
        'if False:', ""),
    'integral floats stay floats': ('src/bitt/hashing.py', 'return int(obj) if obj.is_integer() else obj',
        'return obj', ""),
    "an impl sets a nested call's actor": ('src/bitt/kernel.py', 'else self._actors[-1]',
        'else actor', ""),
    'an impl names its own DAG caller': ('src/bitt/kernel.py', 'caller = self.eff[parent]["tool"]',
        'pass', ""),
    'an impl may add any link': ('src/bitt/kernel.py', 'bad = [r for r in extra if r not in lint.IMPL_ROLES]',
        'bad = []', ""),
    'an impl may return an old node': ('src/bitt/kernel.py', 'if v not in new:\n                raise Failed',
        'if False:\n                raise Failed', ""),
    'a broken finish handler leaves the job running': ('src/bitt/kernel.py', 'and (getattr(x, "deferred", False) or isinstance(x, Failed)):',
        'and getattr(x, "deferred", False):', ""),
    'a caught nested refusal is committed': ('src/bitt/kernel.py', "self.rec.drop_since(pmark)          # this call's part",
        "pass                                # this call's part", ""),
    'Postgres TRUNCATE allowed on data tables': ('src/bitt/tables.py', 'sql.SQL("CREATE TRIGGER no_truncate BEFORE TRUNCATE ON {} FOR EACH STATEMENT EXECUTE FUNCTION bitt.refuse_change()")',
        'sql.SQL("COMMENT ON TABLE {} IS NULL")', ""),
    'Postgres TRUNCATE allowed': ('src/bitt/sql/postgres.sql', "EXECUTE format('CREATE TRIGGER no_truncate",
        "PERFORM format('CREATE TRIGGER no_truncate", ""),
    'a free column needs no reason': ('src/bitt/record/memory.py', 'if new["kind"] == "free" and not new["origin"].get("reason"):',
        'if False:', ""),
    'a column may be retyped': ('src/bitt/tools/data.py', 'elif have[c["name"]]["type"] != c["type"]:',
        'elif False:', ""),
    'NULL keys are hashed': ('src/bitt/hashing.py', 'return {k: v for k, v in d.items() if v is not None}',
        'return dict(d)', ""),
    'text is not normalized': ('src/bitt/hashing.py', 'return unicodedata.normalize("NFC", v.replace("\\r\\n", "\\n").replace("\\r", "\\n"))',
        'return v', ""),
    'a line name may hold `__`': ('src/bitt/tables.py', '    check_name(base)\n    if not re.fullmatch(SUFFIX',
        '    pass\n    if not re.fullmatch(SUFFIX', ""),
    'line names are not length-limited': ('src/bitt/tables.py', 'or len(name) > MAX_NAME',
        '', ""),
    'integral floats ≥ 2^63 stay floats': ('src/bitt/hashing.py', 'return int(obj) if obj.is_integer() else obj',
        'return int(obj) if obj.is_integer() and abs(obj) < 2 ** 63 else obj', ""),
    'int columns take any size': ('src/bitt/hashing.py', '        if not -2 ** bits <= int(v) < 2 ** bits:',
        '        if False:', ""),
    'a vector of the wrong length is stored': ('src/bitt/hashing.py', '        if len(v) != dim:',
        '        if False:', ""),
    'timestamps lose digits silently': ('src/bitt/hashing.py', 'if not isinstance(v, _dt.datetime) and re.search(',
        'if False and re.search(', ""),
    'a date column takes a timestamp': ('src/bitt/hashing.py', '        if isinstance(v, _dt.datetime):\n            raise ValueError(f"bitt: {v!r} is a timestamp',
        '        if False:\n            raise ValueError(f"bitt: {v!r} is a timestamp', ""),
    'the registry keeps a redeclared column silently': ('src/bitt/record/memory.py', '            if (old["type"], old["kind"]) != (c["type"], c.get("kind", "free")):',
        '            if False:', ""),
    'column types are not validated': ('src/bitt/tables.py', 'def check_type(t):\n',
        'def check_type(t):\n    return t\n', ""),
    'a failed refusal write escapes': ('src/bitt/kernel.py', '        except Exception as e:                  # the store refuses this write too',
        '        except ZeroDivisionError as e:          # the store refuses this write too', ""),
    'foreign keys are not checked on insert': ('src/bitt/record/memory.py', '            if not self._exists(target, dict(zip(b, vals))):',
        '            if False:', ""),
    'part is not in the output key': ('src/bitt/hashing.py', '{"recipe": recipe, "in": in_h, "sample": sample, "part": part}',
        '{"recipe": recipe, "in": in_h, "sample": sample}', ""),
    'localhost spellings are different servers': ('conformance/backend.py', '    local = {None, "", "localhost", "127.0.0.1", "::1"}',
        '    local = {None}', ""),
    'file bytes are hashed by their repr': ('src/bitt/kernel.py', 'text_hash(v if isinstance(v, (str, bytes)) else canonical(v).decode())',
        'text_hash(v if isinstance(v, str) else canonical(v).decode())', ""),
    'tests may use port 5432': ('conformance/backend.py', '    if str(d.get("port") or "5432") == "5432":',
        '    if False:', ""),
    'any event on a job ends it': ('src/bitt/jobs.py', '            and x["payload"].get("card") == "exec.job.finish"]:',
        '            ]:', ""),
    'the ssh launch needs setsid': ('src/bitt/tools/envs.py', 'detach = "S=$(command -v setsid || true); "',
        'detach = "S=setsid; "', ""),
    'company data may go to any env': ('src/bitt/tools/envs.py', '    if SENSITIVITY.index(sensitivity) > SENSITIVITY.index(top):',
        '    if False:', ""),
    'the MPS guard is off': ('src/bitt/tools/envs.py', '            if code == 0 and out.strip():',
        '            if False:', ""),
    'a module without a complete header is accepted': ('src/bitt/tools/artifact.py', 'return "fail", problem',
        'pass', ""),
    'a set ignores its order': ('src/bitt/sets.py', 'h("set", canonical([list(m) for m in members]))',
        'h("set", canonical(sorted([list(m) for m in members], key=str)))', ""),
    'a set may list a row twice': ('src/bitt/sets.py', 'if kind not in REPEATS and len({m[0] for m in members}) != len(members):',
        'if False:', ""),
    'a prefix of a prefix is not flattened': ('src/bitt/sets.py', 'while rec.get_row("bitt.set", (root,))["parent"]:',
        'while False:', ""),
    'links over several tables are not checked': ('src/bitt/sets.py', 'if not spec["fks"]:',
        'if False:', ""),
    'a smoke, failed or train run fills an arm': ('src/bitt/kernel.py', 'if f["kind"] not in ("event", "ruling", "warning") and not self._no_fill(f)]',
        'if f["kind"] not in ("event", "ruling", "warning")]', ""),
    'a label with `:` is not read where any kind is taken': ('src/bitt/tools/recipe.py', 'and ":" not in ref:   # `:` is never in a name: a label',
        'and True:', ""),
    "a label drops its hash": ('src/bitt/tools/recipe.py', '''    return f"{base_of(eng, recipe)}:{eng.node(recipe)['spec_h'][:8]}"''',
        '    return base_of(eng, recipe)', "test_recipe"),
    "an undeclared column fails its row again": ('src/bitt/tools/run.py', '            lack = sorted({c for _, _, miss in split for c in miss})',
        '            lack = sorted({c for _, more, miss in split for c in [*miss, *(more or {})]})', "test_run"),
    "an older store opens without a migration": ('src/bitt/storeformat.py', '    if have and have < want["format"] and not migrating:',
        '    if False:', "test_storeformat"),
    "a dev tree syncs its skills on every command": ('src/bitt/skills.py', '    return sync(source=RELEASE) if RELEASE.exists() else []',
        '    return sync(source=RELEASE if RELEASE.exists() else SOURCE)', "test_skillsync"),
    "inspect --task shows every row": ('src/bitt/cli.py', '        ms = [(m, sp) for m, sp in ms if m in mine]', '        ms = ms', "test_cli"),
    "a report row is keyed by its step only (a smoke's numbers stand for the full train's)": ('src/bitt/tools/run.py',
        'rec.insert(t, {"bitt_row_hash": h("report", canonical({"run": run_n, "step": step})), "bitt_in_hash": ih,',
        'rec.insert(t, {"bitt_row_hash": h("report", canonical({"step": step})), "bitt_in_hash": ih,', "test_train"),
    "a wrap with its prompt fixed is no connector": ('src/bitt/tools/run.py',
        '    return recipes.artifacts(eng, recipe).get("prompt") if h_["kind"] == "generate" and not h_["reads"] else None',
        '    return recipes.artifacts(eng, recipe).get("prompt") if "prompt" in h_["roles"] and not h_["reads"] else None', "test_run"),
    # D15 (docs/v2/d15.md): every run counts per unit; a win reads one row; a train reports what it declares
    "a row reads the first hit above it, not its own unit's chain": ('src/bitt/tools/run.py', '    ch = chain(eng, ref, i, memo)\n    rows = ',
        '    ch = chain(eng, ref, i, memo)[:1]\n    rows = ', "test_units"),
    "a made row links only its input row": ('src/bitt/tools/run.py', 'for t, r in dict.fromkeys([(in_t, m), *read]):',
        'for t, r in dict.fromkeys([(in_t, m)]):', "test_units"),
    "a run's output set refuses a row twice": ('src/bitt/sets.py', 'REPEATS = ("run_out",)', 'REPEATS = ()', "test_units"),
    "a win reads a run with several rows": ('src/bitt/tools/run.py', '    if len(ms) != 1:\n        return None',
        '    if not ms:\n        return None', "test_units"),
    "an undeclared reported name is accepted": ('src/bitt/tools/run.py', '        if extra := sorted(k for k in r if k not in declared):',
        '        if extra := []:', "test_units"),
    # several named inputs (docs/v2/inputs.md, J1): a join keeps the units, refuses a repeated key, links and hashes what it read
    "a join's rows are new units": ('src/bitt/tools/run.py', '        out.append((key_, sp, i))', '        out.append((key_, sp, None))',
        "test_join"),
    "a repeated lookup key is accepted": ('src/bitt/tools/run.py', '    if twice := [(k_, len(v)) for k_, v in by.items() if len(v) > 1]:',
        '    if twice := []:', "test_join"),
    "a joined row does not link the lookup rows it read": ('src/bitt/tools/run.py',
        '                read.append((line_table(eng, reads[role], memo), hit[0]))\n                read += hit[2]', '                pass',
        "test_join"),
    "a joined row is keyed without its picked values": ('src/bitt/tools/run.py', '        ih = in_hash({"src": {"key": key_vals, **vals}})',
        '        ih = in_hash({"src": {"key": key_vals}})', "test_join"),
    "a derive takes a read input": ('src/bitt/tools/run.py',
        '    if ctx.get("read") and h_["kind"] not in ("join", "pipeline", "union") and not named:', '    if False:', "test_join"),
    # J3: named table inputs, the shipped union
    "a union keeps a duplicate twice": ('src/bitt/tools/run.py', '            k_ = canonical([row.get(c) for c in key])',
        '            k_ = canonical([t, m])', "test_union"),
    "a union row links only its first source": ('src/bitt/tools/run.py', '        for t, m in dict.fromkeys(srcs):', '        for t, m in srcs[:1]:',
        "test_union"),
    "a union takes an input without the units' columns": ('src/bitt/tools/run.py',
        '        if lack := [c for c in cols if c not in {x["name"] for x in rec.spec(t)["columns"]}]:', '        if lack := []:', "test_union"),
    "a named input is not required": ('src/bitt/tools/run.py', '    if named and sorted(ctx.get("read") or {}) != sorted(named):',
        '    if False:', "test_union"),
    # #3: contamination by what the model saw
    "contamination compares rows by identity only": ('src/bitt/tools/rules.py',
        '        both, same = units(w.seen(m)) & units(read), ([] if made_from_data else same_content(eng, m, run))',
        '        both, same = units(w.seen(m)) & units(read), []',
        "test_judge"),
    "content is compared without normalizing": ('src/bitt/tools/rules.py',
        '    return " ".join(str(v).lower().split()) if v is not None else None', '    return str(v) if v is not None else None', "test_judge"),
    "the model's test side counts as seen": ('src/bitt/tools/rules.py', '    seen = seen_values(eng, trains[0], {r: tcols[r] for r in roles}, skip_test=True)',
        '    seen = seen_values(eng, trains[0], {r: tcols[r] for r in roles}, skip_test=False)', "test_judge"),
    # W5: SQL walks like the walker
    "SQL downstream follows story links": ('src/bitt/sql/postgres_nav.sql',
        '    SELECT l.child, down.depth + 1 FROM bitt.link l JOIN down ON l.parent = down.id\n    WHERE l.lineage\n',
        '    SELECT l.child, down.depth + 1 FROM bitt.link l JOIN down ON l.parent = down.id\n', "test_walk"),
    # #9: the sorted roles
    "a finding is made from what it is about": ('spec/cards/base.yaml', "    made_from: [parent, set]                                          # a version's parent rows, the set an exclude acts on (#9, 11-03)\n    story: [in, origin, because, evidence, fills, resolving, supersedes, subject, ruling, against, line, target, replaces, during, evals, grant, judged,\n            about, agreement,",
        "    made_from: [parent, set, about]                                          # a version's parent rows, the set an exclude acts on (#9, 11-03)\n    story: [in, origin, because, evidence, fills, resolving, supersedes, subject, ruling, against, line, target, replaces, during, evals, grant, judged,\n            agreement,", "test_walk"),
    "a version is not made from its parent": ('spec/cards/base.yaml', '    made_from: [parent, set]', '    made_from: [set]', "test_walk"),
    # W4 / #8: artifacts made from data
    "an artifact made from data saw nothing": ('src/bitt/walk.py',
        '        if p.get("set") and self.links(artifact, "run"):         # made from data (W4): exactly the rows picked, any split',
        '        if False:', "test_judge"),
    "only models are checked for what they saw": ('src/bitt/tools/rules.py',
        '    return [a for a in recipes.artifacts(eng, recipe).values() if w.links(a, "run")]',
        '    return models_of(eng, recipe)', "test_judge"),
    "an artifact from data needs no kind": ('src/bitt/tools/run.py', '    if not kind:\n        raise Refused("run.go: an artifact made from data names its kind',
        '    if False:\n        raise Refused("run.go: an artifact made from data names its kind', "test_judge"),
    # owner 11-04: a wrap pins data; an eval that pins its evalset judges every arm on it; samples are the recipe's
    "a pinned wrap runs on anything": ('src/bitt/tools/run.py', '    if not pins:\n        return "pass", "pins nothing"',
        '    if True:\n        return "pass", "pins nothing"', "test_pin"),
    "an arm of a pinned eval runs on another version": ('src/bitt/tools/run.py',
        '    if (p := pins_of(eng, plan["links"]["pipeline"]).get("on"))', '    if False and (p := pins_of(eng, plan["links"]["pipeline"]).get("on"))',
        "test_pin"),
    "a changed pin is a minor": ('src/bitt/tools/tag.py', ' and pins[0] == pins[1] else "major"', ' else "major"', "test_pin"),
    "a wrap of a wrap re-pins a role": ('src/bitt/tools/module.py',
        '    if again := sorted(set(n["payload"]["fixed"].get("pin") or {}) & set(pins_of(eng, n["links"]["wraps"]))):',
        '    if again := []:', "test_pin"),
    "the run decides the samples": ('src/bitt/tools/run.py', '    return int(eng.node(recipe)["payload"].get("samples") or 1)',
        '    return 1', "test_pin"),
    "more samples redo the asks already made": ('src/bitt/record/memory.py', '            "out", "samples", "sample_rows"}', '            "out", "sample_rows"}', "test_pin"),
    "a recipe's sample size makes it another work": ('src/bitt/record/memory.py', '            "out", "samples", "sample_rows"}', '            "out", "samples"}', "test_run"),
    # owner 11-04: a claim stands on versions; a working arm an eval judges runs on versions
    "a version may cite evidence over unversioned data": ('src/bitt/tools/tag.py',
        '    loose = not_a_version(eng, evidence_stands_on(eng, s, [*as_list(scope.get("because")), *as_list(scope.get("agreement"))]))',
        '    loose = []', "test_tag"),
    "a dataset's version is refused for the raw it is made from": ('src/bitt/tools/tag.py',
        '    own = eng.lineage(target) | {target}', '    own = {target}', "test_tag"),
    "a working arm an eval judges may run on a raw import": ('src/bitt/tools/run.py',
        '    if loose := not_a_version(eng, dict.fromkeys(stands)):', '    if loose := []:', "test_pipeline"),
    # #4: another task's data
    "another task's unversioned input is silent": ('src/bitt/tools/run.py',
        '        if t and t != task and not (eng.node(x)["kind"] in ("dataset", "evalset") and names.version_of(eng, x)):',
        '        if False:', "test_cross_task"),
    "a version may be made from another task's unversioned data": ('src/bitt/tools/tag.py',
        '        if hit := other_task_loose(eng, task, [*w.links(r, "on"), *w.links(r, "read")]):',
        '        if hit := []:', "test_cross_task"),
    "an agent's proposed plan is judged before the approve": ('src/bitt/tools/pipeline.py',
        '        if not plan or not plan["links"].get("pipeline") or not eng.plan_confirmed(plan):',
        '        if not plan or not plan["links"].get("pipeline"):', "test_pipeline"),
    "the approve of an agent's plan leaves its filled arms unjudged": ('src/bitt/tools/pipeline.py',
        '        return on_approval(eng, out.get("validation"))', '        return None', "test_pipeline"),
    "a check by hand in a working cycle reads as the plan's verdict": ('src/bitt/tools/run.py',
        """    return "fail", "a check run outside the plan's eval: its verdicts are a hint, never this cycle's result\"""",
        """    return "pass", "x\"""", "test_pipeline"),
    "the panel draws another task's input as ours": ('src/bitt/panel/data.py', '    if (t := k.task_of(nid)) and t != task:', '    if False:',
        "test_panel"),
    "the panel's arrow from a --read input names no role": ('src/bitt/panel/data.py',
        """                        fed[(rep.get(i, i), x)] = f"{role}: {few(cols_fed(k, n['id'], role))}\"""",
        """                        fed[(rep.get(i, i), x)] = \"\"""", "test_panel"),
    "an input made in another cycle has no box for it": ('src/bitt/panel/data.py',
        '            if h and h not in cset and h != task_home and x not in made_here:', '            if False:', "test_panel"),
    "the panel opens a store writable": ('src/bitt/panel/serve.py', '" -c default_transaction_read_only=on"', '""', "test_panel"),
    "an open panel page never asks its store's seq": ('src/bitt/panel/view.py',
        '    live = live_js(L.seq, seq) if L.seq else ""', '    live = ""', "test_panel"),
    "the live ring scales with what changed (a wide row balloons)": ('src/bitt/panel/view.py',
        '@keyframes halo{0%{outline:2px solid var(--vio);outline-offset:0}100%{outline:2px solid transparent;outline-offset:6px}}',
        '@keyframes halo{0%{outline:2px solid var(--vio);transform:scale(.9)}100%{outline:2px solid transparent;transform:scale(1.35)}}', "test_panel"),
    "a new row flashes forever": ('src/bitt/panel/view.py', '.pulse{animation:halo 1.4s ease-out 3}', '.pulse{animation:halo 1.4s ease-out infinite}',
        "test_panel"),
    "a served page hides its last check": ('src/bitt/panel/view.py', '    return CHK + LIVE_JS.replace(', '    return LIVE_JS.replace(', "test_panel"),
    "a model saw every unit a shared row ever linked (the fan-out through a joined profile)": ('src/bitt/walk.py',
        '                out |= self.units_in(self.links(run, "on")[0], {m for _, m, _ in self.set_rows(sh)}, skip_test=True)',
        '                out |= {u for _, m, _ in self.set_rows(sh, skip_test=True) for u in self.rows_up(self.rec.get_row("bitt.set", (sh,))["tbl"], m)}',
        "test_judge"),
    "a load need not say what the data is": ('spec/cards/data.yaml',
        "        does: {type: text}             # what the data is, in one sentence (a module's `does` for data): how it is found later\n", "",
        "test_types or test_cli"),
    "data list finds no line by what it is for": ('src/bitt/cli.py', '    hay = lambda it: " ".join([it["line"], it["does"], it["source"],',
        '    hay = lambda it: " ".join([it["line"], it["source"],', "test_cli"),
    "the inspector hides what links a node (its history)": ('src/bitt/panel/data.py', '    kids = k.kids(nid)', '    kids = []', "test_panel"),
    "a snapshot offers picks no server answers": ('src/bitt/panel/view.py', 'return f" data-n=\'{e(nid)}\'" if L.node and nid else ""',
        'return f" data-n=\'{e(nid)}\'" if nid else ""', "test_panel"),
    "the inspector offers no SQL for a run's rows": ('src/bitt/panel/data.py', '    if sh and (q := rows_sql(k, sh)):', '    if False:', "test_panel"),
    "an empty store's home is a blank page": ('src/bitt/panel/view.py',
        '''    lanes = lanes or ["<div class='lane'><div class='nm mute'>no task yet</div></div>"]''', '    lanes = lanes', "test_panel"),
    "a smoke run keeps its own rail line after its run came": ('src/bitt/panel/data.py',
        '        elif (s := last_smoke.pop(key[n["id"]], None)) is not None:', '        elif False:', "test_panel"),
    "a row ladder's smoke rung keeps its own rail line": ('src/bitt/panel/data.py',
        '        if p.get("smoke") or (p.get("rung") == 1 and (p.get("of") or 0) > 1):', '        if p.get("smoke"):', "test_panel"),
    "a train's smoke run draws as its own graph box": ('src/bitt/panel/data.py',
        '    return (key[0], key[1], key[3])', '    return (key[0], key[1], key[2], key[3])', "test_panel"),
    "the eval list re-reads every store on every load": ('scripts/viz_serve.py',
        '    if g is not None and key in CACHE and CACHE[key][0] == g:', '    if False:', "test_panel"),
    "bitt_from [role, index] links the units' row": ('src/bitt/tools/run.py', '            out.add((t, ro[i][1]))', '            out.add((in_t, rs[i][1]))',
        "test_union"),
    "a pipeline drops its read inputs": ('src/bitt/tools/pipeline.py', '        self.read = dict(ctx.get("read") or {})', '        self.read = {}',
        "test_join"),
    # J2: many rows per key, as of the unit's time
    "asof reads a row at the unit's own time": ('src/bitt/tools/run.py', 'x[1][asof[role][0]] < t_]', 'x[1][asof[role][0]] <= t_]',
        "test_join"),
    "asof reads the future": ('src/bitt/tools/run.py',
        '                    hits = [x for x in hits if t_ is not MISSING and t_ is not None and x[1][asof[role][0]] < t_]',
        '                    hits = list(hits)', "test_join"),
    "a many role with no row is silent": ('src/bitt/tools/run.py', '                empty[role] += not hits', '                pass', "test_join"),
    "a select over shared rows gives the bare set error": ('src/bitt/tools/run.py',
        '    if (shared := len({m for m, _ in chosen})) < len(chosen):', '    if False:', "test_join"),
    # the walker (docs/v2/walk.md, W1): one role registry, lineage follows every input
    "a run's read inputs are story": ('spec/cards/base.yaml', 'policy, prev, want, ref, rule]', 'policy, prev, want, ref, rule, read]', "test_walk"),
    "a role in two classes is accepted": ('src/bitt/cards.py',
        '                    errors.append(f"role {r} is in two role classes ({was}, {klass}): a role means one thing")', '                    pass',
        "test_walk"),
    "a card's link role in no class is accepted": ('src/bitt/cards.py',
        '                    errors.append(f"{cid}.{name}: link role {name} is in no role class (base.yaml roles)")', '                    pass',
        "test_walk"),
    "the walker walks story links up": ('src/bitt/walk.py',
        '            if (role in lint.STORY_ROLES) == story and (via is None or lint.role_class(role) in via):',
        '            if via is None or lint.role_class(role) in via:', "test_walk"),
    # W2: the rules ask the walker; the data path follows every input
    "the data path skips a run's read inputs": ('src/bitt/walk.py', 'DATA_PATH = ("units", "reads")', 'DATA_PATH = ("units",)', "test_judge"),
    # W3: the run tool reads through the walker
    "the walker ignores an open person run's answers": ('src/bitt/walk.py', '                if got is None and not e and self.open_run:',
        '                if False:', ""),
    "a model saw its test members too": ('src/bitt/walk.py',
        '                out |= self.units_in(self.links(run, "on")[0], {m for _, m, _ in self.set_rows(sh)}, skip_test=True)',
        '                out |= self.units_in(self.links(run, "on")[0], {m for _, m, _ in self.set_rows(sh)}, skip_test=False)', "test_judge"),
    "many reads only the first matching row": ('src/bitt/tools/run.py', '                hits = index[role].get(key, [])',
        '                hits = index[role].get(key, [])[:1]', "test_join"),
}

def checks():
    sys.path.insert(0, str(ROOT / "conformance"))
    sys.path.insert(0, str(ROOT / "src"))
    from backend import make_kernel
    return sorted(make_kernel("mutate_list").rules)


def env_for(work, off=None):
    env = {**os.environ, "PYTHONPATH": str(work / "src")}
    env.pop("BITT_MUTATE_OFF", None)
    return {**env, "BITT_MUTATE_OFF": off} if off else env


def replays(work, off=None, only=REPLAYS):
    """(caught by, crashed): a ✗ line or a refusal / failure escaping the story is a catch; any other crash proves nothing."""
    caught, crash = [], False
    for replay in only:
        r = subprocess.run([PY, f"conformance/{replay}"], capture_output=True, text=True, cwd=work, env=env_for(work, off))
        if "  ✗ " in r.stdout or (r.returncode != 0 and ("bitt.errors.Refused" in r.stderr or "bitt.errors.Failed" in r.stderr)):
            caught.append(replay.removeprefix("replay_").removesuffix(".py"))
        elif r.returncode != 0:
            crash = True
    return caught, crash


def pytest(work, off=None, sel=None, ids=("tests",)):
    """('caught', the failing test's id) when a test fails, 'none' when every selected test passes, 'no test' when nothing ran."""
    r = subprocess.run([PY, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", *ids, *(["-k", sel] if sel else [])],
                       capture_output=True, text=True, cwd=work, env=env_for(work, off))
    if " failed" in r.stdout:
        return "caught", (re.findall(r"^FAILED (.+?)(?: - .*)?$", r.stdout, re.M) or [None])[0]
    return ("none" if " passed" in r.stdout else "no test"), None


def verdict(work, off=None, sel="", killer=None):
    """(verdict, what caught it). A known killer runs alone first; the full path only when it no longer catches."""
    if killer in REPLAYS and replays(work, off, only=(killer,))[0]:
        return "caught by " + killer.removeprefix("replay_").removesuffix(".py"), killer
    if killer and killer.startswith("tests/") and pytest(work, off, ids=(killer,))[0] == "caught":
        return "caught by pytest", killer
    caught, crash = replays(work, off)
    if caught:
        return "caught by " + "+".join(caught), f"replay_{caught[0]}.py"
    if sel is not None:
        got, test = pytest(work, off, sel or None)
        if got == "caught":
            return "caught by pytest", test
        if got == "no test":
            return "NO TEST", None
    return ("SURVIVED (crash only)" if crash else "SURVIVED"), None


def copy():
    work = ROOT / "_output" / "mutant"
    shutil.rmtree(work, ignore_errors=True)
    shutil.copytree(ROOT, work, ignore=shutil.ignore_patterns(".git", ".venv", ".pg", "_output", "_report", "__pycache__", "_store"))
    return work


if __name__ == "__main__":
    only = sys.argv[sys.argv.index("--only") + 1].split("|") if "--only" in sys.argv else []
    want = lambda name: not only or any(o in name for o in only)  # noqa: E731
    backend = os.environ.get("BITT_BACKEND", "memory")
    try:
        killers = {} if "--fresh" in sys.argv else json.loads(KILLERS.read_text()).get(backend, {})
    except (OSError, ValueError):
        killers = {}
    found = {}
    caught, crash = replays(ROOT)
    if caught or crash or pytest(ROOT)[0] != "none":
        print(f"BASELINE FAILS (replays {caught or 'crashed' if crash else 'ok'}): the unmutated suite must pass first")
        sys.exit(2)
    results = []
    for c in checks():
        name = f"{c} always passes"
        if want(name):
            v, found[name] = verdict(ROOT, off=c, killer=killers.get(name))
            results.append((name, v))
            print(f"{results[-1][1]:<28} {name}", flush=True)
    for name, (f, old, new, sel) in SRC.items():
        if not want(name):
            continue
        work = copy()
        src = (work / f).read_text()
        if src.count(old) != 1:
            results.append((name, "STALE"))
        else:
            (work / f).write_text(src.replace(old, new))
            v, found[name] = verdict(work, sel=sel, killer=killers.get(name))
            results.append((name, v))
        print(f"{results[-1][1]:<28} {name}", flush=True)
    try:
        saved = json.loads(KILLERS.read_text())
    except (OSError, ValueError):
        saved = {}
    saved[backend] = {**killers, **found}
    KILLERS.parent.mkdir(exist_ok=True)
    KILLERS.write_text(json.dumps(saved, indent=1, sort_keys=True))
    bad = [n for n, v in results if not v.startswith("caught")]
    print(f"\n{len(results) - len(bad)}/{len(results)} mutations caught (survivors: {bad or 'none'})")
    sys.exit(1 if bad else 0)
