"""Prompts (foundation.md §B, §M): a prompt is an artifact of kind `prompt`, a JSON chat-messages file.

  {"bitt": {"does": "…"},                                what it is for, one sentence (required)
   "gives": {"title": "text", "tags": "json"},           optional: none = one text column named after the prompt
   "messages": [{"role": "system", "content": "…"},      an optional system message, worked examples as user / assistant pairs,
                {"role": "user", "content": "… {q} …"}]}  then the row's own user message; `{slot}` slots are what it needs

Its contract is needs → gives: needs = the slots (a recipe binds each to a column), gives = the declared fields + raw_text (exactly
what the model returned) + warn (a note on the reply). A slot or field change is a major, a wording change a minor. bitt renders each
row's messages and parses each reply; the generate module (a connector) only sends messages and returns the text.
"""
import json
import re

SLOT = re.compile(r"\{([a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)?)\}")   # `{name}` or `{line.name}` is a slot: any other brace is text
ROLES = ("system", "user", "assistant")
TYPES = ("text", "int", "number", "bool", "json")
OWN = ("raw_text", "warn")                       # the columns bitt adds to every prompt's output


def slots(messages):
    """The columns a prompt reads, in the order they first appear."""
    out = []
    for m in messages:
        for s in SLOT.findall(m.get("content", "")):
            if s not in out:
                out.append(s)
    return out


def parse(code, name):
    """(contract, problem) of a prompt file: {needs, gives, does}; `name` is its line (the default output column)."""
    try:
        doc = json.loads(code.decode() if isinstance(code, bytes) else code)
    except (ValueError, UnicodeDecodeError) as x:
        return None, f"the prompt is not JSON: {x}"
    if not isinstance(doc, dict) or set(doc) - {"bitt", "gives", "messages"}:
        return None, 'a prompt is {"bitt": {"does": "…"}, "gives": {…}, "messages": [ … ]} (gives optional)'
    msgs = doc.get("messages")
    if not isinstance(msgs, list) or not msgs or not all(isinstance(m, dict) and set(m) == {"role", "content"}
                                                         and m["role"] in ROLES and isinstance(m["content"], str) for m in msgs):
        return None, f"messages is a list of {{role, content}} with role one of {list(ROLES)} and content text"
    if msgs[-1]["role"] != "user":
        return None, "the last message is the row's own user message"
    if any(m["role"] == "system" for m in msgs[1:]):
        return None, "a system message comes first, or not at all"
    needs = slots(msgs)
    if not needs:
        return None, "the prompt needs no column: put a {slot} in a message"
    gives = doc.get("gives")
    plain_ = gives is None
    if gives is None:
        gives = {name: "text"}
    if not isinstance(gives, dict) or not gives or any(t not in TYPES for t in gives.values()):
        return None, f"gives is {{name: type}} with types from {list(TYPES)}"
    bad = [k for k in gives if not re.fullmatch(r"[a-z][a-z0-9]*(_[a-z0-9]+)*", k) or k in OWN or k.startswith("bitt_")]
    if bad:
        return None, f"gives {bad}: a field is a column name, and {list(OWN)} are bitt's"
    does = (doc.get("bitt") or {}).get("does") if isinstance(doc.get("bitt"), dict) else None
    c = {"needs": needs, "gives": {**gives, "raw_text": "text", "warn": "text"}, "plain": plain_, "does": does}
    return c, (None if does else 'a prompt says what it is for: "bitt": {"does": "<one sentence>"}')


def messages_of(code):
    return json.loads(code.decode() if isinstance(code, bytes) else code)["messages"]


def declared(contract):
    """The fields a reply must carry (the prompt's gives without bitt's own columns)."""
    return {k: t for k, t in contract["gives"].items() if k not in OWN}


def render(messages, values):
    """One row's messages: each slot replaced by the row's value (text as is; anything else as JSON)."""
    def fill(m):
        v = values.get(m.group(1))
        return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    return [{"role": m["role"], "content": SLOT.sub(fill, m["content"])} for m in messages]


def _typed(v, t):
    if t == "text":
        return isinstance(v, str)
    if t == "int":
        return isinstance(v, int) and not isinstance(v, bool)
    if t == "number":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    if t == "bool":
        return isinstance(v, bool)
    return True                                                       # json: anything


def reply_json(text):
    """The JSON object in a reply: the whole text, or a ```json fenced block in it."""
    s = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", s, re.S)
    try:
        return json.loads(fence.group(1) if fence else s)
    except ValueError:
        return None


def parse_reply(text, header, plain_=False):
    """A reply → the row's output columns. A plain prompt (no `gives`): the text is the value. Otherwise a missing declared field, a
    wrong type or no JSON object is the row's error (ValueError); fields nobody declared are kept in `bitt_extra` (and raw_text), noted in
    `warn` (A11)."""
    want = declared(header)
    if plain_:
        return {list(want)[0]: text, "raw_text": text, "warn": None}
    got = reply_json(text)
    if not isinstance(got, dict):
        raise ValueError(f"the reply is not a JSON object (raw_text: {text[:200]!r})")
    missing = [k for k in want if k not in got]
    if missing:
        raise ValueError(f"the reply lacks {missing} (raw_text: {text[:200]!r})")
    wrong = [f"{k} is not {t}" for k, t in want.items() if got[k] is not None and not _typed(got[k], t)]
    if wrong:
        raise ValueError(f"the reply's {'; '.join(wrong)} (raw_text: {text[:200]!r})")
    extra = [k for k in got if k not in want]
    return {**{k: got[k] for k in want}, "raw_text": text, "warn": f"extra: {', '.join(extra)}" if extra else None,
            "bitt_extra": {k: got[k] for k in extra} or None}
