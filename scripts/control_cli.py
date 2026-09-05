from __future__ import annotations

import argparse
import os
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="token-bi-control")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8790)
    parser.add_argument("--main-port", type=int, default=8787)
    parser.add_argument("--stop-dev", choices=["main", "control", "all"])
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.stop_dev:
        from app.process_lifecycle import stop_dev_service, stop_owned_chrome_workers
        root = Path(__file__).resolve().parents[1]
        data_root = Path(os.getenv("TOKEN_BI_APP_DATA_DIR") or root).expanduser().resolve()
        services = ["control", "main"] if args.stop_dev == "all" else [args.stop_dev]
        results = [stop_dev_service(root, service) for service in services]
        if args.stop_dev == "all" and all(results):
            stop_owned_chrome_workers(data_root / "runtime" / "contexts")
        if not all(results):
            raise SystemExit("进程身份不匹配或无法停止，已保留该进程和 PID 文件；未按端口清理。")
        print("已停止对应的开发服务；无 PID 记录时不操作其他进程。")
        return
    os.environ["TOKEN_BI_CONTROL_HOST"] = args.host
    os.environ["TOKEN_BI_CONTROL_PORT"] = str(args.port)
    os.environ["TOKEN_BI_PORT"] = str(args.main_port)

    from scripts.control_panel import main as control_main

    control_main()


if __name__ == "__main__":
    main()
