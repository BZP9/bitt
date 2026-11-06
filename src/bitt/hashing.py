"""Hashes (docs/v2/db.md): h(type, bytes) = sha256(type || 0x00 || bytes), hex.

The kernel's own:  node id (the node body) and spec hash (what a node is: kind + stable payload + lineage parents' spec hashes).
The data tables' four (docs/v2/db.md): raw row, input (`bitt_in_hash`), output, recipe (= a spec hash).
"""
import datetime as _dt
import decimal
import hashlib
import json
import re
import unicodedata


def normalize(obj):
    """The one JSON value space every backend stores identically (so ids re-verify after a round trip):
    integral floats become ints (as Postgres jsonb does), NaN / ±inf and NUL characters are refused."""
    if isinstance(obj, float):
        if obj != obj or obj in (float("inf"), float("-inf")):
            raise ValueError("bitt: NaN / infinity cannot be stored (not JSON)")
        return int(obj) if obj.is_integer() else obj
    if isinstance(obj, str):
        if "\x00" in obj:
            raise ValueError("bitt: a NUL character cannot be stored")
        return obj
    if isinstance(obj, dict):
        return {str(k): normalize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [normalize(v) for v in obj]
    if obj is None or isinstance(obj, (bool, int)):
        return obj
    return normalize(str(obj))


def norm_value(v, type_="text"):
    """A data-table value in its stored (= hashed) form, per column type (docs/v2/db.md)."""
    if v is None:
        return None
    if type_ == "text":
        v = str(v)
        if "\x00" in v:
            raise ValueError("bitt: a NUL character cannot be stored")
        return unicodedata.normalize("NFC", v.replace("\r\n", "\n").replace("\r", "\n"))
    if type_ in ("int", "bigint"):
        if isinstance(v, bool) or (isinstance(v, float) and not v.is_integer()):
            raise ValueError(f"bitt: {v!r} is not an integer")
        bits = 31 if type_ == "int" else 63
        if not -2 ** bits <= int(v) < 2 ** bits:
            raise ValueError(f"bitt: {v!r} does not fit a {type_} ({bits + 1}-bit) column")
        return int(v)
    if type_ == "numeric":
        d = decimal.Decimal(str(v))
        if not d.is_finite():
            raise ValueError("bitt: NaN / infinity cannot be stored")
        s = format(d.normalize(), "f")
        s = s.rstrip("0").rstrip(".") if "." in s else s
        return "0" if s in ("-0", "") else s
    if type_ == "boolean":
        if not isinstance(v, bool):
            raise ValueError(f"bitt: {v!r} is not a boolean")
        return v
    if type_ == "date":
        if isinstance(v, _dt.datetime):
            raise ValueError(f"bitt: {v!r} is a timestamp, not a date (convert it to a date in its own time zone first)")
        return v.isoformat() if isinstance(v, _dt.date) else _dt.date.fromisoformat(str(v)).isoformat()
    if type_ == "timestamptz":
        t = v if isinstance(v, _dt.datetime) else _dt.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        if t.tzinfo is None:
            raise ValueError("bitt: a timestamptz needs a time zone")
        if not isinstance(v, _dt.datetime) and re.search(r"\.\d{7,}", str(v)):
            raise ValueError(f"bitt: {v!r} has more than 6 fractional digits (microseconds are the limit)")
        return t.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if type_ == "jsonb":
        return normalize(v)
    if type_.startswith("vector"):
        dim = int(type_[len("vector("):-1])
        if len(v) != dim:
            raise ValueError(f"bitt: a {type_} value has {len(v)} numbers")
        return [float(_f32(x)) for x in v]
    raise ValueError(f"bitt: unknown column type {type_!r}")


def _f32(x):
    import struct
    f = struct.unpack("f", struct.pack("f", float(x)))[0]
    for digits in range(1, 18):                  # the shortest repr that round-trips through float32
        r = float(f"{f:.{digits}g}")
        if struct.unpack("f", struct.pack("f", r))[0] == f:
            return r
    return f


def canonical(obj):
    """Canonical JSON bytes: sorted keys, no whitespace, UTF-8 (non-ASCII kept as is), no NaN."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str, allow_nan=False).encode("utf-8")


def drop_nulls(d):
    """Keys whose value is NULL are left out of every data hash, so a column added later changes no old hash."""
    return {k: v for k, v in d.items() if v is not None}


def h(type_, data):
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(type_.encode() + b"\x00" + data).hexdigest()


def raw_hash(values):
    """A raw row: every loaded column (stored names → normalized values)."""
    return h("raw", canonical(drop_nulls(values)))


def in_hash(by_role):
    """What a piece of work was given: {role: {column: value}} over only the columns its recipe reads."""
    return h("in", canonical({r: drop_nulls(v) for r, v in by_role.items()}))


def out_hash(recipe, in_h, sample=0, part=0):
    return h("out", canonical({"recipe": recipe, "in": in_h, "sample": sample, "part": part}))


def text_hash(text):
    return h("text", text)
