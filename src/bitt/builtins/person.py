"""A person answers each row's prompt (labelling): the run stays open for as long as it takes and blocks nothing (C9).

bitt never calls this function: `bitt run answer <run> --file answers.jsonl` adds a person's answers, `bitt run close <run>` ends it.
What reads the run before it is closed sees the answers so far, marked partial."""
BITT = {"kind": "generate", "calls": "person"}


def person(messages: list) -> str:
    raise RuntimeError("a person answers this: bitt run answer")
