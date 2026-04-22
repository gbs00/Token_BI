from __future__ import annotations

import json
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
        payload = {"accounts": [account.model_dump(mode="json") for account in accounts]}
        self._settings.accounts_file.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

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

    def create_account(self, body: CreateAccountRequest) -> AccountRecord:
        with self._lock:
            accounts = self._read_accounts()
            account_id = f"acc_{uuid.uuid4().hex[:8]}"
            session_path = self._settings.runtime_contexts_dir / account_id
            account_alias = self._resolve_account_alias(body)
            account = AccountRecord(
                account_id=account_id,
                account_alias=account_alias,
                masked_email=body.masked_email,
                status=AccountStatus.PENDING,
                session_storage_path=str(session_path),
                created_at=datetime.now(timezone.utc),
            )
            accounts.append(account)
            self._write_accounts(accounts)
            return account

    def _resolve_account_alias(self, body: CreateAccountRequest) -> str:
        alias = (body.account_alias or "").strip()
        if alias:
            return alias
        return body.masked_email

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
