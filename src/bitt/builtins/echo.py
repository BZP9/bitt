"""Reply with the last user message, as is: a CPU stub model for tests and smoke runs (no network, no model)."""
BITT = {"kind": "generate"}


def echo(messages: list) -> str:
    return [m for m in messages if m["role"] == "user"][-1]["content"]
