"""Serve a built GÅSEN pilot locally, using only Python's standard library."""

import argparse
import functools
import json
import threading
import urllib.request
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/__goosen__":
            data = json.dumps({"app": "goosen-flight", "version": 1}).encode()
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
    url = f"http://127.0.0.1:{args.port}"
    try:
        server = ThreadingHTTPServer(
            ("127.0.0.1", args.port), functools.partial(Handler, directory=str(root))
        )
    except OSError:
        try:
            with urllib.request.urlopen(url + "/__goosen__", timeout=2) as response:
                same_app = json.load(response).get("app") == "goosen-flight"
        except Exception:
            same_app = False
        if not same_app:
            raise SystemExit(f"Port {args.port} is occupied. Try --port 4175.") from None
        if not args.no_browser:
            webbrowser.open(url)
        return
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
