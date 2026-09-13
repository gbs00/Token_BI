"""Manual native-shell QA only. Bind an unused 8790; never launch real services."""
import json
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import qrcode
import qrcode.image.svg


class Handler(BaseHTTPRequestHandler):
    def respond(self, body):
        raw = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = urlparse(self.path)
        if path.path == "/api/app/health":
            return self.respond({"ok": True, "service": "token-bi-control-panel", "preview": True})
        if path.path == "/api/status":
            now = datetime.now(timezone.utc)
            account = {"masked_email": "demo****@example.com", "status": "active", "account_id": "native-preview"}
            return self.respond({"healthy": True, "running": True, "account": account, "urls": {
                "lan": "http://192.168.1.20:8787/dashboard", "fixed": "http://token-bi-demo.local:8787/dashboard"},
                "log_tail": "Native preview fixture. No real services or credentials.", "dashboard": {
                    "account": account, "state": "ready", "summary": {"source_type": "oauth", "last_success_at": now.isoformat()},
                    "metrics": [{"metric_type": "session", "label": "5h 额度", "remaining_pct": 82, "reset_at": (now + timedelta(hours=3, minutes=38)).isoformat()},
                                {"metric_type": "weekly", "label": "周额度", "remaining_pct": 44, "reset_at": (now + timedelta(days=3, hours=9)).isoformat()}]}})
        if path.path == "/api/pairing":
            kind = parse_qs(path.query).get("kind", ["lan"])[0]
            url = "http://token-bi-demo.local:8787/dashboard" if kind == "fixed" else "http://192.168.1.20:8787/dashboard"
            svg = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, border=4).to_string().decode()
            return self.respond({"ok": True, "url": url, "svg": svg})
        self.send_error(404)

    def do_POST(self):
        if self.path == "/api/start":
            return self.respond({"ok": True})
        if self.path == "/api/refresh-status":
            return self.respond({"ok": False, "message": "预览同步失败：网络连接超时"})
        self.respond({"ok": False, "message": "隔离预览不执行真实账号或服务操作"})


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 8790), Handler)
    print("Isolated native fixture on 8790. Stop after QA.", flush=True)
    server.serve_forever()
