"""Does the text match a regex (case-insensitive unless case is true)?"""
import re

BITT = {"kind": "check"}


def contains(text: str, *, pattern: str, case: bool = False) -> bool:
    return re.search(pattern, "" if text is None else str(text), 0 if case else re.IGNORECASE) is not None
