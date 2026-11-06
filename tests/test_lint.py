"""Lint enforces the card grammars the contract states (when, subjects, cache, deferred, open_in, named sets)."""
import pytest

from bitt import cards

ANCHOR = '{rule: control.can_approve, subject: subject, when: "verdict in [approve, reject]", on_fail: refuse}'


def planted(tmp_path, path, old, new):
    files = cards.default_files()
    f = next(x for x in files if x.as_posix().endswith(path))
    text = f.read_text()
    assert old in text, "the planting anchor moved"
    p = tmp_path / f.name
    p.write_text(text.replace(old, new, 1))
    return cards.lint_report(cards.load([x for x in files if x != f] + [p]))


@pytest.mark.parametrize("old, new, expect", [
    ('when: "verdict in [approve, reject]"', 'when: "fills > 3 or eval(x)"', "not in the grammar"),
    ("subject: subject, when", 'subject: "target..[[weird", when', "not in the grammar"),
    ('when: "verdict in [approve, reject]"', 'when: "verdict in no_such_set"', "no_such_set"),
])
def test_planted_card_errors_are_caught(tmp_path, old, new, expect):
    report = planted(tmp_path, "spec/cards/control.yaml", ANCHOR, ANCHOR.replace(old, new))
    assert any(expect in e for e in report), report


def test_the_shipped_cards_lint_clean():
    assert cards.lint_report(cards.load()) == []


@pytest.mark.parametrize("path, old, new, expect", [
    ("spec/cards/control.yaml", "    open_in: [FRAME, WORK]\n", "    open_in: [FRAME, WORK, CLOSED]\n", "CLOSED"),
    ("spec/cards/control.yaml", "    cache: never\n", "    cache: sometimes\n", "cache must be"),
])
def test_lint_rules(tmp_path, path, old, new, expect):
    report = planted(tmp_path, path, old, new)
    assert any(expect in e for e in report), report


def test_the_declared_python_floor_compiles_the_code():
    """requires-python is the oldest Python that can run bitt: every source compiles on it (uv picks the floor if it is installed)."""
    import pathlib, re, shutil, subprocess, tomllib
    root = pathlib.Path(__file__).resolve().parents[1]
    floor = re.fullmatch(r">=(\d+\.\d+)", tomllib.loads((root / "pyproject.toml").read_text())["project"]["requires-python"])
    assert floor, "requires-python is not a plain >=X.Y floor"
    uv = shutil.which("uv")
    found = uv and subprocess.run([uv, "python", "find", "--no-project", floor[1]], capture_output=True, text=True)
    if not found or found.returncode:
        pytest.skip(f"no Python {floor[1]} installed")
    py = found.stdout.strip()
    srcs = [str(p) for d in ("src", "conformance", "scripts", "evals") for p in (root / d).rglob("*.py")]
    out = subprocess.run([py, "-c", "import sys\nfor f in sys.argv[1:]: compile(open(f).read(), f, 'exec')", *srcs],
                         capture_output=True, text=True)
    assert out.returncode == 0, f"Python {floor[1]} cannot compile the code: raise requires-python\n{out.stderr[-600:]}"


def test_blobs_pinned_to_the_test(tmp_path):
    """conftest pins the blob store under each test's tmp dir: no test can write into the user's ~/.cache/bitt/blobs."""
    import os
    from pathlib import Path
    assert Path(os.environ["BITT_BLOBS"]).is_relative_to(tmp_path), os.environ.get("BITT_BLOBS")


LIVE_DOCS = ["docs/v2/charter.md", "docs/v2/walk.md", "docs/v2/inputs.md", "docs/v2/kernel.md", "docs/v2/db.md", "docs/v2/names.md", "docs/v2/words.md",
             "docs/v2/scenarios.md", "README.md", "AGENTS.md", "SKILL.md", "CLAUDE.md"]
HISTORY_MENTIONS = {("docs/v2/kernel.md", "spec/kernel-contract.md"),     # "it replaces …": a pointer at history, on purpose
                    ("docs/v2/walk.md", "tools/guards.py"),             # the six old walks, before the walker
                    ("docs/v2/words.md", "tools/guards.py"),            # W17's rename row: guards.py -> rules.py
                    ("docs/v2/words.md", "control.promote")}            # W2's decision row (10-28), before the rebuild


