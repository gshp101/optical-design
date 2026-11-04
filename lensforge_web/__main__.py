"""Build the web app and serve it locally: ``python -m lensforge_web [--port 8000] [--no-browser]``.

The server only hands out files (the lens engine runs in the browser). It sends the
cross-origin isolation headers (COOP/COEP) that let the page's Stop button interrupt a running
optimisation; on other hosts the page's service worker (sw.js) adds them.

``--pyodide DIR_OR_URL`` loads Pyodide from a local copy of the Pyodide distribution (for use
without internet access) instead of the jsDelivr CDN.
"""

from __future__ import annotations

import argparse
import functools
import http.server
import os
import webbrowser

from .build import PYODIDE_CDN, build


class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map, ".js": "text/javascript",
                      ".mjs": "text/javascript", ".wasm": "application/wasm", ".json": "application/json",
                      ".svg": "image/svg+xml", ".zip": "application/zip"}
    local_pyodide = None  # (url prefix, directory)

    def end_headers(self):
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def translate_path(self, path):
        lp = self.local_pyodide
        if lp and path.split("?", 1)[0].startswith(lp[0]):
            rel = path.split("?", 1)[0][len(lp[0]):]
            return os.path.join(lp[1], *[p for p in rel.split("/") if p and p != ".."])
        return super().translate_path(path)

    def log_message(self, fmt, *args):  # quiet
        pass


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m lensforge_web", description="Build and serve the LensForge web app")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--out", help="build directory (default: web-dist in the repository)")
    ap.add_argument("--pyodide", default=PYODIDE_CDN, help="Pyodide URL, or a local Pyodide directory")
    ap.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    a = ap.parse_args(argv)
    url = a.pyodide
    if os.path.isdir(a.pyodide):
        Handler.local_pyodide = ("/pyodide/", os.path.abspath(a.pyodide))
        url = "pyodide/"
    out = build(a.out, url)
    server = http.server.ThreadingHTTPServer((a.host, a.port), functools.partial(Handler, directory=out))
    addr = f"http://{a.host}:{server.server_address[1]}/"
    print(f"LensForge web app at {addr}  (Ctrl+C stops the server)")
    if not a.no_browser:
        webbrowser.open(addr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
