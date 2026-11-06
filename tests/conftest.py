"""Every test runs on each Record backend: memory, and Postgres when BITT_PG_ADMIN_DSN points at a throwaway cluster
(scripts/pg_throwaway.sh start). Anything else is refused (backend.throwaway_problem). A test that needs a store across commands (the
CLI, the monitor) takes `pg_dsn`: a fresh database of its own, skipped when no throwaway cluster is up."""
import os
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "conformance"))
__import__("mutant").apply()             # conformance/mutate.py switches a check off through $BITT_MUTATE_OFF (unset: nothing)


def _pg_admin():
    dsn = os.environ.get("BITT_PG_ADMIN_DSN")
    if not dsn:
        return None
    from backend import throwaway_problem
    if why := throwaway_problem(dsn):
        pytest.exit(f"refusing BITT_PG_ADMIN_DSN: {why}")
    return dsn


@pytest.fixture(autouse=True)
def _isolated_jobs(tmp_path, monkeypatch):
    """Module jobs run under the test's tmp dir, and never read the user's envs.yaml (only the built-in `local` env)."""
    monkeypatch.setenv("BITT_JOBS", str(tmp_path / "jobs"))
    monkeypatch.setenv("BITT_BLOBS", str(tmp_path / "blobs"))           # never your real blob store (~/.cache/bitt/blobs)
    monkeypatch.setenv("BITT_ENVS", str(tmp_path / "no-envs.yaml"))
    monkeypatch.setenv("BITT_CURRENT", str(tmp_path / "current.json"))    # never your real current cycle (~/.config/bitt)
    monkeypatch.delenv("BITT_DSN", raising=False)                         # never your real store: a test sets the one it uses


os.environ.setdefault("BITT_NO_SKILL_SYNC", "1")     # tests never write to ~/.claude/skills (test_skills.py points the sync at a tmp dir)

BACKENDS = ["memory"] + (["postgres"] if os.environ.get("BITT_PG_ADMIN_DSN") else [])


@pytest.fixture(params=BACKENDS)
def opener(request, tmp_path):
    """opener() → a fresh Record of this backend; opener(same=True) → reopen the same store (persistence tests)."""
    kind, state = request.param, {}

    def open_(same=False):
        if kind == "memory":
            from bitt.record.memory import MemoryRecord
            if same:
                pytest.skip("memory has nothing to reopen")
            return MemoryRecord()
        import psycopg
        from psycopg.conninfo import conninfo_to_dict, make_conninfo

        from bitt.record.postgres import PostgresRecord
        admin = _pg_admin()
        if "db" not in state:
            state["db"] = f"bitt_t_{uuid.uuid4().hex[:10]}"
            with psycopg.connect(admin, autocommit=True) as c:
                c.execute(f'CREATE DATABASE "{state["db"]}"')
        return PostgresRecord(make_conninfo(**(conninfo_to_dict(admin) | {"dbname": state["db"]})))

    open_.kind = kind
    yield open_
    if "db" in state:
        import psycopg
        with psycopg.connect(_pg_admin(), autocommit=True) as c:
            c.execute(f'DROP DATABASE IF EXISTS "{state["db"]}" WITH (FORCE)')


@pytest.fixture
def pg_dsn():
    """A fresh database on the throwaway cluster for one test (dropped after); skipped when none is up."""
    import psycopg
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    admin = _pg_admin()
    if not admin:
        pytest.skip("needs the throwaway Postgres: scripts/pg_throwaway.sh start, BITT_PG_ADMIN_DSN=$(scripts/pg_throwaway.sh dsn)")
    db = f"bitt_t_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(admin, autocommit=True) as c:
        c.execute(f'CREATE DATABASE "{db}"')
    yield make_conninfo(**(conninfo_to_dict(admin) | {"dbname": db}))
    with psycopg.connect(admin, autocommit=True) as c:
        c.execute(f'DROP DATABASE IF EXISTS "{db}" WITH (FORCE)')
