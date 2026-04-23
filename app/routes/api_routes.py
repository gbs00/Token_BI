from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Request, status

from app.models.account import CreateAccountRequest


router = APIRouter(prefix="/api/v1")


@router.get("/accounts")
def list_accounts(request: Request) -> dict[str, list[dict[str, str]]]:
    container = request.app.state.container
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


@router.get("/dashboard")
def get_dashboard(request: Request, account_id: Optional[str] = None) -> dict:
    container = request.app.state.container
    payload = container.usage_service.get_dashboard(account_id=account_id)
    return payload.model_dump(mode="json")


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

    payload = container.usage_service.refresh_dashboard(account_id=account_id)
    updated = container.account_service.get_account(account_id)
    session = container.browser_worker_service.get_session_snapshot(account_id)
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


@router.post("/dashboard/refresh")
def refresh_dashboard(request: Request, account_id: Optional[str] = None) -> dict:
    container = request.app.state.container
    payload = container.usage_service.refresh_dashboard(account_id=account_id)
    return payload.model_dump(mode="json")
