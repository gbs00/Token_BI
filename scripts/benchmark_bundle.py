"""测量隔离数据目录下的打包服务启动耗时，不读取用户账号或启动采集。"""
from __future__ import annotations

import argparse
import json
import os
import plistlib
import statistics
import subprocess
import tempfile
import time
from pathlib import Path

import psutil

from verify_bundle import free_port
from urllib.request import ProxyHandler, Request, build_opener


def benchmark(bundle: Path, runs: int) -> dict:
    contents = bundle.resolve() / "Contents"
    resources = contents / "Resources"
    info = plistlib.loads((contents / "Info.plist").read_bytes())
    shared = resources / "token-bi-runtime"
    # 仅基准工具兼容旧包，便于在同一轮测量精简前后的启动表现。
    backend = (shared if shared.is_dir() else resources / "token-bi-backend-runtime") / "token-bi-backend"
    runtimes = [shared] if shared.is_dir() else [resources / f"token-bi-{name}-runtime" for name in ("control", "backend")]
    sizes = {name: sum(p.stat().st_size for directory in directories for p in directory.rglob("*")
                       if p.is_file() and not p.is_symlink())
             for name, directories in [("app", [contents]), ("python_runtime", runtimes)]}
    samples = []
    opener = build_opener(ProxyHandler({}))
    for _ in range(runs):
        with tempfile.TemporaryDirectory(prefix="token-bi-benchmark-") as directory:
            root = Path(directory)
            (root / "config").mkdir()
            (root / "config/accounts.json").write_text('{"accounts":[],"access_enabled":false}')
            port, main_port = free_port(), free_port()
            while main_port == port:
                main_port = free_port()
            env = {**os.environ, "TOKEN_BI_APP_DATA_DIR": directory,
                   "TOKEN_BI_MAIN_BACKEND_BIN": str(backend),
                   "TOKEN_BI_HOST": "127.0.0.1", "TOKEN_BI_PORT_MAX": str(main_port)}
            def request(path, method="GET", headers=None):
                with opener.open(Request(f"http://127.0.0.1:{port}{path}", method=method,
                                         headers=headers or {}), timeout=35) as response:
                    return json.load(response)
            start = time.perf_counter()
            process = subprocess.Popen([str(contents / "MacOS/token-bi-control"),
                                        "--host", "127.0.0.1", "--port", str(port), "--main-port", str(main_port)],
                                       env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            ready = False
            try:
                while time.perf_counter() - start < 30 and process.poll() is None:
                    try:
                        ready = request("/api/app/health").get("service") == "token-bi-control-panel"
                        if ready:
                            break
                    except OSError:
                        time.sleep(.02)
                assert ready, "Control not ready"
                control_ms = (time.perf_counter() - start) * 1000
                main_start = time.perf_counter()
                assert request("/api/start", "POST")["ok"]
                state = request("/api/status")
                assert state["healthy"] and state["access_enabled"] is False
                backend_ms = (time.perf_counter() - main_start) * 1000
                tree = [psutil.Process(process.pid), *psutil.Process(process.pid).children(recursive=True)]
                samples.append({"control_ms": round(control_ms, 2), "backend_ms": round(backend_ms, 2),
                                "total_ms": round((time.perf_counter() - start) * 1000, 2),
                                "rss_bytes": sum(p.memory_info().rss for p in tree if p.is_running()),
                                "process_count": len(tree)})
            finally:
                try:
                    if ready:
                        request("/api/app/shutdown", "POST", {"X-Token-BI-Control-Pid": str(process.pid)})
                    process.wait(timeout=12)
                finally:
                    if process.poll() is None:
                        process.terminate()
                        process.wait(timeout=12)
    return {"version": info["CFBundleShortVersionString"], "bundle": str(bundle), "bytes": sizes,
            "scope": "isolated packaged services; access paused; not full GUI launch or upstream network",
            "samples": samples, "median": {k: statistics.median(s[k] for s in samples) for k in samples[0]}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assert 1 <= args.runs <= 20
    result = benchmark(args.bundle, args.runs)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
