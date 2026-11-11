"""A test-only act for tests of the kernel's own mechanics (refusals, nesting, storage): `control.test_note` writes a `note` node."""
from pathlib import Path

from bitt import Package


def note_package():
    return Package(name="note", cards=[Path(__file__).parent / "cards" / "note.yaml"])
