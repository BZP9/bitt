"""`bitt serve`: the panel, live (docs/v2/panel.md). Every page is drawn from its store when asked; an open page asks the store's seq
every 3 s and redraws itself in place when it moved. Nothing to rebuild.

  /                         the store's home: every task as a lane
  /s/<store>/t/<task>       a task · /s/<store>/t/<task>/c/<n> a cycle · /s/<store>/seq the store's newest seq
  /s/<store>/n/<id>         the inspector: one node (an id or a ≥8-char prefix) as the drawer draws it

Read only: a store opens in a read-only session (default_transaction_read_only) with no schema setup; the server answers GET only and
listens on 127.0.0.1. `Panel(stores)` takes {key: Store}; `bitt serve` gives it your store as `mine`; scripts/viz_serve.py adds the
eval and tour stores.
"""
import html
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import quote, unquote, urlparse

from . import data, view


def read_only(dsn):
    """The same store in a session that cannot write."""
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    c = conninfo_to_dict(dsn)
    return make_conninfo(**(c | {"options": (c.get("options", "") + " -c default_transaction_read_only=on").strip()}))


class Store:
    """How to read one store: `kernel()` a fresh kernel over it, `seq()` its newest seq."""

    def __init__(self, kernel, seq):
        self.kernel, self.seq = kernel, seq

    @classmethod
    def postgres(cls, dsn, before=None):
        """A Postgres store, read only (`before`: run first, e.g. point blob reads at an eval's folder)."""
        def kernel():
            from ..kernel import Kernel
            from ..record.postgres import PostgresRecord
            from ..tools import packages
            if before:
                before()
            return Kernel(PostgresRecord(read_only(dsn), init=False), packages=packages())

        def seq():
            import psycopg
            with psycopg.connect(read_only(dsn)) as db:
                return db.execute("SELECT coalesce(max(seq), 0) FROM bitt.node").fetchone()[0]
        return cls(kernel, seq)


def links(key):
    base = f"/s/{quote(key)}"
    return view.Links(home=f"{base}/", task=base + "/t/{t}", cycle=base + "/t/{t}/c/{n}", seq=f"{base}/seq", node=f"{base}/n/__N__")


def page(store, key, rest):
    """A page of the panel: rest = [] (home), [t, task] or [t, task, c, n]; KeyError when there is none."""
    S = data.model(store.kernel())
    view.L = links(key)
    if not rest:
        return view.home(S)
    t = next((x for x in S["tasks"] if x["name"] == rest[1]), None) if len(rest) >= 2 and rest[0] == "t" else None
    if t is None:
        raise KeyError(f"no task {rest[1:2]}")
    if len(rest) == 2:
        return view.task_page(t)
    c = next((x for x in t["cycles"] if str(x["n"]) == rest[3]), None) if len(rest) == 4 and rest[2] == "c" else None
    if c is None:
        raise KeyError(f"no cycle {rest[2:]}")
    return view.cycle_page(t, c)


class Panel:
    """The server's routes over `stores()` → {key: Store}; `home`: the key `/` shows; `extra(path, query)` → html or None, for more pages."""

    def __init__(self, stores, home=None, extra=None):
        self.stores, self.home, self.extra = stores, home, extra

    def answer(self, path, query=""):
        """(status, content type, body) of one GET."""
        parts = [unquote(p) for p in urlparse(path).path.strip("/").split("/") if p]
        try:
            if not parts and self.home:
                return 200, "text/html; charset=utf-8", page(self.stores()[self.home], self.home, [])
            if self.extra and (got := self.extra(parts, query)) is not None:
                return 200, "text/html; charset=utf-8", got
            if len(parts) >= 2 and parts[0] == "s":
                st = self.stores()[parts[1]]
                if parts[2:] == ["seq"]:
                    return 200, "text/plain", str(st.seq())
                if len(parts) == 4 and parts[2] == "n":              # the inspector: one node, as a drawer's fragment
                    view.L = links(parts[1])
                    return 200, "text/html; charset=utf-8", view.inspector(data.inspect(st.kernel(), parts[3]))
                return 200, "text/html; charset=utf-8", page(st, parts[1], parts[2:])
            return 404, "text/html; charset=utf-8", "<p>not found: <a href='/'>home</a></p>"
        except KeyError as e:
            return 404, "text/html; charset=utf-8", f"<p>not found: {html.escape(str(e))} · <a href='/'>home</a></p>"
        except Exception:
            return 500, "text/html; charset=utf-8", f"<pre>{html.escape(traceback.format_exc()[-3000:])}</pre><p><a href='/'>home</a></p>"

    def server(self, port=8765, host="127.0.0.1"):
        panel = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                code, kind, body = panel.answer(self.path, urlparse(self.path).query)
                b = body.encode()
                self.send_response(code)
                self.send_header("Content-Type", kind)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def log_message(self, *a):
                pass
        return HTTPServer((host, port), Handler)               # one request at a time: a page opens its own store


def main(dsn, port=8765):
    """`bitt serve`: your store's panel, until ^C."""
    st = Store.postgres(dsn)
    srv = Panel(lambda: {"mine": st}, home="mine").server(port)
    print(f"bitt serve: http://127.0.0.1:{srv.server_port}  (read only; ^C stops it)", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0
