from __future__ import annotations

from app.models.browser_session import BrowserSessionState
from app.services.browser_worker_service import BrowserWorkerService


class _StubScraperService:
    pass


def test_start_login_session_adopts_existing_browser_worker(test_settings, monkeypatch) -> None:
    service = BrowserWorkerService(test_settings, _StubScraperService())
    context_dir = test_settings.runtime_contexts_dir / "acc_existing"
    existing_context_dir = context_dir.parent / f"{context_dir.name}-cdp"
    existing_context_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(
        service,
        "_find_existing_browser_worker",
        lambda context_dirs: (existing_context_dir, 9222),
    )
    monkeypatch.setattr(
        service,
        "_probe_current_url",
        lambda debug_port: "https://chatgpt.com/codex/cloud/settings/analytics#usage",
    )

    launch_calls: list[tuple] = []

    def _unexpected_launch(*args, **kwargs):
        launch_calls.append((args, kwargs))
        raise AssertionError("Existing browser worker should be adopted without launching a new browser.")

    monkeypatch.setattr(service, "_launch_browser", _unexpected_launch)

    snapshot = service.start_login_session(
        account_id="acc_existing",
        context_dir=context_dir,
    )

    assert snapshot.account_id == "acc_existing"
    assert snapshot.state == BrowserSessionState.AWAITING_LOGIN
    assert snapshot.debug_port == 9222
    assert snapshot.context_dir == str(existing_context_dir)
    assert snapshot.current_url.endswith("#usage")
    assert launch_calls == []
