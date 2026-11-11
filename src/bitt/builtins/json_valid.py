"""Does the value hold JSON (text that parses, or a value already parsed)?"""
import json

BITT = {"kind": "check"}


def json_valid(value: str) -> bool:
    if value is None:
        return False
    if not isinstance(value, str):
        return True
    try:
        json.loads(value)
        return True
    except ValueError:
        return False
