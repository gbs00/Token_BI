from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Optional


def write_private_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f"{path.name}-", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def quarantine_json(path: Path) -> Optional[Path]:
    backup = path.with_name(f"{path.name}.corrupt-{uuid.uuid4().hex}")
    try:
        os.chmod(path, 0o600)
        os.replace(path, backup)
    except FileNotFoundError:
        return None
    return backup
