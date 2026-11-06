"""How often two verdict columns agree, and Cohen's kappa (agreement beyond chance)."""
from typing import TypedDict

BITT = {"kind": "check", "scope": "table", "reads": ["a", "b"]}


class Agreement(TypedDict):
    agreement: float
    kappa: float
    n: int


def agreement(rows: list) -> Agreement:
    pairs = [(r.get("a"), r.get("b")) for r in rows if r.get("a") is not None and r.get("b") is not None]
    if not pairs:
        return {"agreement": None, "kappa": None, "n": 0}
    n = len(pairs)
    po = sum(1 for a, b in pairs if a == b) / n
    labels = {x for p in pairs for x in p}
    pe = sum((sum(1 for a, _ in pairs if a == x) / n) * (sum(1 for _, b in pairs if b == x) / n) for x in labels)
    return {"agreement": round(po, 6), "kappa": None if pe == 1 else round((po - pe) / (1 - pe), 6), "n": n}
