from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.error import URLError
from urllib.request import urlopen
import re

from playwright.sync_api import sync_playwright

from app.config import Settings
from app.models.account import AccountRecord
from app.models.browser_session import BrowserSessionSnapshot, BrowserSessionState
from app.services.scraper_service import ScraperUnavailableError


class LiveSessionRequiredError(ScraperUnavailableError):
    pass


@dataclass
class ManagedBrowserSession:
    account_id: str
    context_dir: Path
    debug_port: int
    browser_app_name: str
    state: BrowserSessionState
    launched_at: datetime
    last_seen_at: datetime
    current_url: Optional[str] = None
    last_error: Optional[str] = None


class BrowserWorkerService:
    def __init__(self, settings: Settings, scraper_service) -> None:
        self._settings = settings
        self._scraper_service = scraper_service
        self._lock = threading.RLock()
        self._sessions: dict[str, ManagedBrowserSession] = {}

    def start_login_session(
        self,
        account_id: str,
        context_dir: Path,
        target_url: Optional[str] = None,
    ) -> BrowserSessionSnapshot:
        with self._lock:
            self.close_session(account_id)
            context_dir.mkdir(parents=True, exist_ok=True)
            target_url = target_url or self._settings.manual_login_url
            existing = self._find_existing_browser_worker(
                [
                    context_dir,
                    context_dir.parent / f"{context_dir.name}-cdp",
                ]
            )
            if existing is not None:
                existing_context_dir, debug_port = existing
                launched_at = datetime.now(timezone.utc)
                session = ManagedBrowserSession(
                    account_id=account_id,
                    context_dir=existing_context_dir,
                    debug_port=debug_port,
                    browser_app_name=self._settings.browser_app_name,
                    state=BrowserSessionState.AWAITING_LOGIN,
                    launched_at=launched_at,
                    last_seen_at=launched_at,
                    current_url=target_url,
                )
                session.current_url = self._probe_current_url(debug_port) or session.current_url
                self._sessions[account_id] = session
                return self._snapshot(session)

            self._cleanup_profile_locks(context_dir)

            debug_port = self._allocate_debug_port()
            launched_at = datetime.now(timezone.utc)
            session = ManagedBrowserSession(
                account_id=account_id,
                context_dir=context_dir,
                debug_port=debug_port,
                browser_app_name=self._settings.browser_app_name,
                state=BrowserSessionState.AWAITING_LOGIN,
                launched_at=launched_at,
                last_seen_at=launched_at,
                current_url=target_url,
            )

            try:
                self._launch_browser(
                    context_dir=context_dir,
                    debug_port=debug_port,
                    target_url=target_url,
                )
                self._wait_for_debug_port(debug_port)
                session.current_url = self._probe_current_url(debug_port) or session.current_url
            except Exception as exc:
                session.state = BrowserSessionState.ERROR
                session.last_error = f"Unable to launch CDP browser worker: {exc}"

            self._sessions[account_id] = session
            return self._snapshot(session)

    def ensure_worker_for_account(
        self,
        account: AccountRecord,
        target_url: Optional[str] = None,
    ) -> BrowserSessionSnapshot:
        context_dir = Path(account.session_storage_path)
        with self._lock:
            session = self._sessions.get(account.account_id)
            if session is not None and self._debug_port_ready(session.debug_port):
                current_url = self._probe_current_url(session.debug_port)
                if current_url:
                    session.current_url = current_url
                session.last_seen_at = datetime.now(timezone.utc)
                return self._snapshot(session)

            restored = self._restore_existing_session(account)
            if restored is not None:
                return self._snapshot(restored)

        return self.start_login_session(
            account_id=account.account_id,
            context_dir=context_dir,
            target_url=target_url or self._settings.analytics_url,
        )

    def fetch_usage(self, account: AccountRecord) -> dict:
        with self._lock:
            session = self._sessions.get(account.account_id)
            if session is None:
                session = self._restore_existing_session(account)
                if session is None:
                    raise LiveSessionRequiredError(
                        "No live browser worker for this account. Start login on Mac and keep the browser window open."
                    )

            if not self._debug_port_ready(session.debug_port):
                restored = self._restore_existing_session(account)
                if restored is not None:
                    session = restored
                else:
                    session.state = BrowserSessionState.STOPPED
                    session.last_error = "Live browser worker is not reachable. Start login on Mac again."
                    raise LiveSessionRequiredError(session.last_error)

            try:
                payload, current_url = self._scrape_via_cdp(session.debug_port)
            except ScraperUnavailableError as exc:
                session.state = BrowserSessionState.ERROR
                session.last_error = str(exc)
                session.current_url = self._probe_current_url(session.debug_port)
                session.last_seen_at = datetime.now(timezone.utc)
                raise

            session.state = BrowserSessionState.READY
            session.last_error = None
            session.current_url = current_url
            session.last_seen_at = datetime.now(timezone.utc)
            return payload

    def get_session_snapshot(self, account_id: str) -> Optional[BrowserSessionSnapshot]:
        with self._lock:
            session = self._sessions.get(account_id)
            if session is None:
                return None

            if not self._debug_port_ready(session.debug_port):
                session.state = BrowserSessionState.STOPPED
                session.last_error = "Live browser worker is no longer reachable."
                return self._snapshot(session)

            current_url = self._probe_current_url(session.debug_port)
            if current_url:
                session.current_url = current_url
            return self._snapshot(session)

    def restore_session_snapshot(self, account: AccountRecord) -> Optional[BrowserSessionSnapshot]:
        with self._lock:
            session = self._sessions.get(account.account_id)
            if session is None:
                session = self._restore_existing_session(account)
            if session is None:
                return None
            current_url = self._probe_current_url(session.debug_port)
            if current_url:
                session.current_url = current_url
            return self._snapshot(session)

    def close_session(self, account_id: str) -> None:
        with self._lock:
            session = self._sessions.pop(account_id, None)
            if session is None:
                return
            subprocess.run(
                ["pkill", "-f", str(session.context_dir)],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    def minimize_session(self, account_id: str) -> bool:
        with self._lock:
            session = self._sessions.get(account_id)
            if session is None:
                return False
            if not self._debug_port_ready(session.debug_port):
                session.state = BrowserSessionState.STOPPED
                session.last_error = "Live browser worker is no longer reachable."
                return False
            return self._minimize_debug_port(session.debug_port)

    def shutdown(self) -> None:
        with self._lock:
            account_ids = list(self._sessions.keys())
        for account_id in account_ids:
            self.close_session(account_id)

    def _launch_browser(self, context_dir: Path, debug_port: int, target_url: str) -> None:
        subprocess.Popen(
            [
                "open",
                "-na",
                self._settings.browser_app_name,
                "--args",
                f"--remote-debugging-port={debug_port}",
                f"--user-data-dir={context_dir}",
                "--new-window",
                "--no-first-run",
                "--no-default-browser-check",
                target_url,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def _wait_for_debug_port(self, debug_port: int, timeout_seconds: int = 15) -> None:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            if self._debug_port_ready(debug_port):
                return
            time.sleep(0.5)
        raise RuntimeError(f"CDP port {debug_port} did not become ready in time.")

    def _debug_port_ready(self, debug_port: int) -> bool:
        try:
            with urlopen(self._debug_version_url(debug_port), timeout=2) as response:
                return response.status == 200
        except (URLError, OSError):
            return False

    def _probe_current_url(self, debug_port: int) -> Optional[str]:
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.connect_over_cdp(self._debug_origin(debug_port))
                try:
                    context = browser.contexts[0] if browser.contexts else None
                    if context is None:
                        return None
                    page = context.pages[0] if context.pages else context.new_page()
                    return page.url
                finally:
                    browser.close()
        except Exception:
            return None

    def _scrape_via_cdp(self, debug_port: int) -> tuple[dict, Optional[str]]:
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(self._debug_origin(debug_port))
            try:
                context = browser.contexts[0] if browser.contexts else None
                if context is None:
                    raise LiveSessionRequiredError("No browser context available on the live worker.")
                page = context.pages[0] if context.pages else context.new_page()
                payload = self._scraper_service.fetch_usage_from_page(page)
                return payload, page.url
            finally:
                browser.close()

    def _minimize_debug_port(self, debug_port: int) -> bool:
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.connect_over_cdp(self._debug_origin(debug_port))
                try:
                    context = browser.contexts[0] if browser.contexts else None
                    if context is None:
                        return False
                    page = context.pages[0] if context.pages else context.new_page()
                    cdp_session = context.new_cdp_session(page)
                    window = cdp_session.send("Browser.getWindowForTarget")
                    cdp_session.send(
                        "Browser.setWindowBounds",
                        {
                            "windowId": window["windowId"],
                            "bounds": {"windowState": "minimized"},
                        },
                    )
                    return True
                finally:
                    browser.close()
        except Exception:
            return False

    def _allocate_debug_port(self) -> int:
        base_port = self._settings.browser_debug_base_port
        used_ports = {session.debug_port for session in self._sessions.values()}
        for offset in range(0, 200):
            port = base_port + offset
            if port in used_ports:
                continue
            if not self._debug_port_ready(port):
                return port
        raise RuntimeError("No free CDP debug port available in the configured range.")

    def _debug_origin(self, debug_port: int) -> str:
        return f"http://{self._settings.browser_debug_host}:{debug_port}"

    def _debug_version_url(self, debug_port: int) -> str:
        return f"{self._debug_origin(debug_port)}/json/version"

    def _find_existing_browser_worker(
        self,
        context_dirs: list[Path],
    ) -> Optional[tuple[Path, int]]:
        try:
            result = subprocess.run(
                ["ps", "ax", "-o", "command="],
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.SubprocessError):
            return None

        lookup = sorted(((str(path), path) for path in context_dirs), key=lambda item: len(item[0]), reverse=True)
        for line in result.stdout.splitlines():
            if "--remote-debugging-port=" not in line or "--user-data-dir=" not in line:
                continue
            port_match = re.search(r"--remote-debugging-port=(\d+)", line)
            if port_match is None:
                continue
            matched_dir = None
            for raw_path, candidate in lookup:
                if f"--user-data-dir={raw_path}" in line:
                    matched_dir = candidate
                    break
            if matched_dir is None:
                continue
            debug_port = int(port_match.group(1))
            if self._debug_port_ready(debug_port):
                return matched_dir, debug_port
        return None

    def _cleanup_profile_locks(self, context_dir: Path) -> None:
        for pattern in ("Singleton*", "DevToolsActivePort"):
            for path in context_dir.glob(pattern):
                try:
                    if path.is_dir():
                        for child in path.iterdir():
                            if child.is_file():
                                child.unlink()
                        path.rmdir()
                    else:
                        path.unlink()
                except OSError:
                    continue
        lock_file = context_dir / "Default" / "LOCK"
        if lock_file.exists():
            try:
                lock_file.unlink()
            except OSError:
                pass

    def _restore_existing_session(self, account: AccountRecord) -> Optional[ManagedBrowserSession]:
        context_dir = Path(account.session_storage_path)
        existing = self._find_existing_browser_worker(
            [
                context_dir,
                context_dir.parent / f"{context_dir.name}-cdp",
            ]
        )
        if existing is None:
            return None

        existing_context_dir, debug_port = existing
        now = datetime.now(timezone.utc)
        session = ManagedBrowserSession(
            account_id=account.account_id,
            context_dir=existing_context_dir,
            debug_port=debug_port,
            browser_app_name=self._settings.browser_app_name,
            state=BrowserSessionState.READY,
            launched_at=now,
            last_seen_at=now,
            current_url=self._probe_current_url(debug_port),
        )
        self._sessions[account.account_id] = session
        return session

    def _snapshot(self, session: ManagedBrowserSession) -> BrowserSessionSnapshot:
        return BrowserSessionSnapshot(
            account_id=session.account_id,
            state=session.state,
            context_dir=str(session.context_dir),
            debug_port=session.debug_port,
            browser_app_name=session.browser_app_name,
            current_url=session.current_url,
            last_error=session.last_error,
            launched_at=session.launched_at,
            last_seen_at=session.last_seen_at,
        )
