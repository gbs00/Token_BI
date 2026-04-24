from __future__ import annotations

import os
import sys
from pathlib import Path


APP_NAME = "Token BI"


def resolve_project_root() -> Path:
    if getattr(sys, "frozen", False):
        bundle_root = getattr(sys, "_MEIPASS", None)
        if bundle_root:
            return Path(bundle_root).resolve()
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def resolve_app_data_dir() -> Path:
    override = os.getenv("TOKEN_BI_APP_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    home = Path(os.getenv("HOME", str(Path.home()))).expanduser()
    return home / "Library" / "Application Support" / APP_NAME
