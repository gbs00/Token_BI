from __future__ import annotations

from app.models.browser_session import BrowserSessionState
from app.services.browser_worker_service import ManagedBrowserSession
from app.services.browser_worker_service import BrowserWorkerService
from datetime import datetime, timezone
from subprocess import CompletedProcess


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


def test_find_existing_browser_worker_handles_profile_paths_with_spaces(test_settings, monkeypatch, tmp_path) -> None:
    service = BrowserWorkerService(test_settings, _StubScraperService())
    context_dir = tmp_path / "Application Support" / "Token BI" / "runtime" / "contexts" / "acc_existing"
    context_dir.mkdir(parents=True)
    command = (
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome "
        "--remote-debugging-port=9333 "
        f"--user-data-dir={context_dir} "
        "--new-window https://chatgpt.com/#usage"
    )

    monkeypatch.setattr(
        "app.services.browser_worker_service.subprocess.run",
        lambda *args, **kwargs: CompletedProcess(args=args, returncode=0, stdout=command),
    )
    monkeypatch.setattr(service, "_debug_port_ready", lambda port: port == 9333)

    assert service._find_existing_browser_worker([context_dir]) == (context_dir, 9333)


def test_minimize_session_only_targets_managed_worker(test_settings, monkeypatch) -> None:
    service = BrowserWorkerService(test_settings, _StubScraperService())
    now = datetime.now(timezone.utc)
    service._sessions["acc_ready"] = ManagedBrowserSession(
        account_id="acc_ready",
        context_dir=test_settings.runtime_contexts_dir / "acc_ready",
        debug_port=9333,
        browser_app_name="Google Chrome",
        state=BrowserSessionState.READY,
        launched_at=now,
        last_seen_at=now,
    )
    minimized_ports: list[int] = []

    monkeypatch.setattr(service, "_debug_port_ready", lambda port: True)
    monkeypatch.setattr(service, "_minimize_debug_port", lambda port: minimized_ports.append(port) or True)

    assert service.minimize_session("acc_ready") is True
    assert service.minimize_session("acc_missing") is False
    assert minimized_ports == [9333]
