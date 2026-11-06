"""Pick the Record backend for a conformance run: BITT_BACKEND = memory (default) | postgres.

postgres needs BITT_PG_ADMIN_DSN pointing at a THROWAWAY cluster (scripts/pg_throwaway.sh). Each run gets a fresh database.
It refuses anything that is not a throwaway cluster: a non-local host, the default port 5432, or a server in $BITT_PROTECTED_DSNS.
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import bitt.kernel  # noqa: E402
from bitt.tools import packages  # noqa: E402
import mutant  # noqa: E402

mutant.apply()


def _same_server(a, b):
    from psycopg.conninfo import conninfo_to_dict
    da, db = conninfo_to_dict(a), conninfo_to_dict(b)
    local = {None, "", "localhost", "127.0.0.1", "::1"}             # every spelling of this machine is one server
    host = lambda d: "localhost" if d.get("host") in local or str(d.get("host", "")).startswith("/") else d.get("host")  # noqa: E731
    return (host(da), str(da.get("port") or "5432")) == (host(db), str(db.get("port") or "5432"))


def throwaway_problem(dsn):
    """Why `dsn` is not a throwaway test cluster (None = it may be used): tests only ever run on a local Postgres on a non-default port."""
    from psycopg.conninfo import conninfo_to_dict
    d = conninfo_to_dict(dsn)
    host = d.get("host")
    if not (host in (None, "", "localhost", "127.0.0.1", "::1") or str(host).startswith("/")):
        return f"host {host!r} is not this machine"
    if str(d.get("port") or "5432") == "5432":
        return "port 5432 is where a real database lives; the throwaway cluster runs on another port (scripts/pg_throwaway.sh)"
    for live in filter(None, os.environ.get("BITT_PROTECTED_DSNS", "").split(",")):
        if _same_server(dsn, live.strip()):
            return "it is a server listed in $BITT_PROTECTED_DSNS"
    return None


def make_kernel(name):
    """The contract's cards and the tool packages, on the backend BITT_BACKEND names."""
    # always the suite's own stores and machines, whatever the shell exports: never the user's blobs, job folders or envs.yaml
    import atexit
    import shutil
    os.environ["BITT_BLOBS"] = str(HERE / "_store" / "blobs")
    jobs = HERE / "_store" / f"jobs-{name}-{os.getpid()}"                          # a fresh folder per replay process: job ids
    shutil.rmtree(jobs, ignore_errors=True)                                        # repeat across runs, so two replays at once
    atexit.register(shutil.rmtree, jobs, True)                                     # never share one
    os.environ["BITT_JOBS"] = str(jobs)
    os.environ["BITT_ENVS"] = str(HERE / "fixtures" / "envs.yaml")
    os.environ["BITT_CURRENT"] = str(HERE / "_store" / "current.json")
    return bitt.kernel.Kernel(_record(name), packages=packages())


def _record(name):
    kind = os.environ.get("BITT_BACKEND", "memory")
    if kind == "memory":
        from bitt.record.memory import MemoryRecord
        rec = MemoryRecord()
    elif kind == "postgres":
        import psycopg
        from bitt.record.postgres import PostgresRecord
        admin = os.environ["BITT_PG_ADMIN_DSN"]
        if why := throwaway_problem(admin):
            raise SystemExit(f"refusing BITT_PG_ADMIN_DSN: {why}")
        db = f"bitt_conf_{name}"
        with psycopg.connect(admin, autocommit=True) as c:
            c.execute(f'DROP DATABASE IF EXISTS "{db}"')
            c.execute(f'CREATE DATABASE "{db}"')
        from psycopg.conninfo import conninfo_to_dict, make_conninfo
        rec = PostgresRecord(make_conninfo(**(conninfo_to_dict(admin) | {"dbname": db})))
    else:
        raise SystemExit(f"unknown BITT_BACKEND {kind!r}")
    return rec