def test_live_docs_point_at_what_exists():
    """Every backticked repo path and every `<tool>.<id>` in the live docs exists: a card, a rule, or a name in that tool's code.
    The history pages (foundation, rebuild, d15, handoff, story_router) are not checked: they describe what was."""
    import re
    from pathlib import Path
    from bitt import kernel
    from bitt.tools import packages
    root = Path(__file__).resolve().parents[1]
    k = kernel.Kernel(packages=packages())
    ids = set(k.cards) | set(k.rules)
    tools = sorted({c.split(".")[0] for c in ids})
    path = re.compile(r"^[\w.-]+(/[\w.-]+)+\.(py|md|yaml|sql|sh|jsonl|toml)$")
    ident = re.compile(r"^(%s)\.([a-z_]+)(\.[a-z_]+)?$" % "|".join(tools))

    def in_code(tool, name):
        srcs = [root / "src/bitt/tools" / f"{tool}.py", root / "src/bitt" / f"{tool}.py"]
        return any(s.exists() and re.search(rf"\b{name}\b", s.read_text()) for s in srcs)

    bad = []
    for f in LIVE_DOCS:
        for n, line in enumerate((root / f).read_text().splitlines(), 1):
            for t in (x.strip() for x in re.findall(r"`([^`\n]+)`", line)):
                if (f, t) in HISTORY_MENTIONS:
                    continue
                if re.fullmatch(r"[\w-]+\.(yaml|py|md|sql)", t) and any(root.glob(f"{d}/**/{t}") for d in ("spec", "src", "docs", "conformance")):
                    continue                                         # a bare file name that exists
                if t.startswith(("_output/", "_report/")):
                    continue                                         # local by design (gitignored): never in a clean checkout
                if path.match(t):
                    if not any((root / b / t).exists() for b in ("", "src/bitt", "docs/v2", "docs")):
                        bad.append(f"{f}:{n}: no file {t}")
                elif (m := ident.match(t)) and t not in ids and not in_code(m[1], m[2]):
                    bad.append(f"{f}:{n}: no card, rule or code name {t}")
    assert not bad, "\n".join(bad)


