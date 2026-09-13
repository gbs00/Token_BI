"""Isolated UI fixtures; never imports the production container or reads credentials."""
import argparse
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import qrcode
import qrcode.image.svg

ROOT = Path(__file__).resolve().parents[1] / "desktop"


class PreviewHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/preview-qr":
            kind = parse_qs(parsed.query).get("kind", ["lan"])[0]
            urls = {"lan": "http://192.168.1.20:8787/dashboard", "fixed": "http://token-bi-demo.local:8787/dashboard"}
            if kind not in urls:
                self.send_error(400)
                return
            svg = qrcode.make(urls[kind], image_factory=qrcode.image.svg.SvgPathImage, border=4).to_string().decode()
            body = json.dumps({"ok": True, "url": urls[kind], "svg": svg}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8898)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), PreviewHandler)
    print(f"Preview: http://127.0.0.1:{args.port}/preview.html", flush=True)
    server.serve_forever()
