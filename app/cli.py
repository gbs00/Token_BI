from __future__ import annotations

import argparse
import socket


def create_dual_stack_listener(port: int) -> socket.socket:
    listener = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    try:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        listener.bind(("::", port))
        listener.listen(2048)
        listener.set_inheritable(True)
    except OSError:
        listener.close()
        raise
    return listener


def run_main_server(fastapi_app, host: str, port: int) -> None:
    import uvicorn

    if host == "0.0.0.0" and socket.has_ipv6:
        try:
            listener = create_dual_stack_listener(port)
        except OSError:
            # IPv6 不可用时交还给 Uvicorn 执行原有 IPv4 启动和错误报告。
            pass
        else:
            config = uvicorn.Config(fastapi_app, host=host, port=port, loop="asyncio")
            try:
                uvicorn.Server(config).run(sockets=[listener])
            finally:
                listener.close()
            return

    uvicorn.run(fastapi_app, host=host, port=port, loop="asyncio")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="token-bi-backend")
    subparsers = parser.add_subparsers(dest="command", required=True)

    main = subparsers.add_parser("main-server")
    main.add_argument("--host", default="0.0.0.0")
    main.add_argument("--port", type=int, default=8787)

    subparsers.add_parser("migrate")
    subparsers.add_parser("health")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "main-server":
        from app.main import app as fastapi_app

        run_main_server(fastapi_app, host=args.host, port=args.port)
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
