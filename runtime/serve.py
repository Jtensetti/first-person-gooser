"""Serve a built GÅSEN pilot locally, using only Python's standard library."""

import argparse
import functools
import hashlib
import json
import socket
import threading
import urllib.request
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class LocalServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def server_bind(self):
        # SO_REUSEADDR on Windows would allow a second server on the same port.
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class Handler(SimpleHTTPRequestHandler):
    build_id = ""

    def do_GET(self):
        if self.path == "/__goosen__":
            data = json.dumps({"app": "goosen-flight", "version": 1, "build_id": self.build_id}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            super().do_GET()

    def log_message(self, format, *args):
        if args and str(args[1] if len(args) > 1 else "") not in ("200", "304"):
            super().log_message(format, *args)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=4174)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    if (root / "dist" / "index.html").exists():
        root /= "dist"
    if not (root / "index.html").exists() or not (root / "world" / "world.json").exists():
        raise SystemExit("Missing built pilot. Keep start.py beside index.html and world/.")
    Handler.build_id = hashlib.sha256(
        (root / "index.html").read_bytes() + (root / "world" / "world.json").read_bytes()
    ).hexdigest()
    for port in range(args.port, min(args.port + 10, 65536)):
        url = f"http://127.0.0.1:{port}"
        try:
            server = LocalServer(("127.0.0.1", port), functools.partial(Handler, directory=str(root)))
            break
        except OSError:
            try:
                with urllib.request.urlopen(url + "/__goosen__", timeout=2) as response:
                    existing = json.load(response)
                same_build = (
                    existing.get("app") == "goosen-flight" and existing.get("build_id") == Handler.build_id
                )
            except Exception:
                same_build = False
            if same_build:
                if not args.no_browser:
                    webbrowser.open(url)
                return
    else:
        raise SystemExit("No free local port. Choose another --port.")
    print(f"GASEN: {url}\nKeep this window open. Ctrl+C stops the local server.", flush=True)
    if not args.no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
