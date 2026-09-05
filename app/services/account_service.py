from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.config import Settings
from app.models.account import AccountRecord, AccountStatus, CreateAccountRequest


class AccountService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._lock = threading.RLock()
        self._ensure_accounts_file()

    def _ensure_accounts_file(self) -> None:
        if not self._settings.accounts_file.exists():
            self._settings.accounts_file.write_text('{"accounts": []}\n', encoding="utf-8")

    def _read_accounts(self) -> list[AccountRecord]:
        raw = json.loads(self._settings.accounts_file.read_text(encoding="utf-8"))
        return [AccountRecord.model_validate(item) for item in raw.get("accounts", [])]

    def _write_accounts(self, accounts: list[AccountRecord]) -> None:
        payload = json.loads(self._settings.accounts_file.read_text(encoding="utf-8"))
        payload["accounts"] = [account.model_dump(mode="json") for account in accounts]
        self._write_payload(payload)

    def _write_payload(self, payload: dict) -> None:
        path = self._settings.accounts_file
        temporary = path.with_suffix(".json.tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def access_state(self) -> tuple[bool, int]:
        with self._lock:
            raw = json.loads(self._settings.accounts_file.read_text(encoding="utf-8"))
            return raw.get("access_enabled", True) is True, int(raw.get("access_revision", 0))

    def set_access_enabled(self, enabled: bool) -> None:
        with self._lock:
            raw = json.loads(self._settings.accounts_file.read_text(encoding="utf-8"))
            raw["access_enabled"] = enabled
            raw["access_revision"] = int(raw.get("access_revision", 0)) + 1
            self._write_payload(raw)

    def commit_synced_account(self, proposed: AccountRecord, revision: int) -> Optional[AccountRecord]:
        # 校验接入代次，避免退出后迟到的采集结果重新创建账号。
        with self._lock:
            if self.access_state() != (True, revision):
                return None
            accounts = self._read_accounts()
            index = next((i for i, item in enumerate(accounts) if item.account_id == proposed.account_id), None)
            if index is None and proposed.account_id != "acc_local_codex":
                return None
            if proposed.account_id == "acc_local_codex":
                account_id = f"acc_{uuid.uuid4().hex[:8]}"
                proposed = proposed.model_copy(update={
                    "account_id": account_id,
                    "session_storage_path": str(self._settings.runtime_contexts_dir / account_id),
                })
            committed = proposed.model_copy(update={
                "status": AccountStatus.ACTIVE,
                "last_validated_at": datetime.now(timezone.utc),
            })
            if index is None:
                accounts.append(committed)
            else:
                accounts[index] = committed
            self._write_accounts(accounts)
            return committed

    def list_accounts(self) -> list[AccountRecord]:
        with self._lock:
            return self._read_accounts()

    def list_visible_accounts(self, preferred_account_id: Optional[str] = None) -> list[AccountRecord]:
        with self._lock:
            accounts = self._read_accounts()
        return self._select_visible_accounts(accounts, preferred_account_id)

    def first_account(self) -> Optional[AccountRecord]:
        return self.preferred_account()

    def preferred_account(self, preferred_account_id: Optional[str] = None) -> Optional[AccountRecord]:
        with self._lock:
            accounts = self._read_accounts()

        visible_accounts = self._select_visible_accounts(accounts, preferred_account_id)
        if not visible_accounts:
            return None

        if preferred_account_id:
            for account in visible_accounts:
                if account.account_id == preferred_account_id:
                    return account

            requested = next((item for item in accounts if item.account_id == preferred_account_id), None)
            if requested is not None:
                for account in visible_accounts:
                    if account.masked_email == requested.masked_email:
                        return account

        return visible_accounts[0]

    def get_account(self, account_id: str) -> Optional[AccountRecord]:
        with self._lock:
            for account in self._read_accounts():
                if account.account_id == account_id:
                    return account
        return None

    def delete_account(self, account_id: str) -> Optional[AccountRecord]:
        with self._lock:
            accounts = self._read_accounts()
            deleted_account: Optional[AccountRecord] = None
            kept_accounts: list[AccountRecord] = []
            for account in accounts:
                if account.account_id == account_id:
                    deleted_account = account
                    continue
                kept_accounts.append(account)

            if deleted_account is None:
                return None

            self._write_accounts(kept_accounts)
            return deleted_account

    def create_account(self, body: CreateAccountRequest) -> AccountRecord:
        with self._lock:
            accounts = self._read_accounts()
            account_id = f"acc_{uuid.uuid4().hex[:8]}"
            session_path = self._settings.runtime_contexts_dir / account_id
            masked_email = self._resolve_masked_email(body, account_id)
            account_alias = self._resolve_account_alias(body, masked_email)
            account = AccountRecord(
                account_id=account_id,
                account_alias=account_alias,
                masked_email=masked_email,
                status=AccountStatus.PENDING,
                session_storage_path=str(session_path),
                created_at=datetime.now(timezone.utc),
            )
            accounts.append(account)
            self._write_accounts(accounts)
            return account

    def _resolve_masked_email(self, body: CreateAccountRequest, account_id: str) -> str:
        masked_email = (body.masked_email or "").strip()
        if masked_email:
            return masked_email
        return f"Signing in {account_id[-4:]}"

    def _resolve_account_alias(self, body: CreateAccountRequest, masked_email: str) -> str:
        alias = (body.account_alias or "").strip()
        if alias:
            return alias
        return masked_email

    def _select_visible_accounts(
        self,
        accounts: list[AccountRecord],
        preferred_account_id: Optional[str] = None,
    ) -> list[AccountRecord]:
        visible_candidates = [account for account in accounts if not self._is_demo_account(account)]
        deduped_by_email: dict[str, AccountRecord] = {}
        for account in visible_candidates:
            current = deduped_by_email.get(account.masked_email)
            if current is None or self._account_rank(account, preferred_account_id) > self._account_rank(
                current, preferred_account_id
            ):
                deduped_by_email[account.masked_email] = account

        visible_accounts = list(deduped_by_email.values())
        active_accounts = [account for account in visible_accounts if account.status == AccountStatus.ACTIVE]
        if active_accounts:
            visible_accounts = active_accounts

        return sorted(
            visible_accounts,
            key=lambda account: self._account_rank(account, preferred_account_id),
            reverse=True,
        )

    def _is_demo_account(self, account: AccountRecord) -> bool:
        return account.account_id.startswith("acc_demo_")

    def _account_rank(
        self,
        account: AccountRecord,
        preferred_account_id: Optional[str] = None,
    ) -> tuple[int, int, float, float]:
        selected_score = 1 if preferred_account_id and account.account_id == preferred_account_id else 0
        status_score = {
            AccountStatus.ACTIVE: 3,
            AccountStatus.PENDING: 2,
            AccountStatus.EXPIRED: 1,
            AccountStatus.INVALID: 0,
        }[account.status]
        validated_score = account.last_validated_at.timestamp() if account.last_validated_at else 0.0
        created_score = account.created_at.timestamp()
        return (selected_score, status_score, validated_score, created_score)

    def update_account_status(
        self,
        account_id: str,
        status: str,
        update_validation_time: bool = False,
    ) -> Optional[AccountRecord]:
        with self._lock:
            accounts = self._read_accounts()
            updated_account: Optional[AccountRecord] = None
            for index, account in enumerate(accounts):
                if account.account_id != account_id:
                    continue
                updated_account = account.model_copy(
                    update={
                        "status": AccountStatus(status),
                        "last_validated_at": datetime.now(timezone.utc)
                        if update_validation_time
                        else account.last_validated_at,
                    }
                )
                accounts[index] = updated_account
                break

            if updated_account is None:
                return None

            self._write_accounts(accounts)
            return updated_account

    def update_account_identity(self, account_id: str, masked_email: str) -> Optional[AccountRecord]:
        normalized_email = masked_email.strip()
        if not normalized_email:
            return None

        with self._lock:
            accounts = self._read_accounts()
            updated_account: Optional[AccountRecord] = None
            for index, account in enumerate(accounts):
                if account.account_id != account_id:
                    continue
                updated_account = account.model_copy(
                    update={
                        "account_alias": normalized_email,
                        "masked_email": normalized_email,
                        "identity_key": None,
                    }
                )
                accounts[index] = updated_account
                break

            if updated_account is None:
                return None

            self._write_accounts(accounts)
            return updated_account
