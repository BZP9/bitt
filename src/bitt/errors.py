"""Errors raised by the call path."""


class Refused(Exception):
    """A write the contract does not allow. Nothing is written except the refusal record."""


class Failed(Exception):
    """A card broke its own contract (MIN out missing, DAG violated): a bug in a tool, not a refusal."""
