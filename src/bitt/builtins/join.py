"""Look each unit's row up in the named inputs by key: the picked columns, one row per unit (docs/v2/inputs.md)."""
BITT = {"kind": "join"}


def join(on, *, key: dict, miss: str = "empty", many: list = [], asof: dict = {}):
    """The join's settings are its params; bitt computes a join itself (per table, recorded per row), so this body never runs.

    key   {lookup role: column} (the same name on both sides) or {lookup role: {lookup column: unit column}} (a composite key)
    miss  a unit with no matching row: "empty" (its picked columns read as empty, warned), "drop" (it leaves the output, warned),
          "fail" (a failed row)
    many  [lookup role]: every matching row, each picked column a list (in the lookup's order, or asof order); never a miss
    asof  {many role: [lookup column, unit column]}: only the rows whose lookup column is strictly before the unit's, oldest first
    """
    raise RuntimeError("bitt computes a join itself")
