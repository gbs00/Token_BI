"""Serve the real dashboard template with sample quotas and no production services."""
import argparse
import json
import mimetypes
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app/static"
TEMPLATES = Environment(loader=FileSystemLoader(ROOT / "app/templates"), autoescape=select_autoescape())


def sample_dashboard(single=False):
    now = datetime.now(timezone.utc)
    metrics = [
        {"metric_type": "session", "label": "5h 额度", "remaining_pct": 100, "reset_at": now + timedelta(hours=4)},
        {"metric_type": "weekly", "label": "周额度", "remaining_pct": 61, "reset_at": now + timedelta(days=6, hours=23)},
    ]
    return {"state": "ready", "message": None,
            "account": {"account_id": "preview-single" if single else "preview-double", "masked_email": "demo****@example.com"},
            "metrics": metrics[1:] if single else metrics,
            "summary": {"source_type": "local_snapshot", "updated_at": now, "last_success_at": now,
                        "next_sync_at": now + timedelta(minutes=3)}}


class Handler(BaseHTTPRequestHandler):
    def send_content(self, body, content_type):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlsplit(self.path)
        query = parse_qs(url.query)
        single = query.get("windows") == ["1"] or query.get("account_id") == ["preview-single"]
        payload = sample_dashboard(single)
        if url.path in {"/", "/dashboard"}:
            payload["state"] = SimpleNamespace(value=payload["state"])
            html = TEMPLATES.get_template("dashboard.html").render(
                dashboard=payload, selected_account_id=payload["account"]["account_id"],
                url_for=lambda _name, path: "/static/" + path)
            self.send_content(html.encode(), "text/html; charset=utf-8")
        elif url.path in {"/api/v1/dashboard", "/api/v1/dashboard/refresh"}:
            self.send_content(json.dumps(payload, default=lambda value: value.isoformat()).encode(), "application/json")
        elif url.path.startswith("/static/"):
            path = (STATIC / url.path[len("/static/"):]).resolve()
            if not path.is_relative_to(STATIC) or not path.is_file():
                self.send_error(404)
                return
            self.send_content(path.read_bytes(), mimetypes.guess_type(path)[0] or "application/octet-stream")
        else:
            self.send_error(404)

    def do_POST(self):
        if urlsplit(self.path).path != "/api/v1/dashboard/refresh":
            self.send_error(404)
            return
        self.do_GET()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8899)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Sample dashboard: http://127.0.0.1:{server.server_port}/dashboard", flush=True)
    server.serve_forever()
