from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.account import AccountRecord, AccountStatus
from app.models.account import CreateAccountRequest


def test_create_account_persists_record(container) -> None:
    account = container.account_service.create_account(
        CreateAccountRequest(masked_email="guo****@gmail.com")
    )

    stored = container.account_service.get_account(account.account_id)
    assert stored is not None
    assert stored.account_alias == "guo****@gmail.com"
    assert stored.masked_email == "guo****@gmail.com"
    assert stored.status.value == "pending"


def test_delete_account_only_removes_binding_and_preserves_legacy_profile(container) -> None:
    account = container.account_service.create_account(
        CreateAccountRequest(masked_email="user****@example.com")
    )
    context_dir = container.session_service.ensure_context_dir(account.account_id)
    profile_file = context_dir / "Default" / "Cookies"
    profile_file.parent.mkdir(parents=True, exist_ok=True)
    profile_file.write_text("cookie", encoding="utf-8")

    deleted = container.account_service.delete_account(account.account_id)

    assert deleted is not None
    assert container.account_service.get_account(account.account_id) is None
    assert profile_file.read_text() == "cookie"


def test_visible_accounts_hide_demo_and_prefer_active(container) -> None:
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


def test_same_masked_email_does_not_merge_different_identities(container):
    service = container.account_service
    first = service.create_account(CreateAccountRequest(masked_email="same****@example.com"))
    second = first.model_copy(update={"account_id": "acc_second", "identity_key": "b" * 64})
    first = first.model_copy(update={"identity_key": "a" * 64})
    service._write_accounts([first, second])
    assert len(service.list_visible_accounts()) == 2
    second = second.model_copy(update={"identity_key": first.identity_key})
    service._write_accounts([first, second])
    assert len(service.list_visible_accounts()) == 1


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
                created_at=now + timedelta(seconds=1),
            ),
        ]
    )

    visible_accounts = service.list_visible_accounts()

    assert [account.account_id for account in visible_accounts] == ["acc_pending_b", "acc_pending_a"]
