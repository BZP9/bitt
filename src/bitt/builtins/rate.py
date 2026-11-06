"""The share of rows whose flag is true, with its 95% Wilson interval (rows without a flag are left out)."""
import math
from typing import TypedDict

BITT = {"kind": "check", "scope": "table", "reads": ["x"]}
Z = 1.96


class Rate(TypedDict):
    rate: float
    lo: float
    hi: float
    n: int


def rate(rows: list) -> Rate:
    vals = [r["x"] for r in rows if r.get("x") is not None]
    n = len(vals)
    if not n:
        return {"rate": None, "lo": None, "hi": None, "n": 0}
    p = sum(1.0 for v in vals if v is True) / n
    d = 1 + Z * Z / n
    mid, half = (p + Z * Z / (2 * n)) / d, Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / d
    return {"rate": round(p, 6), "lo": round(max(0.0, mid - half), 6), "hi": round(min(1.0, mid + half), 6), "n": n}
