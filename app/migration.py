from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MigrationResult:
    migrated: bool
    message: str


def migrate_project_data(old_root: Path, app_data_dir: Path) -> MigrationResult:
    source_accounts = old_root / "config" / "accounts.json"
    target_accounts = app_data_dir / "config" / "accounts.json"
    if not source_accounts.exists():
        return MigrationResult(False, "No project accounts file found.")
    if target_accounts.exists():
        return MigrationResult(False, "App data already exists; migration skipped.")

    target_accounts.parent.mkdir(parents=True, exist_ok=True)
    (app_data_dir / "runtime").mkdir(parents=True, exist_ok=True)

    source_runtime = old_root / "runtime"
    target_runtime = app_data_dir / "runtime"
    if source_runtime.exists():
        shutil.copytree(source_runtime, target_runtime, dirs_exist_ok=True)

    payload = json.loads(source_accounts.read_text(encoding="utf-8"))
    for account in payload.get("accounts", []):
        account_id = account.get("account_id")
        if account_id:
            account["session_storage_path"] = str(target_runtime / "contexts" / account_id)
    target_accounts.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return MigrationResult(True, "Project data migrated to Application Support.")
