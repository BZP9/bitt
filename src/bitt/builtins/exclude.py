"""Keep every row of the input but the ones named, each on its own split (a new version without the bad rows: A22)."""
BITT = {"kind": "derive", "writes": "selection"}


def exclude(rows: list, *, drop: list) -> list:
    out = set(drop)
    return [(i, r.get("bitt_split")) for i, r in enumerate(rows) if r.get("bitt_row_hash") not in out]