def test_issue_reporting_in_every_skill_block():
    """Each skill block tells an agent to report what is wrong with bitt as an issue, and the eval runner turns filing off (an
    eval agent writes it in its report instead): evals never open real issues."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    blocks = (root / "SKILL.md").read_text().split("## skill: ")[1:]
    assert len(blocks) == 2 and all("### When bitt is wrong" in b and "BITT_ISSUES=off" in b and "gh issue create" in b
               and "~/.bitt/agent-logs/" in b and "bitt log <task>" in b for b in blocks)
    assert '"BITT_ISSUES": "off"' in (root / "evals/haiku/_store.py").read_text()          # the agent's env (agent_env)


def test_the_skill_says_how_each_kind_of_arm_is_filled():
    """Round 3 (11-04): all 3 cycle runs planned the recipes as arms, read 'fill each arm with --fills <want>', then re-planned with
    wants, so the plan they were asked for was replaced. A ref arm is run as it is; --fills is for a want arm only."""
    from pathlib import Path
    skill = (Path(__file__).resolve().parents[1] / "SKILL.md").read_text()
    step = " ".join(skill.split("### A working cycle", 1)[1].split("\n4. ", 1)[0].split())
    assert "an arm that is a ref" in step.lower() and "never re-plan" in step.lower() and "--fills <want>" in step


def test_the_skill_never_tells_the_agent_to_trust():
    """Any trust tag is a person's act (tag.yaml control.approval); every line of the skill that shows the trust command says a person
    runs it, so the agent is never told both."""
    from pathlib import Path
    skill = " ".join((Path(__file__).resolve().parents[1] / "SKILL.md").read_text().split())
    for part in skill.split("--trust trusted")[:-1]:
        near = part[-60:].lower()
        assert "person runs" in near, f"the trust command is shown without saying a person runs it: …{part[-120:]}"


def test_no_private_data_in_tracked_files():
    """The repo is published as a public snapshot (scripts/publish_public.sh): no home paths, private IPs, personal emails or keys
    in any tracked file; and none of the owner's private words, kept outside the repo in $BITT_PRIVATE_WORDS or
    ~/.config/bitt/private_words.txt (one regex per line), so the list itself is never published."""
    import os
    import re
    import subprocess
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    files = [f for f in subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True).stdout.split()
             if f != "uv.lock" and (root / f).is_file()]
    generic = [r"/(Users|home)/[a-z][\w.-]+/", r"\b(10|192\.168|172\.(1[6-9]|2\d|3[01]))\.\d+\.\d+(\.\d+)?\b",
               r"[\w.+-]+@(?!example\.|anthropic\.com|github\.com|users\.noreply)[\w-]+\.(com|tw|org|net|io)\b", r"-----BEGIN [A-Z ]*PRIVATE KEY"]
    wl = Path(os.environ.get("BITT_PRIVATE_WORDS") or Path.home() / ".config/bitt/private_words.txt")
    own = [w.strip() for w in wl.read_text().splitlines() if w.strip() and not w.startswith("#")] if wl.exists() else []
    bad = []
    for f in files:
        try:
            text = (root / f).read_text()
        except UnicodeDecodeError:
            continue
        for pat in generic + own:
            for m in re.finditer(pat, text, flags=re.I if pat in own else 0):
                line = text.count("\n", 0, m.start()) + 1
                bad.append(f"{f}:{line}: {'a private word' if pat in own else repr(m[0])}")
    assert not bad, "\n".join(bad[:30])


def test_the_skill_keeps_a_dropped_option_dropped():
    """Owner 11-04 (SOP N3): no mechanism, two habits: a dropped option is written down, and read before proposing."""
    from pathlib import Path
    skill = " ".join((Path(__file__).resolve().parents[1] / "SKILL.md").read_text().split())
    assert 'bitt note "dropped: <the option>: <why>"' in skill and "never bring a dropped option back without saying why" in skill


def test_the_skill_never_teaches_full_on_a_models_step():
    """Round 5 (11-05): 20 runs went to all rows without the sample, after the skill's model example used --full. A model's step
    climbs (smoke, the sample, look, the rest); --full is for a person's recipe or an arm run as it is."""
    import re
    from pathlib import Path
    text = (Path(__file__).resolve().parents[1] / "SKILL.md").read_text()
    for m in re.finditer(r"bitt run go (\S+) [^`]*--full", text):
        assert m.group(1).startswith(("person:", "<recipe>")), f"--full taught on a model's step: {m.group(0)[:80]}"
    assert "a model's step climbs" in text, "the skill says when --full is right"


def test_every_tag_the_skill_teaches_that_needs_because_shows_it():
    """Agent mistakes 11-06 (_report/qwen/agent_mistakes): `tag --version` without --because, 8 calls in round 5 and 14 before, most
    on a module or a rubric (the skill showed the version line for a dataset only) and on --trust (its line had no --because)."""
    import re
    from pathlib import Path
    text = (Path(__file__).resolve().parents[1] / "SKILL.md").read_text()
    shown = re.findall(r"`bitt tag [^`]*--(?:version|trust|deprecated)[^`]*`", text)
    assert shown and all("--because" in x for x in shown), [x for x in shown if "--because" not in x]
    assert "a module, an artifact" in text, "the version line says it is for any line, not only a dataset"


def test_every_load_the_skill_teaches_says_what_the_data_is():
    """A24 (owner 11-06): data is found later by what its load said it is; a load without --does is refused, so the skill never
    shows one, and it teaches how to find data (`bitt data list <words>`)."""
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    for f in ("SKILL.md", "README.md"):
        loads = re.findall(r"bitt data load [^`\n]*", (root / f).read_text())
        assert loads and all("--does" in x for x in loads), (f, [x for x in loads if "--does" not in x])
    assert "bitt data list <words>" in (root / "SKILL.md").read_text()
