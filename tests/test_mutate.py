"""The mutation harness (conformance/mutate.py) runs what caught a mutation last time alone, and the full path when it no longer catches."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "conformance"))
import mutate  # noqa: E402


def fake(monkeypatch, replay_catches, test_catches):
    calls = []

    def replays(work, off=None, only=mutate.REPLAYS):
        calls.append(("replays", only))
        return [r.removeprefix("replay_").removesuffix(".py") for r in only if r in replay_catches], False

    def pytest(work, off=None, sel=None, ids=("tests",)):
        calls.append(("pytest", ids))
        hit = [t for t in test_catches if ids == ("tests",) or t in ids]
        return ("caught", hit[0]) if hit else ("none", None)
    monkeypatch.setattr(mutate, "replays", replays)
    monkeypatch.setattr(mutate, "pytest", pytest)
    return calls


def test_a_known_killer_runs_alone(monkeypatch):
    calls = fake(monkeypatch, [], ["tests/test_tag.py::test_first"])
    assert mutate.verdict(".", killer="tests/test_tag.py::test_first") == ("caught by pytest", "tests/test_tag.py::test_first")
    assert calls == [("pytest", ("tests/test_tag.py::test_first",))]
    calls = fake(monkeypatch, ["replay_gw.py"], [])
    assert mutate.verdict(".", killer="replay_gw.py") == ("caught by gw", "replay_gw.py")
    assert calls == [("replays", ("replay_gw.py",))]


def test_a_killer_that_no_longer_catches_falls_back_to_the_full_path(monkeypatch):
    calls = fake(monkeypatch, [], ["tests/test_run.py::test_other"])
    assert mutate.verdict(".", killer="tests/test_tag.py::test_first") == ("caught by pytest", "tests/test_run.py::test_other")
    assert [c[0] for c in calls] == ["pytest", "replays", "pytest"]
    calls = fake(monkeypatch, [], [])
    assert mutate.verdict(".", killer="replay_vk.py") == ("SURVIVED", None)
