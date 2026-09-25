"""在隔离数据和本地额度接口下验证打包服务，不访问用户授权。"""
from __future__ import annotations

import argparse
import base64
import json
import os
import plistlib
import socket
import subprocess
import tempfile
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener


MAX_BUNDLE_BYTES = 50_000_000


def verify_resources(bundle: Path) -> dict[str, int]:
    contents = bundle.resolve() / "Contents"
    resources = contents / "Resources"
    runtime = resources / "token-bi-runtime"
    internal = runtime / "_internal"
    for name in ("token-bi-control", "token-bi-backend"):
        assert not (resources / f"{name}-runtime").exists(), f"Separate runtime must not ship: {name}"
        binary = runtime / name
        assert binary.is_file() and os.access(binary, os.X_OK), f"Missing service entrypoint: {name}"
    frameworks = list(resources.rglob("Python*.framework"))
    assert len(frameworks) == 1 and frameworks[0].parent == internal, "Missing or duplicate Python framework"
    assert list(resources.rglob("base_library.zip")) == [internal / "base_library.zip"], (
        "Missing or duplicate base_library"
    )
    framework = frameworks[0]
    library = framework.stem
    aliases = (internal / library, framework / library, framework / "Versions/Current")
    assert all(path.is_symlink() for path in aliases), "Python aliases expanded into copies"
    assert aliases[0].resolve() == aliases[1].resolve(), "Python aliases disagree"
    for path in internal.rglob("*"):
        if path.is_symlink():
            assert path.exists(), f"Broken runtime symlink: {path}"
            assert internal in path.resolve().parents, f"Runtime symlink escapes bundle: {path}"
    assert not list(resources.rglob("control_panel.html")), "Retired console must not ship"
    assert not list(resources.rglob("playwright")), "Playwright must not ship"
    assert not list(resources.rglob("node")), "Node runtime must not ship"
    web_session = resources / "Token BI Web Session.app/Contents/MacOS/TokenBIWebSession"
    assert web_session.is_file() and os.access(web_session, os.X_OK), "Missing native web session"

    def file_bytes(path: Path) -> int:
        return sum(item.stat().st_size for item in path.rglob("*") if not item.is_symlink() and item.is_file())

    sizes = {"total": file_bytes(contents), "native": file_bytes(contents / "MacOS"),
             "runtime": file_bytes(runtime),
             "web_session": file_bytes(resources / "Token BI Web Session.app")}
    assert sizes["total"] <= MAX_BUNDLE_BYTES, f"App exceeds {MAX_BUNDLE_BYTES} byte budget: {sizes}"
    return sizes


def verify_python_archives(runtime: Path) -> None:
    from PyInstaller.archive.readers import CArchiveReader

    for name in ("token-bi-control", "token-bi-backend"):
        archive = CArchiveReader(str(runtime / name))
        modules = set()
        for member, entry in archive.toc.items():
            if entry[-1] == "z":
                modules.update(archive.open_embedded_archive(member).toc)
        required = ({"httpx._client", "pydantic", "uvicorn"} if name.endswith("backend")
                    else {"psutil", "qrcode.image.svg"})
        assert required <= modules, f"Missing Python dependencies: {name}"
        forbidden = ("httpx._main", "pygments", "playwright", "pytest")
        assert not any(module == prefix or module.startswith(prefix + ".")
                       for prefix in forbidden for module in modules), f"Unused Python dependencies bundled: {name}"


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


