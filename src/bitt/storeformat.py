"""The store's format (owner 11-06: from v2.0.1 on, a store holds real work, so a format change ships a migration, never a wipe).

A store is stamped with the format it was made or migrated to (bitt.store_format). The format is the shape of the store: the bitt.*
tables' columns and constraints, and the columns bitt gives a data table of each shape (sql/format.json, checked by
tests/test_storeformat.py on a fresh store). Opening a store at another format is refused: an older one → `bitt migrate`
(sql/migrations/<n>.sql, applied in order in one transaction); a newer one → this bitt is older than the store, upgrade it.
A store made before stamps existed is adopted at format 1 when its bitt.* shape is format 1's, refused otherwise.
"""
import hashlib
import json
from importlib import resources

from . import tables


class FormatRefused(Exception):
    """The store's format is not this bitt's: nothing was read or written."""


def spec():
    """{"format": n, "bitt": <hash of the bitt.* shape>, "data": <hash of the data tables' shape>} for this code."""
    return json.loads(resources.files("bitt").joinpath("sql/format.json").read_text())


def migrations():
    """{n: sql} the migrations to format n (n >= 2), from sql/migrations/<n>.sql."""
    d = resources.files("bitt").joinpath("sql/migrations")
    if not d.is_dir():
        return {}
    return {int(f.name[:-4]): f.read_text() for f in d.iterdir() if f.name.endswith(".sql") and f.name[:-4].isdigit()}


def _hash(rows):
    return hashlib.sha256(json.dumps(sorted(rows), default=str).encode()).hexdigest()[:16]


def shape(db, schemas=("bitt",)):
    """A hash of the tables in these schemas (the stamp itself left out): every column (table, name, type, null, default) and every constraint."""
    cols = db.execute("SELECT table_schema, table_name, column_name, data_type, udt_name, is_nullable, column_default "
                      "FROM information_schema.columns c JOIN information_schema.tables t USING (table_schema, table_name) "
                      "WHERE table_schema = ANY(%s) AND t.table_type = 'BASE TABLE' AND table_name <> 'store_format'", (list(schemas),)).fetchall()
    cons = db.execute("SELECT n.nspname, r.relname, c.contype, pg_get_constraintdef(c.oid) FROM pg_constraint c "
                      "JOIN pg_class r ON r.oid = c.conrelid JOIN pg_namespace n ON n.oid = r.relnamespace "
                      "WHERE n.nspname = ANY(%s) AND r.relname <> 'store_format'", (list(schemas),)).fetchall()
    return _hash([["col", *r] for r in cols] + [["con", *r] for r in cons])


def data_shape():
    """A hash of what bitt gives a data table of each shape (columns, keys, foreign keys, indexes): from the specs, no database."""
    data = [{"name": "text", "type": "text", "kind": "source"}]
    raw = tables.shape_spec("raw", "raw", "probe", {}, data)
    regs = {"raw.probe": raw}
    specs = [raw, tables.shape_spec("output", "made", "probe_out", {"in": "raw.probe"}, data, regs),
             tables.shape_spec("src", "made", "probe_out" + tables.SUFFIX["src"], {"in": "raw.probe"}, [], regs),
             tables.shape_spec("sets", "raw", "probe" + tables.SUFFIX["sets"], {"rows": "raw.probe"}, [], regs)]
    return _hash([json.dumps(sp, sort_keys=True, default=str) for sp in specs])


def stamp(db):
    """The store's format: an int; None for a store made before stamps; 0 for an empty database."""
    if not db.execute("SELECT 1 FROM information_schema.tables WHERE table_schema = 'bitt' AND table_name = 'node'").fetchone():
        return 0
    if not db.execute("SELECT 1 FROM information_schema.tables WHERE table_schema = 'bitt' AND table_name = 'store_format'").fetchone():
        return None
    r = db.execute("SELECT max(format) FROM bitt.store_format").fetchone()
    return r[0] if r else None


def write_stamp(db, n):
    db.execute("CREATE TABLE IF NOT EXISTS bitt.store_format (format int NOT NULL, at timestamptz NOT NULL DEFAULT now())")
    db.execute("INSERT INTO bitt.store_format (format) VALUES (%s)", (n,))


def check(db, migrating=False, write=True):
    """Before anything is read: → the store's format (0 = an empty database). Refused (FormatRefused) at another format,
    unless migrating from an older one. Adopts an unstamped store whose bitt.* shape is format 1's (stamps it 1 when `write`)."""
    want, have = spec(), stamp(db)
    if have is None:
        if shape(db) != json.loads(resources.files("bitt").joinpath("sql/format_1.json").read_text())["bitt"]:
            raise FormatRefused("this store was made before format stamps and its shape is not format 1's: it cannot be adopted; "
                                "restore it with the bitt that made it, or start a new store")
        if write:
            write_stamp(db, 1)
        have = 1
    if have and have > want["format"]:
        raise FormatRefused(f"this store is format {have}, newer than this bitt (format {want['format']}): upgrade bitt "
                            f"(uv tool upgrade bitt)")
    if have and have < want["format"] and not migrating:
        raise FormatRefused(f"this store is format {have}, this bitt needs format {want['format']}: back the store up "
                            f"(pg_dump), then run `bitt migrate`")
    return have


def migrate(db):
    """Apply every migration from the store's format to this bitt's, in order; → [(n, applied)]. Run inside one transaction."""
    have, want = check(db, migrating=True), spec()["format"]   # (check stamps an adopted store first)
    if have == 0:
        return []
    ms, done = migrations(), []
    for n in range(have + 1, want + 1):
        if n not in ms:
            raise FormatRefused(f"no migration to format {n} (sql/migrations/{n}.sql): this bitt cannot carry the store forward")
        db.execute(ms[n])
        write_stamp(db, n)
        done.append(n)
    return done
