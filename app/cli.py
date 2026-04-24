from __future__ import annotations

import argparse
import os


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="token-bi-backend")
    subparsers = parser.add_subparsers(dest="command", required=True)

    control = subparsers.add_parser("control-panel")
    control.add_argument("--host", default="127.0.0.1")
    control.add_argument("--port", type=int, default=8790)
    control.add_argument("--main-port", type=int, default=8787)

    main = subparsers.add_parser("main-server")
    main.add_argument("--host", default="0.0.0.0")
    main.add_argument("--port", type=int, default=8787)

    subparsers.add_parser("migrate")
    subparsers.add_parser("health")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "control-panel":
        os.environ["TOKEN_BI_CONTROL_HOST"] = args.host
        os.environ["TOKEN_BI_CONTROL_PORT"] = str(args.port)
        os.environ["TOKEN_BI_PORT"] = str(args.main_port)
        from scripts.control_panel import main as control_main

        control_main()
        return
    if args.command == "main-server":
        import uvicorn

        from app.main import app as fastapi_app

        uvicorn.run(fastapi_app, host=args.host, port=args.port, loop="asyncio")
        return
    if args.command == "migrate":
        from app.app_paths import resolve_app_data_dir, resolve_project_root
        from app.migration import migrate_project_data

        print(migrate_project_data(resolve_project_root(), resolve_app_data_dir()).message)
        return
    if args.command == "health":
        print("ok")
        return
    raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
