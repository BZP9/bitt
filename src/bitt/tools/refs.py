"""One way to name a node on the command line (docs/v2/names.md §3): an id (or a unique ≥8-character prefix), a name (`qs_split`,
`qs_split@1.0`, `gw/qa_test@1`, `raw/qs@2`, `demo#3`), or `last` (what your previous command made). Every `bitt` command that takes a
node uses `node()`, which resolves through the kernel and prints what a name resolved to."""
import sys

from .. import names
from ..errors import Refused

ACTOR = None                    # who runs this command (set by cli.main): whose `last` it is
QUIET = {"event", "ruling", "warning", "flag", "refusal", "name", "job", "validation", "ack", "outcome"}


def last(k, actor):
    """The newest node `actor` made that is a thing (not an event, a ruling or a name)."""
    for nid in reversed(k.rec.journal()):
        n = k.node(nid)
        if n["kind"] not in QUIET and n["stamp"].get("actor") == actor:
            return nid
    raise SystemExit(f"bitt: `last`: {actor} has made nothing yet")


def node(k, x, task=None, kinds=None, actor=None, quiet=False):
    if x == "last":
        nid = last(k, actor or ACTOR or "")
    else:
        try:
            nid, via = k.resolve(x, task, kinds)
        except Refused as e:
            raise SystemExit(f"bitt: {str(e).removeprefix('record.resolve: ')}") from None
        if not via:
            return nid
    if not quiet:
        n = k.node(nid)
        made = ""
        if n["kind"].startswith("run:") and n["links"].get("recipe") and x != nid and not nid.startswith(x):
            made = f", made by recipe {names.vlabel(k, n['links']['recipe'], task)}: the newest run on the line (an id picks another)"
        print(f"  {x} → {n['kind']} {nid[:12]} ({names.ref_of(k, nid, task)}{made})", file=sys.stderr)
    return nid
