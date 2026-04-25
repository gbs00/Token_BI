from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.models.account import AccountRecord, AccountStatus


def _write_active_account_with_snapshot(app, account_id: str, email: str, session_pct: int, weekly_pct: int) -> None:
    now = datetime.now(timezone.utc)
    app.state.container.account_service._write_accounts(
        [
            AccountRecord(
                account_id=account_id,
                account_alias=email,
                masked_email=email,
                status=AccountStatus.ACTIVE,
                session_storage_path=f"/tmp/{account_id}",
                created_at=now,
                last_validated_at=now,
            )
        ]
    )
    snapshot_path = app.state.container.settings.runtime_local_connector_dir / f"{account_id}.json"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(
        json.dumps(
            {
                "session_remaining_pct": session_pct,
                "session_reset_at": "2026-04-26T16:00:00+08:00",
                "weekly_remaining_pct": weekly_pct,
                "weekly_reset_at": "2026-04-30T16:00:00+08:00",
                "updated_at": "2026-04-26T10:24:35+08:00",
            }
        ),
        encoding="utf-8",
    )


def test_dashboard_directly_displays_masked_account_without_switcher(app) -> None:
    _write_active_account_with_snapshot(app, "acc_real", "8754****@qq.com", 86, 72)

    response = TestClient(app).get("/dashboard")

    assert response.status_code == 200
    html = response.text
    assert "8754****@qq.com" in html
    assert "account-switcher" not in html
    assert "selected-account-bar" not in html
    assert "data-account-pill" in html


def test_dashboard_sync_button_replaces_refresh_copy_and_keeps_tiered_progress(app) -> None:
    _write_active_account_with_snapshot(app, "acc_real", "8754****@qq.com", 86, 72)

    response = TestClient(app).get("/dashboard")

    assert response.status_code == 200
    html = response.text
    assert "同步额度" in html
    assert ">Refresh<" not in html
    assert 'class="progress-fill tier-75-plus"' in html
    assert 'class="progress-fill tier-50-75"' in html


def test_dashboard_uses_desktop_bi_layout_styles() -> None:
    css = Path("app/static/css/dashboard.css").read_text(encoding="utf-8")

    assert "width: min(100%, 920px)" in css
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in css
    assert "font-size: clamp(56px, 8vw, 76px)" in css
    assert ".agent-nav" not in css


def test_dashboard_landscape_keeps_quota_number_prominent_on_small_ios_screens() -> None:
    css = Path("app/static/css/dashboard.css").read_text(encoding="utf-8")

    assert "font-size: 72px;\n  font-size: clamp(56px, 8vw, 76px)" in css
    assert "font-size: 72px;\n    font-size: clamp(58px, 13vw, 76px)" in css
    assert "font-size: clamp(58px, 13vw, 76px)" in css
    assert "font-size: clamp(38px, 11vw, 54px)" not in css


def test_dashboard_metric_suffix_uses_margin_for_legacy_safari_without_flex_gap() -> None:
    css = Path("app/static/css/dashboard.css").read_text(encoding="utf-8")

    assert "margin-left: 10px" in css
    assert "letter-spacing: normal" in css


def test_dashboard_sync_button_forces_live_refresh() -> None:
    js = Path("app/static/js/dashboard.js").read_text(encoding="utf-8")

    assert "/api/v1/dashboard/refresh" in js
    assert 'method: forceRefresh ? "POST" : "GET"' in js
