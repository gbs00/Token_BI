from __future__ import annotations

import os
from pathlib import Path
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
        "dashboard": _public_dashboard(cached),
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
        "next_step": "在 Mac 端打开 Token BI 登录窗口，完成同一账号登录后读取额度。",
    }


@router.post("/accounts/{account_id}/validate")
def validate_account(request: Request, account_id: str) -> dict:
    container = request.app.state.container
    account = container.account_service.get_account(account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found.")

    payload = container.usage_sync_coordinator.refresh(account_id=account_id)
    updated = container.account_service.get_account(account_id)
    session = container.web_session_service.get_session_snapshot(account_id)
    if payload.state == PageState.READY:
        container.web_session_service.minimize_session(account_id)
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

    session = container.web_session_service.get_session_snapshot(account_id)
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
    session = container.web_session_service.start_login_session(
        account_id=account_id,
        context_dir=context_dir,
        expected_identity=account.identity_key,
    )
    return {
        "account_id": account_id,
        "context_dir": str(context_dir),
        "session": session.model_dump(mode="json"),
        "next_step": "完成同一账号登录后窗口会收起，网页登录状态会保留。",
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
        if payload.state not in {PageState.REAUTH_REQUIRED, PageState.SOURCE_CHANGED}:
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
    session = container.web_session_service.start_login_session(
        account_id=account.account_id,
        context_dir=context_dir,
        expected_identity=account.identity_key,
    )
    return {
        "ok": session.state.value != "error",
        "action": "login",
        "next_button_label": "登录账号",
        "account": account.model_dump(mode="json"),
        "session": session.model_dump(mode="json"),
        "message": ("未能打开原生登录窗口，请重试。" if session.state.value == "error" else
                    "已打开 Token BI 登录窗口，完成登录后会自动同步额度。"),
    }


@router.post("/account-session/logout")
def logout_account_session(request: Request, account_id: Optional[str] = None) -> dict:
    container = request.app.state.container
    account = container.account_service.preferred_account(account_id)
    # 只解除本工具的接入；不清理 WebKit/Chrome Cookie 或外部授权文件。
    container.usage_sync_coordinator.disconnect()
    container.web_session_service.close_session()
    container.account_service.clear_accounts()
    if account is None:
        return {
            "action": "logout",
            "account_id": None,
            "next_button_label": "登录账号",
            "message": "已暂停 Token BI 账号接入，本机 Codex 登录态保持不变。",
        }

    return {
        "action": "logout",
        "account_id": account.account_id,
        "next_button_label": "登录账号",
        "message": (
            "已解除 Token BI 账号接入授权。"
            "Codex、CLI 和网页的登录状态保持不变。"
            "自动读取已暂停，点击登录账号后恢复接入。"
        ),
    }


@router.post("/accounts/{account_id}/minimize-worker")
def minimize_account_worker(request: Request, account_id: str) -> dict:
    container = request.app.state.container
    account = container.account_service.get_account(account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found.")
    minimized = container.web_session_service.minimize_session(account_id)
    return {"account_id": account_id, "minimized": minimized}


@router.get("/diagnostics")
def diagnostics(request: Request) -> dict:
    container = request.app.state.container
    web_available = container.web_session_service.available()
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
    codex_cli_available = any(
        connector.name == "codex_cli_rpc" and connector.cli_available()
        for connector in container.usage_connector_manager.connectors
    )
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
            "code": "webview_available",
            "title": "原生登录窗口",
            "severity": "ok" if web_available else "warning",
            "next_step": "网页登录使用系统 WKWebView，无需安装 Chrome。组件缺失时请重新安装 Token BI。",
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
            "next_step": "OAuth 数据源是常规刷新首选链路，不会打开登录网页。",
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
            "severity": "info" if "wkwebview" in connector_names else "warning",
            "next_step": "仅当前两条主链路不可用时，才尝试同账号 WKWebView 会话。",
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
