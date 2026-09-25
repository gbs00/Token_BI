"""显式本机验收：用户登录专用网页会话，验证同账号读取和进程重启；不导出凭据。"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.services.account_service import AccountService
from app.services.usage_connectors import normalize_usage_payload
from app.services.web_session_service import WebSessionService


def verify(login: bool, output: Path, wait: int) -> None:
    settings = get_settings()
    account = AccountService(settings).preferred_account()
    expected = account.identity_key if account else None
    service = WebSessionService(settings)
    ready = threading.Event()
    service.on_event = lambda event: ready.set() if event == "session_ready" else None
    reports = []
    try:
        if login:
            session = service.start_login_session("verification", settings.runtime_dir, expected_identity=expected)
            assert session.state.value != "error", session.last_error
            print("Waiting for manual login in Token BI account window.", flush=True)
            if not ready.wait(wait):
                raise TimeoutError("未完成实机登录验收；不会清理已建立的网页登录状态。")
        for step in ("hidden", "warm", "restart"):
            if step == "restart":
                service.close_session()
            result = service._get_bridge().request("collect", expected)
            assert result.get("category") == "success", result.get("category")
            key = result["identity"]["key"]
            assert expected is None or key == expected, "Account mismatch"
            expected = key
            normalized = normalize_usage_payload(result["usage"], "web_session", "wkwebview_json")
            report = {"step": step, "category": "success", "same_account": True,
                      "elapsed_ms": result["elapsed_ms"], "checked_at": result["checked_at"],
                      "windows": normalized["windows"], "reset_credits": normalized["reset_credits"]}
            reports.append(report)
            print(json.dumps(report, ensure_ascii=False, default=lambda value: value.isoformat()), flush=True)
        output.parent.mkdir(parents=True, exist_ok=True)
        with os.fdopen(os.open(output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as handle:
            json.dump(reports, handle, ensure_ascii=False, indent=2, default=lambda value: value.isoformat())
    finally:
        service.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--login", action="store_true")
    parser.add_argument("--wait", type=int, default=600)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    verify(args.login, args.output, args.wait)
