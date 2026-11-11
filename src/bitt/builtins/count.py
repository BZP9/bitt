"""How many rows there are."""
from typing import TypedDict

BITT = {"kind": "check", "scope": "table"}


class Count(TypedDict):
    n: int


def count(rows: list) -> Count:
    return {"n": len(rows)}
