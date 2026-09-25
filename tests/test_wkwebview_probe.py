"""在真正的 macOS WKWebView 中运行隔离 HTTP fixtures，不访问真实账号。"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from app.services.usage_connectors import normalize_usage_payload

ROOT = Path(__file__).resolve().parents[1]
EXECUTABLE = ROOT / "dist/wkwebview-probe/Token BI Web Probe.app/Contents/MacOS/TokenBIWebProbe"
pytestmark = pytest.mark.skipif(
    sys.platform != "darwin" or os.getenv("TOKEN_BI_NATIVE_WK_TEST") != "1",
    reason="原生 WKWebView 测试需显式启用且已构建验证 App",
)


class FixtureServer(ThreadingHTTPServer):
    daemon_threads = True
    case = "cookie"
    sessions = 0
    usage_requests = 0


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def respond(self, body, status=200, headers=None):
        data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json" if not isinstance(body, str) else "text/html")
        self.send_header("Content-Length", str(len(data)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        case = self.server.case
        if self.path.startswith("/fixture"):
            headers = {} if case == "persist-read" else {"Set-Cookie": "fixture_session=present; HttpOnly; Max-Age=3600; Path=/"}
            text = "Just a moment" if case == "challenge" else "Token BI local fixture"
            if case == "dom":
                text += "<p>Weekly 82% left Resets in 6d 12h</p>"
            if case == "navigation-blocked":
                text += '<script>location.replace("https://example.com/blocked")</script>'
            if case.startswith("login-"):
                text += self.login_fixture(case)
            self.respond(f"<!doctype html><meta charset=utf-8><h1>{text}</h1>", headers=headers)
        elif self.path == "/api/auth/session":
            self.server.sessions += 1
            if case == "expired-session":
                self.respond({})
                return
            if case == "identity-check-offline" and self.server.sessions > 1:
                self.respond({}, 503)
                return
            email = "alice@example.test"
            if case == "identity-changed" and self.server.sessions > 1:
                email = "bob@example.test"
            result = {"user": {"email": email}, "do_not_export": "session_secret_fixture"}
            if case == "identity-missing":
                result["user"] = {}
            if case in {"bearer", "rejected-bearer"}:
                result["accessToken"] = "fixture-access-token"
            if case == "empty-token":
                result["accessToken"] = ""
            if case == "token-renewal":
                result["accessToken"] = "fixture-stale-token" if self.server.sessions == 1 else "fixture-access-token"
            self.respond(result)
        elif self.path == "/backend-api/wham/usage":
            self.server.usage_requests += 1
            if case == "token-renewal" and self.headers.get("Authorization") != "Bearer fixture-access-token":
                self.respond({}, 401)
                return
            if case == "timeout":
                time.sleep(1)
            status = {"unauthorized": 401, "rejected-bearer": 401, "denied": 403, "challenge": 403,
                      "limited": 429, "server-error": 503}.get(case)
            if status:
                self.respond({"private_error": "must_not_export"}, status)
                return
            if case == "redirect":
                self.respond({}, 302, {"Location": "/must-not-follow"})
                return
            if case in {"invalid", "dom"}:
                self.respond("not JSON: private-content")
                return
            if case == "oversize":
                self.respond({"large": "x" * (600 * 1024)})
                return
            if case == "missing-window":
                self.respond({"rate_limit": {"primary_window": None}})
                return
            if "fixture_session=present" not in self.headers.get("Cookie", ""):
                self.respond({}, 401)
                return
            if case == "bearer" and self.headers.get("Authorization") != "Bearer fixture-access-token":
                self.respond({}, 401)
                return
            self.respond({
                "rate_limit": {
                    "primary_window": {"used_percent": 100, "limit_window_seconds": 18000,
                                       "reset_at": 2000000000, "ignore": "sensitive_extra"},
                    "secondary_window": {"used_percent": 18, "limit_window_seconds": 604800,
                                         "reset_at": 2000100000},
                },
                "rate_limit_reset_credits": {"available_count": 2},
                "private_secret": "secret-should-never-cross-native-bridge",
            })
        elif self.path == "/backend-api/wham/rate-limit-reset-credits":
            if case == "reset-error":
                self.respond({}, 503)
                return
            self.respond({"available_count": 2, "credits": [
                {"id": "sensitive-credit-id", "status": "available", "reset_type": "codex_rate_limits", "expires_at": 2000200000},
                {"id": "sensitive-credit-id", "status": "available", "reset_type": "codex_rate_limits", "expires_at": 2000200000},
                {"id": "second-credit", "status": "available", "reset_type": "codex_rate_limits", "expires_at": "2033-05-18T01:00:00Z"},
                {"id": "used-credit", "status": "used", "reset_type": "codex_rate_limits", "expires_at": 2000000000},
            ]})
        else:
            self.server.unexpected.append(self.path)
            self.respond({}, 404)

    def login_fixture(self, case):
        form = ('<form method="POST" action="/api/accounts/password">'
                '<input type="password" name="password" required value="fixture-password-never-log">'
                '<button type="submit">Continue</button></form>')
        actions = {
            "login-fetch": '''document.querySelector('form').onsubmit = event => {
                event.preventDefault();
                fetch('/api/accounts/password?secret=query-secret-never-log', {
                    method: 'POST', headers: {'X-Secret': 'header-secret-never-log'},
                    body: 'fixture-password-never-log',
                }).then(response => response.json()).then(value => {
                    if (value.ok !== true) throw new Error('wrong response');
                });
            }; document.querySelector('button').click();''',
            "login-post": "document.querySelector('button').click();",
            "login-invalid": "document.querySelector('input').value = ''; document.querySelector('button').click();",
            "login-script-error": "setTimeout(() => { throw new TypeError('error-secret-never-log'); }, 0);",
            "login-xhr": '''const xhr = new XMLHttpRequest();
                xhr.open('POST', '/api/accounts/password?secret=query-secret-never-log');
                xhr.send('fixture-password-never-log');''',
            "login-dialogs": '''alert('dialog-secret-never-log');
                if (confirm('dialog-secret-never-log')) throw new Error('should cancel');
                if (prompt('dialog-secret-never-log', 'prompt-secret-never-log') !== null) throw new Error('should cancel');''',
            "login-filter": '''webkit.messageHandlers.probeDiagnostics.postMessage({
                event: 'fetch_end', target: 'header-secret-never-log', route: 'query-secret-never-log',
                status: 200, error_kind: 'error-secret-never-log', password: 'fixture-password-never-log',
            });''',
        }
        return form + "<script>document.addEventListener('DOMContentLoaded', () => {" + actions[case] + "});</script>"

    def do_POST(self):
        # 只处理测试密码，禁止真实网络和真实凭据进入用例。
        assert urlsplit(self.path).path == "/api/accounts/password"
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        assert b"fixture-password-never-log" in body
        self.server.posts += 1
        if self.server.case == "login-post":
            self.respond("<!doctype html><h1>Signed in fixture</h1>")
        else:
            self.respond({"ok": True, "secret": "response-secret-never-log"}, 200 if self.server.case == "login-fetch" else 403)


@pytest.fixture
def server():
    instance = FixtureServer(("127.0.0.1", 0), Handler)
    instance.unexpected = []
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    yield instance
    instance.shutdown()
    instance.server_close()
    thread.join(timeout=2)


def run_probe(server, tmp_path, case, *arguments):
    assert EXECUTABLE.exists(), "先运行 scripts/build_wkwebview_probe.py"
    server.case = case
    server.sessions = 0
    server.posts = 0
    result = tmp_path / f"{case}.json"
    subprocess.run([
        str(EXECUTABLE), "--self-test", f"http://127.0.0.1:{server.server_port}/fixture/{case}",
        "--result", str(result), *arguments,
    ], check=True, capture_output=True, timeout=45)
    assert result.exists()
    text = result.read_text()
    for secret in ["fixture-access-token", "session_secret_fixture", "alice@example.test", "bob@example.test",
                   "private-content", "sensitive_extra", "sensitive-credit-id", "secret-should-never-cross-native-bridge",
                   "fixture-password-never-log", "query-secret-never-log", "header-secret-never-log",
                   "error-secret-never-log", "dialog-secret-never-log", "prompt-secret-never-log", "response-secret-never-log"]:
        assert secret not in text
    assert result.stat().st_mode & 0o777 == 0o600
    assert not server.unexpected
    return json.loads(text)


@pytest.mark.parametrize("case", ["cookie", "bearer", "empty-token"])
def test_native_read_and_existing_normalizer(server, tmp_path, case):
    result = run_probe(server, tmp_path, case)
    assert result["category"] == "success", result
    assert result["identity"]["key"] == hashlib.sha256(b"alice@example.test").hexdigest()
    assert result["authorization"] == {
        "access_token_present": case == "bearer",
        "usage_request": "bearer_with_session" if case == "bearer" else "session_cookie",
    }
    data = normalize_usage_payload(result["usage"], "web_session", "wkwebview_probe")
    assert [row["remaining_pct"] for row in data["windows"]] == [0, 82]
    assert [row["window_minutes"] for row in data["windows"]] == [300, 10080]
    assert data["reset_credits"]["available_count"] == 2
    assert len(data["reset_credits"]["expires_at"]) == 2


def test_access_token_presence_does_not_imply_authorized_usage(server, tmp_path):
    result = run_probe(server, tmp_path, "rejected-bearer")
    assert result["authorization"]["access_token_present"] is True
    assert result["category"] == "auth_required"
    assert not result.get("usage")


@pytest.mark.parametrize("case,category", [
    ("unauthorized", "auth_required"), ("denied", "access_denied"),
    ("challenge", "challenge"), ("limited", "rate_limited"),
    ("server-error", "network_error"), ("timeout", "timeout"),
    ("invalid", "schema_changed"), ("missing-window", "schema_changed"),
    ("oversize", "schema_changed"), ("redirect", "network_error"),
    ("identity-missing", "identity_unknown"), ("identity-changed", "identity_changed"),
    ("navigation-blocked", "navigation_blocked"), ("dom", "dom_candidate"),
])
def test_native_failures_are_not_login_errors(server, tmp_path, case, category):
    result = run_probe(server, tmp_path, case)
    assert result["category"] == category, result
    assert not result.get("usage")


def test_native_rejects_other_account(server, tmp_path):
    result = run_probe(server, tmp_path, "cookie", "--expected-identity", "other-account")
    assert result["category"] == "account_mismatch"
    assert not result.get("usage")


def test_native_cookie_persists_across_processes(server, tmp_path):
    profile = str(uuid.uuid4())
    written = run_probe(server, tmp_path, "persist-write", "--test-profile", profile)
    assert written["category"] == "success", written
    restored = run_probe(server, tmp_path, "persist-read", "--test-profile", profile)
    assert restored["category"] == "success", restored
    assert restored["identity"] == written["identity"]


@pytest.mark.parametrize("case,events,posts", [
    ("login-fetch", {"submit_click", "form_submit", "fetch_start", "fetch_end"}, 1),
    ("login-post", {"submit_click", "form_submit", "navigation_response"}, 1),
    ("login-invalid", {"submit_click", "invalid_input"}, 0),
    ("login-script-error", {"script_error"}, 0),
    ("login-xhr", {"xhr_start", "xhr_end"}, 1),
    ("login-dialogs", {"dialog_alert", "dialog_confirm", "dialog_prompt"}, 0),
    ("login-filter", {"fetch_end"}, 0),
])
def test_native_login_diagnostics_preserve_behavior_and_redact(server, tmp_path, case, events, posts):
    result = run_probe(server, tmp_path, case, "--collect-delay", "0.5")
    assert result["category"] == "success", result
    rows = result["diagnostics"]
    assert events <= {row["event"] for row in rows}, rows
    assert server.posts == posts
    if case == "login-fetch":
        assert any(row["event"] == "fetch_end" and row["status"] == 200 and row["route"] == "password" for row in rows)
    if case == "login-xhr":
        assert any(row["event"] == "xhr_end" and row["status"] == 403 for row in rows)
    if case == "login-invalid":
        assert "form_submit" not in {row["event"] for row in rows}


@pytest.mark.parametrize("target,source,frame,expected", [
    ("https://sentinel.openai.com/backend-api/sentinel/frame.html", "https://auth.openai.com/log-in/password", "subframe", "allowed"),
    ("https://sentinel.openai.com/frame", "https://chatgpt.com/auth/login", "subframe", "allowed"),
    ("https://sentinel.openai.com/frame", "https://auth.openai.com/log-in", "main", "blocked"),
    ("https://sentinel.openai.com/frame", "https://untrusted.example.test", "subframe", "blocked"),
    ("https://sentinel.openai.com.evil.test/frame", "https://auth.openai.com/log-in", "subframe", "blocked"),
    ("http://sentinel.openai.com/frame", "https://auth.openai.com/log-in", "subframe", "blocked"),
    ("https://sentinel.openai.com:444/frame", "https://auth.openai.com/log-in", "subframe", "blocked"),
    ("https://sentinel.openai.com/frame", "http://auth.openai.com/log-in", "subframe", "blocked"),
    ("https://user:secret@sentinel.openai.com/frame", "https://auth.openai.com/log-in", "subframe", "blocked"),
])
def test_auth_frame_policy(target, source, frame, expected):
    result = subprocess.run([str(EXECUTABLE), "--check-auth-frame-policy", target, source, frame],
                            check=True, capture_output=True, text=True, timeout=10)
    assert result.stdout.strip() == expected
