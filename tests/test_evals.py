"""The agent-eval tooling (evals/haiku): its acts, never a store."""
import importlib.util
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _store():
    spec = importlib.util.spec_from_file_location("_store", ROOT / "evals/haiku/_store.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_an_eval_is_graded_by_grade_not_check(tmp_path, monkeypatch):
    """#11: the act that judges a store is `grade <dir>` (check is a module kind); `check` is no act any more."""
    s = _store()
    (tmp_path / "dsn.txt").write_text("unused")
    monkeypatch.setattr(s, "env", lambda d: {})
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["eval", "grade", str(tmp_path)])
    with pytest.raises(SystemExit) as e:
        s.main(lambda d: 0, lambda d: 7)
    assert e.value.code == 7
    monkeypatch.setattr("sys.argv", ["eval", "check", str(tmp_path)])
    with pytest.raises(KeyError):
        s.main(lambda d: 0, lambda d: 7)
    assert not [f.name for f in (ROOT / "evals/haiku").glob("*_basics.py") if "\ndef check(d):" in f.read_text()]
    assert '"grade", str(d)' in (ROOT / "evals/run_agent_eval.py").read_text()


def test_the_agent_gets_the_evals_store_never_the_callers(tmp_path):
    """Round 3 (11-04): the runner passed the caller's whole environment, so an agent whose `export` was lost in a fresh shell wrote
    into the owner's own store (BITT_DSN) and could reach the owner's machines (BITT_ENVS). The agent's env is the eval's store only."""
    s = _store()
    (tmp_path / "dsn.txt").write_text("postgresql://bitt@localhost:55432/bitt_eval_x")
    owner = {"PATH": "/usr/bin", "HOME": "/h", "BITT_DSN": "postgresql://bitt@localhost:55433/bitt", "BITT_ENVS": "/h/envs.yaml",
             "BITT_BLOBS": "/h/blobs", "BITT_ACTOR": "usr", "PGPORT": "55433", "PGDATABASE": "bitt"}
    got = s.agent_env(tmp_path, owner)
    assert got["BITT_DSN"].endswith("/bitt_eval_x") and got["BITT_ENVS"] == str(tmp_path / "envs.yaml")
    assert got["BITT_BLOBS"] == str(tmp_path / "blobs") and got["BITT_ISSUES"] == "off"
    assert not {k for k in got if k.startswith("PG")} and "BITT_ACTOR" not in got
    assert got["PATH"] == "/usr/bin" and got["HOME"] == "/h"
    src = (ROOT / "evals/run_agent_eval.py").read_text()
    assert "env = _store.agent_env(d, os.environ)" in src and "**os.environ" not in src
