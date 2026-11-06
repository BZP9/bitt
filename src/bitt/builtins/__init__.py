"""The modules bitt ships: row checks (contains, exact_match, json_valid, length, nonempty), aggregates across rows (rate, mean, count,
agreement: each writes one row) and the naive Bayes train / model pair. Each is a plain module (its function is its contract: a recipe binds its columns); `builtin` trust everywhere (D16)."""
from pathlib import Path

SHIPPED = {p.stem: p for p in Path(__file__).parent.glob("*.py") if p.stem != "__init__"}
