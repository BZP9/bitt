"""Are the two values equal (stripped and lower-cased first unless normalize is false)?"""
BITT = {"kind": "check"}


def exact_match(a: str, b: str, *, normalize: bool = True) -> bool:
    if normalize:
        a, b = (None if x is None else str(x).strip().lower() for x in (a, b))
    return a is not None and a == b