@contextmanager
def usage_fixture():
    offline = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            authorized = (self.path == "/usage"
                          and self.headers.get("Authorization", "").startswith("Bearer e30."))
            payload = {"rate_limit": {"primary_window": {
                "used_percent": 23, "limit_window_seconds": 18000, "reset_at": 2000000000,
            }}}
            data = json.dumps(payload if authorized and not offline.is_set() else {}).encode()
            self.send_response(503 if offline.is_set() else (200 if authorized else 401))
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/usage", offline
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def verify(bundle: Path) -> None:
    print("Bundle bytes (symlinks excluded):", json.dumps(verify_resources(bundle)))
    contents = bundle.resolve() / "Contents"
    info = plistlib.loads((contents / "Info.plist").read_bytes())
    expected = json.loads((Path(__file__).resolve().parents[1] / "package.json").read_text())["version"]
    assert info["CFBundleShortVersionString"] == expected
    resources = contents / "Resources"
    runtime = resources / "token-bi-runtime"
    verify_python_archives(runtime)
    control = contents / "MacOS/token-bi-control"
    backend = runtime / "token-bi-backend"
    assert control.is_file() and backend.is_file()
    control_port, main_port = free_port(), free_port()
    while control_port == main_port:
        main_port = free_port()
    opener = build_opener(ProxyHandler({}))

    def request(port: int, path: str, method: str = "GET", *, headers: dict | None = None) -> dict:
        with opener.open(Request(f"http://127.0.0.1:{port}{path}", method=method, headers=headers or {}), timeout=40) as response:
            return json.load(response)

    with tempfile.TemporaryDirectory(prefix="token-bi-bundle-check-") as directory, usage_fixture() as (usage_url, offline):
        root = Path(directory)
        (root / "config").mkdir()
        (root / "config/accounts.json").write_text(json.dumps({"accounts": [], "access_enabled": False}))
        codex_home = root / "codex"
        codex_home.mkdir()
        identity = {"email": "fixture@example.test", "exp": 4102444800}
        claims = base64.urlsafe_b64encode(json.dumps(identity).encode()).decode().rstrip("=")
        auth = json.dumps({"tokens": {"access_token": f"e30.{claims}.fixture"}})
        auth_file = codex_home / "auth.json"
        auth_file.write_text(auth)
        env = {**os.environ, "TOKEN_BI_APP_DATA_DIR": directory,
               "TOKEN_BI_MAIN_BACKEND_BIN": str(backend), "TOKEN_BI_HOST": "127.0.0.1",
               "HOME": directory, "CODEX_HOME": str(codex_home), "NO_PROXY": "*", "no_proxy": "*",
               "TOKEN_BI_CODEX_OAUTH_USAGE_URL": usage_url,
               "TOKEN_BI_CODEX_CLI_BIN": str(root / "missing-codex"),
               "TOKEN_BI_WEB_SESSION_BIN": str(root / "missing-web-session"),
               "TOKEN_BI_PORT_MAX": str(min(65535, main_port + 5))}
        with (root / "control.log").open("wb") as log:
            process = subprocess.Popen([str(control), "--host", "127.0.0.1", "--port", str(control_port),
                                        "--main-port", str(main_port)], env=env, stdout=log, stderr=log)
            ready = False
            try:
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline and process.poll() is None:
                    try:
                        health = request(control_port, "/api/app/health")
                        ready = health.get("service") == "token-bi-control-panel"
                        if ready:
                            break
                    except OSError:
                        time.sleep(0.1)
                assert ready, "Packaged control did not become ready"
                try:
                    opener.open(f"http://127.0.0.1:{control_port}/", timeout=5)
                except HTTPError as exc:
                    assert exc.code == 404
                else:
                    raise AssertionError("Retired console is still served")
                assert request(control_port, "/api/start", "POST")["ok"]
                status = request(control_port, "/api/status")
                assert status["healthy"] and status["access_enabled"] is False
                assert status["dashboard"]["metrics"] == []
                main_port = status["port"]
                assert request(main_port, "/api/v1/health")["version"] == expected
                with opener.open(f"http://127.0.0.1:{main_port}/dashboard", timeout=5) as response:
                    assert "20260913-fit-viewport" in response.read().decode()
                with opener.open(f"http://127.0.0.1:{main_port}/static/js/dashboard.js", timeout=5) as response:
                    assert b"visualViewport" in response.read()
                pairing = request(control_port, "/api/pairing?kind=fixed")
                assert pairing["ok"] and "<svg" in pairing["svg"]
                assert f":{main_port}/dashboard" in pairing["url"]
                print(f"Packaged {expected}: control, backend, paused access, dashboard, assets and QR passed.")
                assert request(main_port, "/api/v1/account-session/login", "POST")["ok"]
                current = request(main_port, "/api/v1/dashboard")
                assert current["state"] == "ready" and current["summary"]["source_type"] == "oauth"
                assert current["metrics"][0]["remaining_pct"] == 77
                offline.set()
                stale = request(main_port, "/api/v1/dashboard/refresh", "POST")
                assert stale["state"] == "stale" and stale["metrics"] == current["metrics"]
                assert stale["summary"]["last_success_at"] == current["summary"]["last_success_at"]
                offline.clear()
                assert request(main_port, "/api/v1/dashboard/refresh", "POST")["state"] == "ready"
                assert request(main_port, "/api/v1/account-session/logout", "POST")["action"] == "logout"
                assert auth_file.read_text() == auth, "Logout changed external credentials"
                assert request(main_port, "/api/v1/dashboard")["metrics"] == []
                print("Packaged OAuth fixture, failed-upstream cache, recovery and logout passed.")
            finally:
                try:
                    if ready:
                        assert request(control_port, "/api/app/shutdown", "POST", headers={
                            "X-Token-BI-Control-Pid": str(process.pid),
                        })["ok"]
                    process.wait(timeout=10)
                finally:
                    if process.poll() is None:
                        process.terminate()
                        process.wait(timeout=10)
            assert process.returncode == 0
            with socket.socket() as probe:
                assert probe.connect_ex(("127.0.0.1", main_port)) != 0, "Backend survived shutdown"
            print("Packaged shutdown passed; installed App and user account data were not changed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    verify(parser.parse_args().bundle)
