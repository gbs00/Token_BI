from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.models.account import AccountRecord, AccountStatus
from app.models.account import CreateAccountRequest
from app.services.session_service import SessionService


def test_create_account_persists_record(container) -> None:
    account = container.account_service.create_account(
        CreateAccountRequest(masked_email="guo****@gmail.com")
    )

    stored = container.account_service.get_account(account.account_id)
    assert stored is not None
    assert stored.account_alias == "guo****@gmail.com"
    assert stored.masked_email == "guo****@gmail.com"
    assert stored.status.value == "pending"


def test_session_context_material_detection(test_settings) -> None:
    service = SessionService(test_settings)
    account_id = "acc_demo"
    context_dir = service.ensure_context_dir(account_id)

    assert service.context_has_material(account_id) is False

    marker = context_dir / "Default" / "Cookies"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("cookie", encoding="utf-8")

    assert service.context_has_material(account_id) is True


def test_visible_accounts_hide_demo_and_dedupe_by_email(container) -> None:
    service = container.account_service
    now = datetime.now(timezone.utc)
    service._write_accounts(
        [
            AccountRecord(
                account_id="acc_demo_main",
                account_alias="demo",
                masked_email="demo****@gmail.com",
                status=AccountStatus.ACTIVE,
                session_storage_path="/tmp/acc_demo_main",
                created_at=now,
            ),
            AccountRecord(
                account_id="acc_old_pending",
                account_alias="user****@example.com",
                masked_email="user****@example.com",
                status=AccountStatus.PENDING,
                session_storage_path="/tmp/acc_old_pending",
                created_at=now,
            ),
            AccountRecord(
                account_id="acc_real_active",
                account_alias="user****@example.com",
                masked_email="user****@example.com",
                status=AccountStatus.ACTIVE,
                session_storage_path="/tmp/acc_real_active",
                created_at=now,
                last_validated_at=now,
            ),
            AccountRecord(
                account_id="acc_second_real",
                account_alias="team****@gmail.com",
                masked_email="team****@gmail.com",
                status=AccountStatus.PENDING,
                session_storage_path="/tmp/acc_second_real",
                created_at=now,
            ),
        ]
    )

    visible_accounts = service.list_visible_accounts()

    assert [account.account_id for account in visible_accounts] == ["acc_real_active"]


def test_preferred_account_maps_demo_link_to_real_account(container) -> None:
    service = container.account_service
    now = datetime.now(timezone.utc)
    service._write_accounts(
        [
            AccountRecord(
                account_id="acc_demo_main",
                account_alias="demo",
                masked_email="user****@example.com",
                status=AccountStatus.ACTIVE,
                session_storage_path="/tmp/acc_demo_main",
                created_at=now,
            ),
            AccountRecord(
                account_id="acc_real_active",
                account_alias="user****@example.com",
                masked_email="user****@example.com",
                status=AccountStatus.ACTIVE,
                session_storage_path="/tmp/acc_real_active",
                created_at=now,
                last_validated_at=now,
            ),
        ]
    )

    preferred = service.preferred_account("acc_demo_main")

    assert preferred is not None
    assert preferred.account_id == "acc_real_active"


def test_visible_accounts_falls_back_to_pending_when_no_active_exists(container) -> None:
    service = container.account_service
    now = datetime.now(timezone.utc)
    service._write_accounts(
        [
            AccountRecord(
                account_id="acc_pending_a",
                account_alias="user****@example.com",
                masked_email="user****@example.com",
                status=AccountStatus.PENDING,
                session_storage_path="/tmp/acc_pending_a",
                created_at=now,
            ),
            AccountRecord(
                account_id="acc_pending_b",
                account_alias="team****@gmail.com",
                masked_email="team****@gmail.com",
                status=AccountStatus.PENDING,
                session_storage_path="/tmp/acc_pending_b",
                created_at=now.replace(second=(now.second + 1) % 60),
            ),
        ]
    )

    visible_accounts = service.list_visible_accounts()

    assert [account.account_id for account in visible_accounts] == ["acc_pending_b", "acc_pending_a"]
