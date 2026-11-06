"""Is the value there and not blank?"""
BITT = {"kind": "check"}


def nonempty(value: str) -> bool:
    return value is not None and str(value).strip() != ""
