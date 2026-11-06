"""Is the text's length (in words, or chars) within bounds (either bound may be left out)?"""
from typing import TypedDict

BITT = {"kind": "check"}


class Length(TypedDict):
    length_ok: bool
    length: int


def length(text: str, *, unit: str = "words", min: int = None, max: int = None) -> Length:
    t = "" if text is None else str(text)
    n = len(t.split()) if unit == "words" else len(t)
    return {"length_ok": (min is None or n >= min) and (max is None or n <= max), "length": n}
