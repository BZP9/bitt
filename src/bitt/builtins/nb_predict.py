"""Predict a label per row with a model nb_train made (its weights.json, in the `file` role)."""
import json
import math
import re
from pathlib import Path

BITT = {"kind": "generate", "roles": {"file": "model"}}
W = {}


def _words(s):
    return re.findall(r"[a-z0-9]+", str(s or "").lower())


def pred(text: str) -> str:
    if not W:
        W.update(json.loads((Path("input") / "file" / "weights.json").read_text()))
    vocab = len(W["vocab"])

    def score(label):
        n = W["totals"][label]
        return math.log(W["priors"][label]) + sum(math.log((W["counts"][label].get(t, 0) + W["alpha"]) / (n + W["alpha"] * vocab))
                                                   for t in _words(text))
    return max(W["priors"], key=score)
