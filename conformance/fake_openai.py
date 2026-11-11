"""A fake OpenAI-compatible endpoint (tests and evals; standard library only). GET /v1/models lists its models; POST
/v1/chat/completions replies with the last user message as is (so a prompt decides what comes back), or answers 500 when that message
holds `FAIL`. With answers ({text: reply}), a last user message that contains one of the texts gets that text's reply instead (an eval
knows its accuracy whatever prompt the agent writes, as long as the prompt carries the row's text). With a key, a request without
`Authorization: Bearer <key>` gets 401. It counts what it was asked.

  in a test:   srv = FakeOpenAI(models=["tiny"], key="k").start(); srv.url … srv.stop()
  standalone:  uv run python conformance/fake_openai.py --port 18080 --model tiny [--key-file f] [--log calls.jsonl] [--answers a.json]
"""
import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class FakeOpenAI:
    def __init__(self, models=("tiny",), key=None, port=0, log=None, answers=None):
        self.models, self.key, self.port, self.log, self.answers = list(models), key, port, log, dict(answers or {})
        self.calls, self.auth = [], []
        self.srv = None

    @property
    def url(self):
        return f"http://127.0.0.1:{self.srv.server_address[1]}/v1"

    def start(self):
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body):
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _authed(self):
                fake.auth.append(self.headers.get("Authorization"))
                if fake.key and self.headers.get("Authorization") != f"Bearer {fake.key}":
                    self._send(401, {"error": {"message": "invalid api key"}})
                    return False
                return True

            def do_GET(self):
                if not self._authed():
                    return
                if self.path.rstrip("/") == "/v1/models":
                    return self._send(200, {"object": "list", "data": [{"id": m, "object": "model"} for m in fake.models]})
                self._send(404, {"error": {"message": "not found"}})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                if not self._authed():
                    return
                if self.path.rstrip("/") != "/v1/chat/completions":
                    return self._send(404, {"error": {"message": "not found"}})
                fake.calls.append(body)
                if fake.log:                                     # one line per chat call (an eval counts them)
                    with open(fake.log, "a") as f:
                        f.write(json.dumps(body, ensure_ascii=False) + "\n")
                if body.get("model") not in fake.models:
                    return self._send(404, {"error": {"message": f"model {body.get('model')} not served"}})
                text = [m for m in body["messages"] if m["role"] == "user"][-1]["content"]
                if "FAIL" in text:
                    return self._send(500, {"error": {"message": "the model fell over"}})
                text = next((reply for t, reply in fake.answers.items() if t in text), text)
                self._send(200, {"choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}]})

        self.srv = ThreadingHTTPServer(("127.0.0.1", self.port), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        return self

    def stop(self):
        self.srv.shutdown()
        self.srv.server_close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=18080)
    ap.add_argument("--model", action="append", default=[])
    ap.add_argument("--key-file")
    ap.add_argument("--log", help="append each chat request here, one JSON line each")
    ap.add_argument("--answers", help="a JSON file {text: reply}: a message containing the text gets the reply")
    a = ap.parse_args()
    s = FakeOpenAI(a.model or ["tiny"], Path(a.key_file).read_text().strip() if a.key_file else None, a.port, a.log,
                   json.loads(Path(a.answers).read_text()) if a.answers else None).start()
    print(f"serving {s.models} at {s.url}", flush=True)
    threading.Event().wait()
