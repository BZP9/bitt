"""Small shared helpers."""
import hashlib
import json


def h(*xs):
    """A short content hash of JSON-able values (used by mock tools and cache keys, not for node identity)."""
    return hashlib.sha256(json.dumps(xs, sort_keys=True, default=str).encode()).hexdigest()[:12]


def as_list(x):
    return x if isinstance(x, list) else ([] if x is None else [x])
