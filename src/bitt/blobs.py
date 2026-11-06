"""Content-addressed files outside the record (a training script, a dataset export, trained weights). The record keeps only the hash;
the bytes live under $BITT_BLOBS (default ~/.cache/bitt/blobs) as <sha256>. A blob is never rewritten: same bytes, same file."""
import hashlib
import os
from pathlib import Path


def root():
    p = Path(os.environ.get("BITT_BLOBS") or Path.home() / ".cache" / "bitt" / "blobs")
    p.mkdir(parents=True, exist_ok=True)
    return p


def put(data):
    h = hashlib.sha256(data).hexdigest()
    p = root() / h
    if not p.exists():
        tmp = p.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.rename(p)
    return h


def get(h):
    p = root() / h
    if not p.exists():
        raise FileNotFoundError(f"blob {h[:12]} is not in {root()} (it was made on another machine?)")
    return p.read_bytes()


def path(h):
    return root() / h
