"""Smoke-test packaged services with paused account access and temporary data."""
from __future__ import annotations

import argparse
import json
import os
import plistlib
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def verify(bundle: Path) -> None:
    contents = bundle.resolve() / "Contents"
    info = plistlib.loads((contents / "Info.plist").read_bytes())
    expected = json.loads((Path(__file__).resolve().parents[1] / "package.json").read_text())["version"]
    assert info["CFBundleShortVersionString"] == expected
    resources = contents / "Resources"
    control = resources / "token-bi-control-runtime" / "token-bi-control"
    backend = resources / "token-bi-backend-runtime" / "token-bi-backend"
    assert control.is_file() and backend.is_file()
    control_port, main_port = free_port(), free_port()
    while control_port == main_port:
        main_port = free_port()
    opener = build_opener(ProxyHandler({}))

    def request(port: int, path: str, method: str = "GET") -> dict:
        with opener.open(Request(f"http://127.0.0.1:{port}{path}", method=method), timeout=40) as response:
            return json.load(response)

    with tempfile.TemporaryDirectory(prefix="token-bi-bundle-check-") as directory:
        root = Path(directory)
        (root / "config").mkdir()
        (root / "config/accounts.json").write_text(json.dumps({"accounts": [], "access_enabled": False}))
        env = {**os.environ, "TOKEN_BI_APP_DATA_DIR": directory,
               "TOKEN_BI_MAIN_BACKEND_BIN": str(backend), "TOKEN_BI_HOST": "127.0.0.1",
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
            finally:
                try:
                    if ready:
                        assert request(control_port, "/api/app/shutdown", "POST")["ok"]
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
