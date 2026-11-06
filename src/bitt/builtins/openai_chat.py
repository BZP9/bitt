"""Send a row's messages to an OpenAI-compatible chat endpoint and return the reply's text.

POST {url}/chat/completions. The key, when the endpoint needs one, comes from the job's environment (BITT_KEY: bitt reads `key_file`
at call time and sets it in the job's process only): never in job.json, the rows or the output. Standard library only."""
import json
import os
import urllib.error
import urllib.request

BITT = {"kind": "generate"}


def openai_chat(messages: list, *, url: str, model: str, key_file: str = "", temperature: float = None, max_tokens: int = None,
                seed: int = None, timeout: int = 300) -> str:
    body = {"model": model, "messages": messages,
            **{k: v for k, v in (("temperature", temperature), ("max_tokens", max_tokens), ("seed", seed)) if v is not None}}
    req = urllib.request.Request(url.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    if os.environ.get("BITT_KEY"):
        req.add_header("Authorization", f"Bearer {os.environ['BITT_KEY']}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            got = json.loads(resp.read())
    except urllib.error.HTTPError as x:
        raise RuntimeError(f"the endpoint answered {x.code}: {x.read()[:200].decode(errors='replace')}") from None
    return got["choices"][0]["message"]["content"] or ""
