"""A mutant kernel for conformance/mutate.py: BITT_MUTATE_OFF=<check id> makes that check always pass (in the replays through
backend.make_kernel, in pytest through tests/conftest.py). Unset, it does nothing."""
import os


def apply():
    off = [c for c in os.environ.get("BITT_MUTATE_OFF", "").split(",") if c]
    if not off:
        return
    import bitt.kernel
    init = bitt.kernel.Kernel.__init__

    def mutated(self, *a, **kw):
        init(self, *a, **kw)
        for cid in off:
            self.rules[cid] = lambda eng, s, scope: ("pass", "switched off by mutate.py")
    bitt.kernel.Kernel.__init__ = mutated
