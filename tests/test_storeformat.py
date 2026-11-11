"""The store's format (owner 11-06): a store holds real work from v2.0.1 on, so its shape changes only with a migration.
sql/format.json is this code's format; a change to the store's shape without a new format and migration fails here."""
import json

import psycopg
import pytest

from bitt import storeformat
from bitt.record.postgres import PostgresRecord

BUMP = ("the store's shape changed: add sql/migrations/<n>.sql (carries a format n-1 store forward), set sql/format.json to "
        "format n with the new hashes, and say so in the release notes (AGENTS.md 'Changing the store's shape')")


def test_the_data_tables_shape_is_the_recorded_format():
    assert storeformat.data_shape() == storeformat.spec()["data"], BUMP


def test_migrations_run_from_format_2_to_this_format_without_a_gap():
    ms, n = storeformat.migrations(), storeformat.spec()["format"]
    assert sorted(ms) == list(range(2, n + 1)), f"migrations {sorted(ms)} for format {n}"


def test_a_fresh_store_is_this_format_and_stamped(pg_dsn):
    r = PostgresRecord(pg_dsn)
    assert storeformat.shape(r.db) == storeformat.spec()["bitt"], BUMP
    assert storeformat.stamp(r.db) == storeformat.spec()["format"]
    r.db.close()


def _set_stamp(dsn, n):
    with psycopg.connect(dsn) as c:
        c.execute("INSERT INTO bitt.store_format (format) VALUES (%s)", (n,))


def test_a_newer_store_is_refused(pg_dsn):
    PostgresRecord(pg_dsn).db.close()
    _set_stamp(pg_dsn, 99)
    with pytest.raises(storeformat.FormatRefused, match="newer than this bitt"):
        PostgresRecord(pg_dsn)
    with pytest.raises(storeformat.FormatRefused, match="newer than this bitt"):
        PostgresRecord(pg_dsn, init=False)                 # the panel's read-only open too


def test_an_older_store_is_refused_until_migrated(pg_dsn, monkeypatch):
    PostgresRecord(pg_dsn).db.close()
    real = storeformat.spec()
    monkeypatch.setattr(storeformat, "spec", lambda: {**real, "format": real["format"] + 1})
    with pytest.raises(storeformat.FormatRefused, match="bitt migrate"):
        PostgresRecord(pg_dsn)
    with pytest.raises(storeformat.FormatRefused, match="no migration"):
        PostgresRecord(pg_dsn, migrating=True)
    n = real["format"] + 1
    monkeypatch.setattr(storeformat, "migrations", lambda: {n: "CREATE TABLE bitt.probe_migrated (x int)"})
    r = PostgresRecord(pg_dsn, migrating=True)
    assert r.migrated == [n] and storeformat.stamp(r.db) == n
    assert r.db.execute("SELECT 1 FROM information_schema.tables WHERE table_name = 'probe_migrated'").fetchone()
    r.db.close()
    PostgresRecord(pg_dsn).db.close()                      # now opens


def test_an_unstamped_store_is_adopted_only_at_format_1s_shape(pg_dsn):
    PostgresRecord(pg_dsn).db.close()
    with psycopg.connect(pg_dsn) as c:
        c.execute("DROP TABLE bitt.store_format")
    one = json.loads((storeformat.resources.files("bitt") / "sql/format_1.json").read_text())["bitt"]
    if storeformat.spec()["bitt"] != one:
        pytest.skip("this code is past format 1: a fresh store is not format 1's shape")
    r = PostgresRecord(pg_dsn, init=False)                 # read-only: adopted without a write
    assert storeformat.stamp(r.db) is None
    r.db.close()
    r = PostgresRecord(pg_dsn)
    assert storeformat.stamp(r.db) == 1
    r.db.close()
    with psycopg.connect(pg_dsn) as c:
        c.execute("DROP TABLE bitt.store_format")
        c.execute("ALTER TABLE bitt.node ADD COLUMN extra int")
    with pytest.raises(storeformat.FormatRefused, match="cannot be adopted"):
        PostgresRecord(pg_dsn)


def test_the_cli_says_what_to_do_and_migrate_reports(pg_dsn, capsys):
    from bitt import cli
    PostgresRecord(pg_dsn).db.close()
    assert cli.main(["--dsn", pg_dsn, "migrate"]) == 0
    assert "already format" in capsys.readouterr().out
    _set_stamp(pg_dsn, 99)
    assert cli.main(["--dsn", pg_dsn, "tasks"]) == 2
    assert "upgrade bitt" in capsys.readouterr().err
