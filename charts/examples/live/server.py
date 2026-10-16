#!/usr/bin/env python3
"""Static + proxy server for the OpenAlgo LIVE demo.

Serves the openalgo-charts package root AND reverse-proxies `/api/v1/*` to a
running OpenAlgo instance, so the browser demo can call OpenAlgo's REST API from
the SAME origin (OpenAlgo does not send CORS headers, so a direct cross-origin
fetch from the demo would be blocked).

The WebSocket feed is NOT proxied: the browser connects straight to OpenAlgo's
WS proxy (default ws://127.0.0.1:8765); WebSocket upgrades aren't subject to the
CORS preflight that blocks the REST calls.

Usage:
    python server.py                 # serves on http://127.0.0.1:8001
    python server.py 8123            # custom port
    OPENALGO_HOST=http://127.0.0.1:5000 python server.py   # custom OpenAlgo host

Then open:  http://127.0.0.1:8001/examples/live/index.html

NOTE: your OpenAlgo API key is entered in the page (saved to the browser's
localStorage) and forwarded in the request body: it is never stored in this repo.
"""
import os
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

# Package root (two levels up from examples/live/), so /dist and /examples resolve.
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OPENALGO_HOST = os.environ.get("OPENALGO_HOST", "http://127.0.0.1:5000").rstrip("/")


class Handler(SimpleHTTPRequestHandler):
    # ES modules must be served with a JS MIME type (browsers reject text/plain modules).
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".mjs": "application/javascript",
        ".js": "application/javascript",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def do_POST(self):  # noqa: N802 (stdlib naming)
        if self.path.startswith("/api/v1/"):
            return self._proxy()
        self.send_error(404, "Not Found")

    def _proxy(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b""
        url = OPENALGO_HOST + self.path
        req = urlrequest.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
        try:
            with urlrequest.urlopen(req, timeout=30) as resp:
                payload, code = resp.read(), resp.status
        except HTTPError as e:  # forward OpenAlgo's error body + status
            payload, code = e.read(), e.code
        except URLError as e:
            payload = ('{"status":"error","message":"cannot reach OpenAlgo at %s: %s"}'
                       % (OPENALGO_HOST, e.reason)).encode("utf-8")
            code = 502
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8001
    print("openalgo-charts LIVE demo -> http://127.0.0.1:%d/examples/live/index.html" % port)
    print("proxying /api/v1/* -> %s" % OPENALGO_HOST)
    print("serving package root: %s" % ROOT)
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
