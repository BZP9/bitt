"""The mean of a number per row, with its 95% interval (t to 30 rows, normal beyond; rows without a number are left out)."""
import math
from typing import TypedDict

BITT = {"kind": "check", "scope": "table", "reads": ["x"]}
Z = 1.96
T95 = [12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228, 2.201, 2.179, 2.160, 2.145, 2.131, 2.120, 2.110, 2.101,
       2.093, 2.086, 2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042]     # two-sided 95%, df 1..30


class Mean(TypedDict):
    mean: float
    lo: float
    hi: float
    n: int


def mean(rows: list) -> Mean:
    vals = [float(r["x"]) for r in rows if isinstance(r.get("x"), (int, float)) and not isinstance(r.get("x"), bool)]
    n = len(vals)
    if not n:
        return {"mean": None, "lo": None, "hi": None, "n": 0}
    m = sum(vals) / n
    if n < 2:
        return {"mean": round(m, 6), "lo": None, "hi": None, "n": n}
    sd = math.sqrt(sum((v - m) ** 2 for v in vals) / (n - 1))
    half = (T95[n - 2] if n - 1 <= len(T95) else Z) * sd / math.sqrt(n)
    return {"mean": round(m, 6), "lo": round(m - half, 6), "hi": round(m + half, 6), "n": n}
