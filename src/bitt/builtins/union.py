"""Every row of the units and of each named input, once: rows equal on the key are one row, linked to every source row it stands for."""
BITT = {"kind": "union"}


def union(on, *, key: list = []):
    """The union's settings are its params; bitt computes a union itself (docs/v2/inputs.md J3), so this body never runs.

    key   [column]: rows with the same values in these columns are one row (the first one read: --on, then the --read roles in
          name order); empty = every column. Every input has the columns of --on (the output's contract, typed from its table).
    """
    raise RuntimeError("bitt computes a union itself")
