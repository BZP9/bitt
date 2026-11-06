"""bitt: the research-workflow kernel (spec/kernel-contract.md)."""
from .errors import Failed, Refused
from .kernel import Engine, Kernel, Package
from .record import MemoryRecord

__all__ = ["Kernel", "Engine", "Package", "Refused", "Failed", "MemoryRecord", "PostgresRecord"]


def __getattr__(name):
    if name == "PostgresRecord":
        from .record.postgres import PostgresRecord
        return PostgresRecord
    raise AttributeError(name)
