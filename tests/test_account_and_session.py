from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
import stat
from pathlib import Path

import pytest

from app.container import ServiceContainer
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


@pytest.mark.parametrize("broken", ["{", "[]", '{"accounts": [null]}',
                                    '{"accounts": [], "access_revision": "bad"}'])
def test_corrupt_account_metadata_recovers_without_automatic_access(test_settings, broken) -> None:
    test_settings.accounts_file.write_text(broken, encoding="utf-8")
    external_auth = test_settings.codex_auth_paths[0]
    external_auth.write_text("external-credential-fixture", encoding="utf-8")
    recovered = ServiceContainer(test_settings)
    try:
        assert recovered.account_service.access_state()[0] is False
        assert recovered.account_service.list_accounts() == []
        assert "配置" in recovered.usage_sync_coordinator.get_dashboard().message
        backups = list(test_settings.config_dir.glob("accounts.json.corrupt-*"))
        assert len(backups) == 1
        assert backups[0].read_text() == broken
        assert stat.S_IMODE(backups[0].stat().st_mode) == 0o600
        assert external_auth.read_text() == "external-credential-fixture"
        assert json.loads(test_settings.accounts_file.read_text())["access_enabled"] is False

        recovered.usage_sync_coordinator.resume()
        assert recovered.account_service.access_state()[0] is True
        assert "recovery_required" not in json.loads(test_settings.accounts_file.read_text())
    finally:
        recovered.shutdown()


def test_account_file_corruption_invalidates_inflight_revision(container) -> None:
    service = container.account_service
    before = service.access_state()[1]
    container.settings.accounts_file.write_text("{", encoding="utf-8")

    assert service.access_state()[0] is False
    service.set_access_enabled(True)

    assert service.access_state()[1] > before + 1


def test_unchanged_account_polls_do_not_reread_file(container, monkeypatch):
    service = container.account_service
    account = service.create_account(CreateAccountRequest(masked_email="test****@example.com"))
    reads = []
    read_text = Path.read_text
    def tracked(path, *args, **kwargs):
        if path == container.settings.accounts_file:
            reads.append(path)
        return read_text(path, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", tracked)
    for _ in range(20):
        assert service.access_state() == (True, 0)
        assert service.preferred_account().account_id == account.account_id
        assert service.access_state() == (True, 0)
    assert len(reads) == 1


def test_account_cache_notices_same_size_same_mtime_replacement(container):
    service = container.account_service
    path = container.settings.accounts_file
    service.set_access_enabled(True)
    before = service.access_state()
    raw, original_stat = path.read_text(), path.stat()
    replacement = path.with_suffix(".replacement")
    replacement.write_text(raw.replace('"access_revision": 1', '"access_revision": 2'))
    os.utime(replacement, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    replacement.replace(path)
    assert path.stat().st_size == original_stat.st_size
    assert path.stat().st_mtime_ns == original_stat.st_mtime_ns
    assert service.access_state() == (True, before[1] + 1)


def test_account_cache_does_not_share_mutable_records(container):
    service = container.account_service
    account = service.create_account(CreateAccountRequest(masked_email="test****@example.com"))
    service.list_accounts()[0].account_alias = "changed"
    service._read_payload()["accounts"].clear()
    assert service.get_account(account.account_id).account_alias == account.account_alias


def test_failed_account_write_keeps_cached_access_state(container, monkeypatch):
    from app.services import local_json_store
    service = container.account_service
    before = service.access_state()
    def fail(*_):
        raise OSError("fixture write failure")
    monkeypatch.setattr(local_json_store.os, "replace", fail)
    with pytest.raises(OSError):
        service.set_access_enabled(False)
    assert service.access_state() == before


def test_account_cache_missing_file_fails_closed(container):
    service = container.account_service
    before = service.access_state()[1]
    container.settings.accounts_file.unlink()
    assert service.access_state()[0] is False
    assert service.access_state()[1] > before


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
