from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import get_settings


templates = Jinja2Templates(directory=str(get_settings().templates_dir))
router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def root(request: Request) -> RedirectResponse:
    return RedirectResponse(url="/dashboard", status_code=307)


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(request: Request, account_id: Optional[str] = None) -> HTMLResponse:
    container = request.app.state.container
    accounts = container.account_service.list_visible_accounts(preferred_account_id=account_id)
    dashboard = container.usage_sync_coordinator.get_dashboard(account_id=account_id)

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "accounts": accounts,
            "dashboard": dashboard,
            "selected_account_id": dashboard.account.account_id if dashboard.account else None,
        },
    )
