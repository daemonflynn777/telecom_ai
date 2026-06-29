#!/usr/bin/env python3
"""
Local dev server + Anthropic proxy for the Tele2 AI prototype.

Threaded variant: uses ThreadingHTTPServer so each request runs in its own
thread. The plain HTTPServer variant (server.py) serialises requests, which
stalls every other client while a single proxy call to Anthropic is in flight
(up to the 60s timeout).

Why a proxy instead of calling api.anthropic.com from the browser:
  - Browsers block cross-origin calls to the Anthropic API (CORS / preflight),
    which shows up as "socket closed" / "Failed to fetch".
  - The API key stays on the server, never shipped to the client.

Run:
  export ANTHROPIC_API_KEY=sk-ant-...
  python3 server_threading.py
  open http://localhost:8000/tele2-yandex-ai.html
"""
import os, json, urllib.request, urllib.error
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

def get_api_key():
    env_key = os.environ.get('ANTHROPIC_API_KEY')
    if env_key:
        return env_key.strip()

API_KEY = get_api_key()

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


class Handler(SimpleHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/api/messages":
            self._err(404, "not_found", self.path)
            return

        if not API_KEY:
            self._err(500, "no_api_key",
                      "ANTHROPIC_API_KEY is not set. Run: export ANTHROPIC_API_KEY=sk-ant-... then restart server_threading.py")
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
        except Exception as e:
            self._err(400, "bad_request", str(e))
            return

        req = urllib.request.Request(
            ANTHROPIC_URL,
            data=body,
            method="POST",
            headers={
                "content-type": "application/json",
                "x-api-key": API_KEY,
                "anthropic-version": "2023-06-01",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()
                self._raw(resp.status, data)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            print(f"[proxy] Anthropic HTTPError {e.code}: {detail}")
            self._raw(e.code, detail.encode("utf-8"))
        except Exception as e:
            # network failure, DNS, timeout, etc. — surface the real reason
            print(f"[proxy] error: {repr(e)}")
            self._err(502, "proxy_error", repr(e))

    def _raw(self, code, data_bytes):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data_bytes)))
        self.end_headers()
        self.wfile.write(data_bytes)

    def _json(self, code, obj):
        self._raw(code, json.dumps(obj).encode("utf-8"))

    def _err(self, code, etype, message):
        # match Anthropic's error envelope so the client reads data.error.message uniformly
        self._json(code, {"type": "error", "error": {"type": etype, "message": message}})

    def log_message(self, fmt, *args):
        print("[server]", fmt % args)


class ThreadedServer(ThreadingHTTPServer):
    # don't keep the process alive on Ctrl+C if a worker is mid-request
    daemon_threads = True
    # allow quick restarts during dev (TIME_WAIT on the listening socket)
    allow_reuse_address = True


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    state = "SET ✓" if API_KEY else "NOT SET ✗  (export ANTHROPIC_API_KEY=...)"
    print(f"ANTHROPIC_API_KEY: {state}")
    print(f"Serving http://localhost:{port}/tele2-yandex-ai.html (threaded)")
    ThreadedServer(("127.0.0.1", port), Handler).serve_forever()
