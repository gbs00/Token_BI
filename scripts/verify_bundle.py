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
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener


MAX_BUNDLE_BYTES = 195_000_000


def verify_resources(bundle: Path) -> dict[str, int]:
    contents = bundle.resolve() / "Contents"
    resources = contents / "Resources"
    for name in ("token-bi-control", "token-bi-backend"):
        internal = resources / f"{name}-runtime" / "_internal"
        frameworks = list(internal.glob("Python*.framework"))
        assert len(frameworks) == 1, f"Missing or duplicate Python framework: {name}"
        framework = frameworks[0]
        library = framework.stem
        aliases = (internal / library, framework / library, framework / "Versions/Current")
        assert all(path.is_symlink() for path in aliases), f"Python aliases expanded into copies: {name}"
        assert aliases[0].resolve() == aliases[1].resolve(), f"Python aliases disagree: {name}"
        for path in internal.rglob("*"):
            if path.is_symlink():
                assert path.exists(), f"Broken runtime symlink: {path}"
                assert internal in path.resolve().parents, f"Runtime symlink escapes bundle: {path}"
    assert not list(resources.rglob("control_panel.html")), "Retired console must not ship"

    def file_bytes(path: Path) -> int:
        return sum(item.stat().st_size for item in path.rglob("*") if not item.is_symlink() and item.is_file())

    sizes = {"total": file_bytes(contents), "native": file_bytes(contents / "MacOS"),
             "control": file_bytes(resources / "token-bi-control-runtime"),
             "backend": file_bytes(resources / "token-bi-backend-runtime")}
    assert sizes["total"] <= MAX_BUNDLE_BYTES, f"App exceeds {MAX_BUNDLE_BYTES} byte budget: {sizes}"
    return sizes


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def verify(bundle: Path) -> None:
    print("Bundle bytes (symlinks excluded):", json.dumps(verify_resources(bundle)))
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

    def request(port: int, path: str, method: str = "GET", *, headers: dict | None = None) -> dict:
        with opener.open(Request(f"http://127.0.0.1:{port}{path}", method=method, headers=headers or {}), timeout=40) as response:
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
