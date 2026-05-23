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


def _write_active_account_with_weekly_only_snapshot(app, account_id: str, email: str, weekly_pct: int) -> None:
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
                "weekly_remaining_pct": weekly_pct,
                "weekly_reset_at": "2026-04-30T16:00:00+08:00",
                "updated_at": "2026-04-26T10:24:35+08:00",
            }
        ),
        encoding="utf-8",
    )


def _write_active_account_with_windows(app, account_id: str, email: str, windows: list[dict]) -> None:
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
                "windows": windows,
                "updated_at": "2026-05-24T10:24:35+08:00",
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


def test_dashboard_sync_button_replaces_refresh_copy_and_uses_radial_cards(app) -> None:
    _write_active_account_with_snapshot(app, "acc_real", "8754****@qq.com", 86, 72)

    response = TestClient(app).get("/dashboard")

    assert response.status_code == 200
    html = response.text
    assert "同步额度" in html
    assert ">Refresh<" not in html
    assert 'class="metric-radial"' in html
    assert "progress-fill" not in html


def test_dashboard_renders_weekly_only_quota_without_session_card(app) -> None:
    _write_active_account_with_weekly_only_snapshot(app, "acc_real", "8754****@qq.com", 89)

    response = TestClient(app).get("/dashboard")

    assert response.status_code == 200
    html = response.text
    assert "周额度" in html
    assert "89%" in html
    assert "5h 额度" not in html
    assert "Reset time unavailable" not in html


def test_dashboard_api_filters_unknown_windows_and_normalizes_quota_labels(app) -> None:
    _write_active_account_with_windows(
        app,
        "acc_real",
        "8754****@qq.com",
        [
            {
                "display_name": "5h window",
                "remaining_pct": 84,
                "reset_at": "2026-05-24T16:00:00+08:00",
                "window_minutes": 300,
            },
            {
                "display_name": "Weekly",
                "remaining_pct": 61,
                "reset_at": "2026-05-30T16:00:00+08:00",
                "window_minutes": 10080,
            },
            {
                "display_name": "Primary window",
                "remaining_pct": 41,
                "reset_at": "2026-05-25T16:00:00+08:00",
                "window_minutes": 60,
            },
        ],
    )

    response = TestClient(app).get("/api/v1/dashboard")

    assert response.status_code == 200
    payload = response.json()
    assert [metric["metric_type"] for metric in payload["metrics"]] == ["session", "weekly"]
    assert [metric["label"] for metric in payload["metrics"]] == ["5h 额度", "周额度"]
    assert "Primary window" not in json.dumps(payload, ensure_ascii=False)


def test_dashboard_markup_uses_radial_quota_cards_without_outer_percent_or_progress(app) -> None:
    _write_active_account_with_snapshot(app, "acc_real", "8754****@qq.com", 84, 61)

    response = TestClient(app).get("/dashboard")

    assert response.status_code == 200
    html = response.text
    assert "metric-radial" in html
    assert html.count("data-metric-percent") == 2
    assert "metric-value" not in html
    assert "metric-suffix" not in html
    assert "progress-track" not in html
    assert "Remaining usage window" not in html
    assert "Reset time unavailable" not in html


def test_dashboard_uses_desktop_bi_layout_styles() -> None:
    css = Path("app/static/css/dashboard.css").read_text(encoding="utf-8")

    assert "width: min(100%, 100vw)" in css
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in css
    assert "conic-gradient(var(--metric-color)" in css
    assert "min-height: 100dvh" in css
    assert ".agent-nav" not in css


def test_dashboard_landscape_keeps_quota_number_prominent_on_small_ios_screens() -> None:
    css = Path("app/static/css/dashboard.css").read_text(encoding="utf-8")

    assert "@media (orientation: landscape) and (max-height: 620px)" in css
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in css
    assert "width: min(34vh, 200px)" in css
    assert "font-size: clamp(38px, 11vw, 54px)" not in css


def test_dashboard_metric_suffix_uses_margin_for_legacy_safari_without_flex_gap() -> None:
    css = Path("app/static/css/dashboard.css").read_text(encoding="utf-8")

    assert ".metric-suffix" not in css
    assert ".progress-track" not in css


def test_dashboard_sync_button_forces_live_refresh() -> None:
    js = Path("app/static/js/dashboard.js").read_text(encoding="utf-8")

    assert "/api/v1/dashboard/refresh" in js
    assert 'method: forceRefresh ? "POST" : "GET"' in js


def test_dashboard_js_can_create_metric_cards_after_error_state() -> None:
    js = Path("app/static/js/dashboard.js").read_text(encoding="utf-8")

    assert "function syncMetricCards(metrics)" in js
    assert "createMetricCard(metric)" in js
    assert 'card.setAttribute("data-metric-card", metric.metric_type)' in js
    assert "metric-radial" in js
    assert "progress-track" not in js


def test_dashboard_js_unknown_metric_title_fallback_is_not_fixed_session() -> None:
    js = Path("app/static/js/dashboard.js").read_text(encoding="utf-8")

    assert "function normalizeMetric(metric)" in js
    assert '"5h 额度"' in js
    assert '"周额度"' in js
    assert "Usage window" not in js
    assert 'metric.metric_type === "weekly" ? "Weekly" : "5h Session"' not in js
