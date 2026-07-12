from __future__ import annotations

import argparse
import os


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="token-bi-control")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8790)
    parser.add_argument("--main-port", type=int, default=8787)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    os.environ["TOKEN_BI_CONTROL_HOST"] = args.host
    os.environ["TOKEN_BI_CONTROL_PORT"] = str(args.port)
    os.environ["TOKEN_BI_PORT"] = str(args.main_port)

    from scripts.control_panel import main as control_main

    control_main()


if __name__ == "__main__":
    main()
