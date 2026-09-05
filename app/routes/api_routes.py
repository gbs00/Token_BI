from __future__ import annotations

import os
import subprocess
from pathlib import Path
import shutil
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.models.account import AccountStatus, CreateAccountRequest
from app.models.usage_snapshot import PageState
from app.services.usage_connectors import mask_identity
from app.http_access import allows_local_management


def require_api_access(request: Request) -> None:
    public_routes = {
        ("GET", "/api/v1/dashboard"),
        ("POST", "/api/v1/dashboard/refresh"),
        ("GET", "/api/v1/health"),
    }
    origin = request.headers.get("origin")
    if (request.method, request.url.path.rstrip("/")) in public_routes:
        if request.method == "POST" and origin and origin != str(request.base_url).rstrip("/"):
            raise HTTPException(status_code=403, detail="不允许跨站发起同步。")
        return
    if not allows_local_management(
        request.client.host if request.client else "", request.url.hostname or "", origin,
    ):
        raise HTTPException(status_code=403, detail="账号和运维操作仅允许在 Mac 本机控制台执行。")


router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_access)])
MAIN_SERVICE_MARKER = "token-bi-main-service"


def _public_dashboard(payload) -> dict:
    result = payload.model_dump(mode="json")
    if payload.account is not None:
        result["account"] = {
            "account_id": payload.account.account_id,
            "masked_email": mask_identity(payload.account.masked_email),
            "status": payload.account.status.value,
        }
    return result


