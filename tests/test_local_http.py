import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError

import pytest

from app.local_http import open_local_url
from scripts import control_panel


@pytest.fixture
def local_server():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "http://external.invalid/")
            else:
                self.send_response(200)
            self.end_headers()
            self.wfile.write(b'[]' if self.path == "/invalid" else b'{"ok":true}')

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        worker.join(2)


def test_local_backend_and_browser_probes_ignore_proxies(local_server, monkeypatch, container):
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.setenv(key, "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "")
    monkeypatch.setenv("no_proxy", "")
    monkeypatch.setattr(control_panel, "_current_main_port", lambda: local_server.server_port)
    assert control_panel._main_api_request("GET", "/health") == {"ok": True}
    assert container.browser_worker_service._debug_port_ready(local_server.server_port) is True


def test_local_transport_does_not_follow_redirects(local_server):
    with pytest.raises(HTTPError) as error:
        open_local_url(f"http://127.0.0.1:{local_server.server_port}/redirect", timeout=1)
    assert error.value.code == 302


def test_malformed_main_payload_is_a_recoverable_transport_error(local_server, monkeypatch):
    monkeypatch.setattr(control_panel, "_current_main_port", lambda: local_server.server_port)
    with pytest.raises(RuntimeError, match="JSON object"):
        control_panel._main_api_request("GET", "/invalid")


@pytest.mark.parametrize("url", ["https://127.0.0.1/", "http://external.invalid/", "file:///tmp/nope"])
def test_local_transport_rejects_non_loopback_http(url):
    with pytest.raises(ValueError):
        open_local_url(url, timeout=1)
