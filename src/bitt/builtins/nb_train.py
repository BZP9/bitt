"""Train a tiny naive Bayes text classifier (standard library only): the CPU example of a train module.

It learns from the train split, reports its accuracy on each split it was given, and writes weights.json (the model file)."""
import json
import math
import re

BITT = {"kind": "train", "reads": ["text", "label"], "calls": "env",
        "reports": {"train_acc": "number", "val_acc": "number", "test_acc": "number"}}


def _words(s):
    return re.findall(r"[a-z0-9]+", str(s or "").lower())


def _predict(w, text):
    vocab = len(w["vocab"])
    def score(label):
        n = w["totals"][label]
        return math.log(w["priors"][label]) + sum(math.log((w["counts"][label].get(t, 0) + w["alpha"]) / (n + w["alpha"] * vocab))
                                                   for t in _words(text))
    return max(w["priors"], key=score)


def train(job, *, alpha: float = 1):
    rows = job.input.get("train") or [r for rs in job.input.values() for r in rs]
    counts, totals, priors, vocab = {}, {}, {}, set()
    for r in rows:
        y = str(r["label"])
        priors[y] = priors.get(y, 0) + 1
        for t in _words(r["text"]):
            counts.setdefault(y, {})[t] = counts.setdefault(y, {}).get(t, 0) + 1
            totals[y] = totals.get(y, 0) + 1
            vocab.add(t)
    w = {"alpha": alpha, "priors": {y: c / len(rows) for y, c in priors.items()}, "totals": {y: totals.get(y, 0) for y in priors},
         "counts": {y: counts.get(y, {}) for y in priors}, "vocab": sorted(vocab)}
    (job.output / "weights.json").write_text(json.dumps(w, sort_keys=True))
    for split, rs in sorted(job.input.items()):
        if rs:
            job.report(step=1, **{f"{split}_acc": round(sum(_predict(w, r["text"]) == str(r["label"]) for r in rs) / len(rs), 6)})