def _chrome_available() -> bool:
    candidates = [
        Path("/Applications/Google Chrome.app"),
        Path.home() / "Applications" / "Google Chrome.app",
    ]
    if any(path.exists() for path in candidates):
        return True
    try:
        result = subprocess.run(
            ["mdfind", "kMDItemCFBundleIdentifier == 'com.google.Chrome'"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return False
    return bool(result.stdout.strip())


@router.get("/accounts")
def list_accounts(request: Request) -> dict[str, list[dict[str, str]]]:
    container = request.app.state.container
    if not container.account_service.access_state()[0]:
        return {"items": []}
    items = [
        {
            "account_id": account.account_id,
            "account_alias": account.account_alias,
            "masked_email": account.masked_email,
            "status": account.status.value,
        }
        for account in container.account_service.list_visible_accounts()
    ]
    return {"items": items}


@router.get("/health")
def health(request: Request) -> dict:
    return {
        "ok": True,
        "service": MAIN_SERVICE_MARKER,
        "pid": os.getpid(),
        "port": request.app.state.settings.port,
        "version": request.app.version,
    }


@router.get("/runtime-status")
def runtime_status(request: Request) -> dict:
    container = request.app.state.container
    cached = container.usage_sync_coordinator.get_dashboard()
    account = cached.account
    usage = {
            "state": cached.state.value,
            "message": cached.message,
            "has_data": bool(cached.metrics),
            "updated_at": cached.summary.last_success_at or cached.summary.updated_at,
            "source_updated_at": cached.summary.updated_at,
            "last_attempt_at": cached.summary.last_attempt_at,
            "next_sync_at": cached.summary.next_sync_at,
            "source_type": cached.summary.source_type,
            "source_detail": cached.summary.source_detail,
            "connector_name": cached.summary.connector_name,
        }
    return {
        "ok": True,
        "service": MAIN_SERVICE_MARKER,
        "pid": os.getpid(),
        "account": account.model_dump(mode="json") if account is not None else None,
        "usage": usage,
        "access_enabled": container.account_service.access_state()[0],
    }


@router.get("/dashboard")
def get_dashboard(request: Request, account_id: Optional[str] = None) -> dict:
    container = request.app.state.container
    payload = container.usage_sync_coordinator.get_dashboard(account_id=account_id)
    return _public_dashboard(payload)


@router.post("/accounts", status_code=status.HTTP_201_CREATED)
def create_account(request: Request, body: CreateAccountRequest) -> dict:
    container = request.app.state.container
    account = container.account_service.create_account(body)
    container.session_service.ensure_context_dir(account.account_id)
    return {
        "account": account.model_dump(mode="json"),
        "next_step": "Start the live browser worker on Mac, complete Codex login, then validate analytics access.",
    }


@router.post("/accounts/{account_id}/validate")
def validate_account(request: Request, account_id: str) -> dict:
    container = request.app.state.container
    account = container.account_service.get_account(account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found.")

    payload = container.usage_sync_coordinator.refresh(account_id=account_id)
    updated = container.account_service.get_account(account_id)
    session = container.browser_worker_service.get_session_snapshot(account_id)
    if payload.state == PageState.READY:
        container.browser_worker_service.minimize_session(account_id)
    if updated is None:
        raise HTTPException(status_code=500, detail="Unable to update account state.")
    return {
        "account": updated.model_dump(mode="json"),
        "validated": payload.state.value == "ready",
        "dashboard_state": payload.state.value,
        "session": session.model_dump(mode="json") if session else None,
    }


@router.get("/accounts/{account_id}/session")
def get_account_session(request: Request, account_id: str) -> dict:
    container = request.app.state.container
    account = container.account_service.get_account(account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found.")

    session = container.browser_worker_service.restore_session_snapshot(account)
    return {
        "account_id": account_id,
        "session": session.model_dump(mode="json") if session else None,
    }


@router.post("/accounts/{account_id}/reauth")
def reauth_account(request: Request, account_id: str) -> dict:
    container = request.app.state.container
    account = container.account_service.get_account(account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found.")

    container.usage_sync_coordinator.resume()
    context_dir = container.session_service.ensure_context_dir(account_id)
    container.account_service.update_account_status(account_id=account_id, status="pending")
    session = container.browser_worker_service.start_login_session(
        account_id=account_id,
        context_dir=context_dir,
    )
    return {
        "account_id": account_id,
        "context_dir": str(context_dir),
        "session": session.model_dump(mode="json"),
        "next_step": "Complete Codex login in the opened browser window and keep that worker running while the service is active.",
    }


@router.post("/account-session/login")
def login_account_session(request: Request) -> dict:
    container = request.app.state.container
    container.usage_sync_coordinator.resume()
    local_available = any(
        (connector.name == "codex_oauth" and connector.auth_available())
        or (connector.name == "codex_cli_rpc" and connector.cli_available())
        for connector in container.usage_connector_manager.connectors
    )
    if local_available:
        payload = container.usage_sync_coordinator.refresh()
        if payload.state == PageState.READY:
            return {
                "ok": True, "action": "resume", "next_button_label": "退出账号",
                "account": payload.account.model_dump(mode="json"), "session": None,
                "message": "已恢复账号接入，并同步本机 Codex 额度。",
            }
        if payload.state != PageState.REAUTH_REQUIRED:
            return {"ok": False, "action": "resume", "session": None, "message": payload.message}
    account = container.account_service.preferred_account()
    if account is None:
        account = container.account_service.create_account(CreateAccountRequest())
    else:
        refreshed_account = container.account_service.update_account_status(
            account_id=account.account_id,
            status=AccountStatus.PENDING.value,
        )
        if refreshed_account is not None:
            account = refreshed_account

    context_dir = container.session_service.ensure_context_dir(account.account_id)
    session = container.browser_worker_service.start_login_session(
        account_id=account.account_id,
        context_dir=context_dir,
    )
    return {
        "ok": session.state.value != "error",
        "action": "login",
        "next_button_label": "登录账号",
        "account": account.model_dump(mode="json"),
        "session": session.model_dump(mode="json"),
        "message": ("未能打开登录窗口，请检查 Chrome 后重试。" if session.state.value == "error" else
                    "已打开 Token BI 专用 Chrome 登录窗口。完成 Codex 登录后回到控制台刷新状态。"),
    }


@router.post("/account-session/logout")
def logout_account_session(request: Request, account_id: Optional[str] = None) -> dict:
    container = request.app.state.container
    account = container.account_service.preferred_account(account_id)
    # 先撤销接入并使在途结果失效，再清理本应用的账号与浏览器目录。
    container.usage_sync_coordinator.disconnect()
    if account is None:
        return {
            "action": "logout",
            "account_id": None,
            "next_button_label": "登录账号",
            "message": "已暂停 Token BI 账号接入，本机 Codex 登录态保持不变。",
        }

    container.browser_worker_service.close_session(account.account_id)
    deleted = container.account_service.delete_account(account.account_id)
    container.session_service.delete_context(account.account_id)
    if deleted is None:
        raise HTTPException(status_code=404, detail="Account not found.")

    return {
        "action": "logout",
        "account_id": account.account_id,
        "next_button_label": "登录账号",
        "message": (
            "已清除 Token BI 账号记录和专用 Web 登录态。"
            "本机 Codex OAuth / CLI 登录态不会被退出。"
            "自动读取已暂停，点击登录账号后恢复接入。"
        ),
    }


@router.post("/accounts/{account_id}/minimize-worker")
def minimize_account_worker(request: Request, account_id: str) -> dict:
    container = request.app.state.container
    account = container.account_service.get_account(account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found.")
    minimized = container.browser_worker_service.minimize_session(account_id)
    return {"account_id": account_id, "minimized": minimized}


@router.get("/diagnostics")
def diagnostics(request: Request) -> dict:
    container = request.app.state.container
    chrome_available = _chrome_available()
    connector_names = {connector.name for connector in container.usage_connector_manager.connectors}
    oauth_connector = next(
        (connector for connector in container.usage_connector_manager.connectors if connector.name == "codex_oauth"),
        None,
    )
    codex_auth_available = bool(
        oauth_connector is not None
        and hasattr(oauth_connector, "auth_available")
        and oauth_connector.auth_available()
    )
    codex_cli_available = shutil.which(container.settings.codex_cli_bin) is not None
    last_connector_error = "No connector errors recorded."
    if container.usage_connector_manager.last_connector_errors:
        last_connector_error = "；".join(
            f"{item['connector_name']} {item['error_type']}"
            for item in container.usage_connector_manager.last_connector_errors
        )
    items = [
        {
            "code": "service_ready",
            "title": "服务状态",
            "severity": "ok",
            "next_step": "如果副屏打不开看板，请确认控制台里显示的实际端口，并重新扫码。",
        },
        {
            "code": "chrome_available",
            "title": "Chrome 登录窗口",
            "severity": "ok" if chrome_available else "warning",
            "next_step": "Token BI 需要 Google Chrome 作为专用登录窗口；未安装时请先安装 Chrome。",
        },
        {
            "code": "login_required",
            "title": "账号登录态",
            "severity": "info",
            "next_step": "看到登录态失效或真人验证未完成时，点击控制台的“登录账号”重新拉起专用窗口。",
        },
        {
            "code": "network_reachable",
            "title": "副屏连接",
            "severity": "info",
            "next_step": "副屏设备需和 Mac 位于同一局域网；如果 .local 不可达，请改用局域网 IP 入口。",
        },
        {
            "code": "codex_auth_available",
            "title": "Codex 本机登录态",
            "severity": "ok" if codex_auth_available else "warning",
            "next_step": "未检测到可用本机登录态时，请在 Codex App 或 Codex CLI 完成一次登录授权。",
        },
        {
            "code": "codex_cli_available",
            "title": "Codex CLI 能力",
            "severity": "ok" if codex_cli_available else "warning",
            "next_step": "未检测到 Codex CLI 时，Token BI 会跳过 CLI RPC 并尝试下一条数据源。",
        },
        {
            "code": "oauth_connector_ready",
            "title": "OAuth 数据源",
            "severity": "ok"
            if "codex_oauth" in connector_names and codex_auth_available
            else "warning",
            "next_step": "OAuth 数据源是常规刷新首选链路，不会打开 Chrome 页面。",
        },
        {
            "code": "cli_rpc_connector_ready",
            "title": "CLI RPC 数据源",
            "severity": "ok"
            if "codex_cli_rpc" in connector_names and codex_cli_available
            else "warning",
            "next_step": "OAuth 不可用时将尝试读取 Codex app-server rate limit 数据。",
        },
        {
            "code": "web_session_available",
            "title": "Web Session 兜底",
            "severity": "info" if "browser_worker" in connector_names else "warning",
            "next_step": "仅当前两条主链路不可用时，才进入专用 Chrome 登录窗口兜底。",
        },
        {
            "code": "last_connector_error",
            "title": "最近数据源降级",
            "severity": "info",
            "next_step": last_connector_error,
        },
    ]
    return {"items": items}


@router.post("/dashboard/refresh")
def refresh_dashboard(request: Request, account_id: Optional[str] = None) -> dict:
    container = request.app.state.container
    payload = container.usage_sync_coordinator.refresh(account_id=account_id)
    return _public_dashboard(payload)
