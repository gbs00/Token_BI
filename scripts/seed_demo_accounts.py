from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = PROJECT_ROOT / "config" / "accounts.json"
CONTEXTS_DIR = PROJECT_ROOT / "runtime" / "contexts"
LOCAL_CONNECTOR_DIR = PROJECT_ROOT / "runtime" / "cache" / "local_codex"


def main() -> None:
    CONTEXTS_DIR.mkdir(parents=True, exist_ok=True)
    LOCAL_CONNECTOR_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    accounts = [
        {
            "account_id": "acc_demo_main",
            "account_alias": "guo****@gmail.com",
            "masked_email": "guo****@gmail.com",
            "status": "active",
            "session_storage_path": str(CONTEXTS_DIR / "acc_demo_main"),
            "created_at": now,
            "last_validated_at": now,
        },
        {
            "account_id": "acc_demo_alt",
            "account_alias": "team****@gmail.com",
            "masked_email": "team****@gmail.com",
            "status": "active",
            "session_storage_path": str(CONTEXTS_DIR / "acc_demo_alt"),
            "created_at": now,
            "last_validated_at": now,
        },
        {
            "account_id": "acc_demo_lab",
            "account_alias": "lab****@outlook.com",
            "masked_email": "lab****@outlook.com",
            "status": "active",
            "session_storage_path": str(CONTEXTS_DIR / "acc_demo_lab"),
            "created_at": now,
            "last_validated_at": now,
        },
    ]

    for account in accounts:
        context_dir = Path(account["session_storage_path"])
        context_dir.mkdir(parents=True, exist_ok=True)
        marker = context_dir / ".demo_session"
        marker.write_text("demo", encoding="utf-8")
        snapshot_file = LOCAL_CONNECTOR_DIR / f"{account['account_id']}.json"
        snapshot_file.write_text(
            json.dumps(
                {
                    "session_remaining_pct": _session_pct(account["account_id"]),
                    "session_reset_at": _session_reset_at(),
                    "weekly_remaining_pct": _weekly_pct(account["account_id"]),
                    "weekly_reset_at": _weekly_reset_at(),
                    "updated_at": now,
                    "is_estimated": False,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(
        json.dumps({"accounts": accounts}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Seeded {len(accounts)} demo accounts into {CONFIG_FILE}")


def _session_pct(account_id: str) -> int:
    return {
        "acc_demo_main": 93,
        "acc_demo_alt": 81,
        "acc_demo_lab": 67,
    }.get(account_id, 88)


def _weekly_pct(account_id: str) -> int:
    return {
        "acc_demo_main": 84,
        "acc_demo_alt": 72,
        "acc_demo_lab": 58,
    }.get(account_id, 76)


def _session_reset_at() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=5)).replace(microsecond=0).isoformat()


def _weekly_reset_at() -> str:
    return (datetime.now(timezone.utc) + timedelta(days=6, hours=12)).replace(microsecond=0).isoformat()


if __name__ == "__main__":
    main()
