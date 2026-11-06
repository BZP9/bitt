"""Record backends: memory (tests and replays) and Postgres (every store: docs/v2/db.md §2)."""
from .memory import MemoryRecord

__all__ = ["MemoryRecord", "PostgresRecord"]


def __getattr__(name):
    if name == "PostgresRecord":                # psycopg is optional
        from .postgres import PostgresRecord
        return PostgresRecord
    raise AttributeError(name)
