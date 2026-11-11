"""Shared replay helpers: each replay is a story told as kernel calls, with an assert per rule it shows (a refusal writes nothing and
is recorded)."""
import sys

from bitt import Refused


class Harness:
    def __init__(self, E):
        self.E, self.results = E, []

    def ok(self, cond, msg):
        self.results.append((bool(cond), msg))
        print(("  ✓ " if cond else "  ✗ ") + msg)
        return cond

    def refused(self, msg, needle, fn):
        E = self.E
        graph = lambda: [n for n in E.rec.nodes.values() if n["kind"] != "refusal"]  # noqa: E731
        before, refusals = len(graph()), len(E.rec.find("refusal")) + len(E.rec.refusals)
        try:
            fn()
        except Refused as x:
            after = len(E.rec.find("refusal")) + len(E.rec.refusals)
            self.ok(needle in str(x) and len(graph()) == before and after == refusals + 1,
                    f"{msg} → refused, nothing written, attempt recorded")
            if needle not in str(x):
                print(f"      wanted {needle!r}, got: {str(x)[:300]}")
            return
        self.ok(False, f"{msg} → expected a refusal, the call succeeded")

    def c(self, card, actor, **args):
        for a, b in (("in_", "in"), ("as_", "as"), ("with_", "with"), ("on_", "on")):
            if a in args:
                args[b] = args.pop(a)
        return self.E.call(card, args, actor)

    def scene(self, t):
        print(f"\n— {t}")

    def done(self):
        bad = [m for ok, m in self.results if not ok]
        print(f"\n{len(self.results) - len(bad)}/{len(self.results)} asserts passed")
        sys.exit(1 if bad else 0)
