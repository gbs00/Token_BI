from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from hashlib import md5
from typing import Any, Iterable, Optional

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from app.config import Settings
from app.models.account import AccountRecord


class ScraperUnavailableError(RuntimeError):
    pass


class SessionExpiredError(ScraperUnavailableError):
    pass


class AnalyticsPageChangedError(ScraperUnavailableError):
    pass


class ScraperService:
    RESET_UNITS = {
        "d": "days",
        "day": "days",
        "days": "days",
        "h": "hours",
        "hour": "hours",
        "hours": "hours",
        "m": "minutes",
        "min": "minutes",
        "mins": "minutes",
        "minute": "minutes",
        "minutes": "minutes",
    }

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def fetch_usage(self, account: AccountRecord) -> dict:
        if self._settings.mock_scraper_enabled:
            return self._build_mock_payload(account)
        artifacts = self._load_page_artifacts(account.session_storage_path)
        return self._parse_artifacts(artifacts)

    def fetch_usage_from_page(self, page) -> dict:
        artifacts = self._collect_page_artifacts(page)
        return self._parse_artifacts(artifacts)

    def _load_page_artifacts(self, context_dir: str) -> dict:
        try:
            with sync_playwright() as playwright:
                browser_context = playwright.chromium.launch_persistent_context(
                    user_data_dir=context_dir,
                    channel=self._settings.playwright_channel or None,
                    headless=self._settings.playwright_headless,
                )
                try:
                    page = browser_context.pages[0] if browser_context.pages else browser_context.new_page()
                    return self._collect_page_artifacts(page)
                finally:
                    browser_context.close()
        except PlaywrightTimeoutError as exc:
            raise ScraperUnavailableError("Timed out while loading Codex analytics page.") from exc
        except PlaywrightError as exc:
            raise ScraperUnavailableError(f"Unable to access Codex analytics page: {exc}") from exc

    def _collect_page_artifacts(self, page) -> dict:
        network_json_texts: list[str] = []

        def capture_response(response) -> None:
            try:
                content_type = response.headers.get("content-type", "").lower()
                url = response.url.lower()
                if "json" not in content_type:
                    return
                if not any(
                    marker in url for marker in ("usage", "wham", "rate", "limit", "account")
                ):
                    return
                network_json_texts.append(response.text())
            except PlaywrightError:
                return

        page.on("response", capture_response)
        try:
            self._navigate_to_fresh_analytics_page(page)
            artifacts = page.evaluate(
                """() => ({
                    title: document.title || "",
                    url: window.location.href,
                    bodyText: document.body ? document.body.innerText : "",
                    scriptJsonTexts: Array.from(
                      document.querySelectorAll('script[type="application/json"]')
                    ).map(node => node.textContent || "")
                })"""
            )
            artifacts["networkJsonTexts"] = network_json_texts
            artifacts["directUsageJsonTexts"] = []
            artifacts["directIdentityJsonTexts"] = []
            try:
                direct_payload = page.evaluate(
                    """async () => {
                        const response = await fetch('/backend-api/wham/usage', {
                          credentials: 'include',
                          headers: { accept: 'application/json' }
                        });
                        if (!response.ok) {
                          return null;
                        }
                        return await response.text();
                    }"""
                )
                if direct_payload:
                    artifacts["directUsageJsonTexts"].append(direct_payload)
            except PlaywrightError:
                pass
            for identity_url in (
                "/backend-api/me",
                "/backend-api/accounts/check/v4-2023-04-27",
            ):
                try:
                    identity_payload = page.evaluate(
                        """async (url) => {
                            const response = await fetch(url, {
                              credentials: 'include',
                              headers: { accept: 'application/json' }
                            });
                            if (!response.ok) {
                              return null;
                            }
                            return await response.text();
                        }""",
                        identity_url,
                    )
                    if identity_payload:
                        artifacts["directIdentityJsonTexts"].append(identity_payload)
                except PlaywrightError:
                    continue
            return artifacts
        finally:
            try:
                page.remove_listener("response", capture_response)
            except Exception:
                pass

    def _navigate_to_fresh_analytics_page(self, page) -> None:
        page.goto(
            self._settings.analytics_url,
            wait_until="domcontentloaded",
            timeout=self._settings.scrape_timeout_ms,
        )
        self._wait_for_page_settle(page)

        # `analytics#usage` is a hash route. If we're already on that route,
        # `goto` may not force a fresh data load, so do one explicit reload.
        page.reload(
            wait_until="domcontentloaded",
            timeout=self._settings.scrape_timeout_ms,
        )
        self._wait_for_page_settle(page)

    def _wait_for_page_settle(self, page) -> None:
        try:
            page.wait_for_load_state("networkidle", timeout=3000)
        except PlaywrightTimeoutError:
            # Network idle is a best-effort hint, not a hard failure.
            pass

    def _parse_artifacts(self, artifacts: dict) -> dict:
        body_text = self._normalize_text(artifacts.get("bodyText", ""))
        title = self._normalize_text(artifacts.get("title", ""))
        account_identity = self._extract_account_identity(artifacts, body_text)

        if self._looks_like_login_gate(title=title, body_text=body_text):
            raise SessionExpiredError("Session expired on Mac. Please sign in again on Mac.")

        direct_data = self._extract_usage_from_json_texts(artifacts.get("directUsageJsonTexts", []))
        if direct_data is not None:
            direct_data["source_detail"] = "direct_usage_fetch"
            return self._with_account_identity(direct_data, account_identity)

        network_data = self._extract_usage_from_json_texts(artifacts.get("networkJsonTexts", []))
        if network_data is not None:
            network_data["source_detail"] = "network_response"
            return self._with_account_identity(network_data, account_identity)

        script_data = self._extract_usage_from_json_texts(artifacts.get("scriptJsonTexts", []))
        if script_data is not None:
            script_data["source_detail"] = "script_json"
            return self._with_account_identity(script_data, account_identity)

        text_data = self._extract_usage_from_text(body_text)
        if text_data is not None:
            text_data["source_detail"] = "dom_fallback"
            return self._with_account_identity(text_data, account_identity)

        raise AnalyticsPageChangedError("Analytics page may have changed.")

    def _with_account_identity(self, payload: dict, account_identity: Optional[str]) -> dict:
        if account_identity:
            payload["account_masked_email"] = account_identity
        return payload

    def _extract_account_identity(self, artifacts: dict, body_text: str) -> Optional[str]:
        json_sources = [
            *artifacts.get("directIdentityJsonTexts", []),
            *artifacts.get("networkJsonTexts", []),
            *artifacts.get("scriptJsonTexts", []),
        ]
        identity = self._extract_identity_from_json_texts(json_sources)
        if identity:
            return identity

        email_match = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", body_text)
        if email_match:
            return self._mask_email(email_match.group(0))
        return None

    def _extract_identity_from_json_texts(self, json_texts: Iterable[str]) -> Optional[str]:
        for text in json_texts:
            stripped = text.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            identity = self._find_identity(payload)
            if identity:
                return identity
        return None

    def _find_identity(self, payload: Any) -> Optional[str]:
        return self._find_email_identity(payload) or self._find_label_identity(payload)

    def _find_email_identity(self, payload: Any) -> Optional[str]:
        if isinstance(payload, dict):
            for key, value in payload.items():
                key_lower = str(key).lower()
                if isinstance(value, str):
                    if "email" in key_lower and "@" in value:
                        return self._mask_email(value)
                nested = self._find_email_identity(value)
                if nested:
                    return nested
        elif isinstance(payload, list):
            for item in payload:
                nested = self._find_email_identity(item)
                if nested:
                    return nested
        elif isinstance(payload, str) and "@" in payload:
            email_match = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", payload)
            if email_match:
                return self._mask_email(email_match.group(0))
        return None

    def _find_label_identity(self, payload: Any) -> Optional[str]:
        if isinstance(payload, dict):
            for key, value in payload.items():
                key_lower = str(key).lower()
                if isinstance(value, str) and key_lower in {"username", "display_name", "name"} and value.strip():
                    return self._mask_label(value)
                nested = self._find_label_identity(value)
                if nested:
                    return nested
        elif isinstance(payload, list):
            for item in payload:
                nested = self._find_label_identity(item)
                if nested:
                    return nested
        return None

    def _mask_email(self, email: str) -> str:
        local, _, domain = email.strip().partition("@")
        if not local or not domain:
            return self._mask_label(email)
        keep = min(4, max(1, len(local)))
        return f"{local[:keep]}****@{domain}"

    def _mask_label(self, value: str) -> str:
        normalized = self._normalize_text(value)
        if not normalized:
            return ""
        if len(normalized) <= 4:
            return normalized
        return f"{normalized[:4]}..."

    def _extract_usage_from_json_texts(self, json_texts: Iterable[str]) -> Optional[dict]:
        for text in json_texts:
            stripped = text.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            extracted = self._find_usage_keys(payload)
            if extracted is not None:
                return extracted
        return None

    def _find_usage_keys(self, payload: Any) -> Optional[dict]:
        if isinstance(payload, dict):
            direct = self._extract_usage_dict(payload)
            if direct is not None:
                return direct
            for value in payload.values():
                nested = self._find_usage_keys(value)
                if nested is not None:
                    return nested
        elif isinstance(payload, list):
            for item in payload:
                nested = self._find_usage_keys(item)
                if nested is not None:
                    return nested
        return None

    def _extract_usage_dict(self, payload: dict) -> Optional[dict]:
        wham_rate_limit = payload.get("rate_limit")
        if isinstance(wham_rate_limit, dict):
            primary = wham_rate_limit.get("primary_window") or {}
            secondary = wham_rate_limit.get("secondary_window") or {}
            if (
                "used_percent" in primary
                and "reset_at" in primary
                and "used_percent" in secondary
                and "reset_at" in secondary
            ):
                return {
                    "session_remaining_pct": max(0, 100 - int(primary["used_percent"])),
                    "session_reset_at": self._coerce_datetime(primary["reset_at"]),
                    "weekly_remaining_pct": max(0, 100 - int(secondary["used_percent"])),
                    "weekly_reset_at": self._coerce_datetime(secondary["reset_at"]),
                    "updated_at": datetime.now().astimezone(),
                    "is_estimated": False,
                }

        required = {
            "session_remaining_pct",
            "session_reset_at",
            "weekly_remaining_pct",
            "weekly_reset_at",
        }
        if not required.issubset(payload.keys()):
            return None
        return {
            "session_remaining_pct": int(payload["session_remaining_pct"]),
            "session_reset_at": self._coerce_datetime(payload["session_reset_at"]),
            "weekly_remaining_pct": int(payload["weekly_remaining_pct"]),
            "weekly_reset_at": self._coerce_datetime(payload["weekly_reset_at"]),
            "updated_at": self._coerce_datetime(payload.get("updated_at")) or datetime.now().astimezone(),
            "is_estimated": bool(payload.get("is_estimated", False)),
        }

    def _extract_usage_from_text(self, body_text: str) -> Optional[dict]:
        if not body_text:
            return None

        session = self._extract_metric_from_text(body_text, "Session")
        weekly = self._extract_metric_from_text(body_text, "Weekly")
        if session is None or weekly is None:
            session = self._extract_metric_from_chinese_text(body_text, "session")
            weekly = self._extract_metric_from_chinese_text(body_text, "weekly")
        if session is None or weekly is None:
            return None

        return {
            "session_remaining_pct": session["remaining_pct"],
            "session_reset_at": session["reset_at"],
            "weekly_remaining_pct": weekly["remaining_pct"],
            "weekly_reset_at": weekly["reset_at"],
            "updated_at": datetime.now().astimezone(),
            "is_estimated": False,
        }

    def _extract_metric_from_text(self, text: str, label: str) -> Optional[dict]:
        patterns = [
            rf"{label}.*?(\d{{1,3}})%\s+(?:left|remaining).*?Resets?\s+in\s+(.+?)(?=(?:Session|Weekly|On pace|Runs out|$))",
            rf"{label}.*?(\d{{1,3}})%.*?Resets?\s+in\s+(.+?)(?=(?:Session|Weekly|On pace|Runs out|$))",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if not match:
                continue
            remaining_pct = int(match.group(1))
            reset_phrase = match.group(2).strip()
            reset_at = self._parse_relative_reset(reset_phrase)
            return {
                "remaining_pct": remaining_pct,
                "reset_at": reset_at,
            }
        return None

    def _extract_metric_from_chinese_text(self, text: str, metric_type: str) -> Optional[dict]:
        if metric_type == "session":
            pattern = r"5\s*小时使用限额.*?(\d{1,3})%\s*剩余.*?重置时间[:：]\s*([0-9]{1,2}:[0-9]{2})"
            parser = self._parse_chinese_time_only
        else:
            pattern = r"每周使用限额.*?(\d{1,3})%\s*剩余.*?重置时间[:：]\s*([0-9]{4}年\d{1,2}月\d{1,2}日\s*[0-9]{1,2}:[0-9]{2})"
            parser = self._parse_chinese_datetime

        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            return None

        return {
            "remaining_pct": int(match.group(1)),
            "reset_at": parser(match.group(2).strip()),
        }

    def _parse_relative_reset(self, value: str) -> datetime:
        normalized = value.lower().replace(",", " ")
        matches = re.findall(
            r"(\d+)\s*(d|day|days|h|hour|hours|m|min|mins|minute|minutes)\b",
            normalized,
        )
        if not matches:
            raise AnalyticsPageChangedError(f"Unsupported reset phrase: {value}")

        delta = timedelta()
        for amount_str, unit in matches:
            amount = int(amount_str)
            mapped = self.RESET_UNITS[unit]
            if mapped == "days":
                delta += timedelta(days=amount)
            elif mapped == "hours":
                delta += timedelta(hours=amount)
            elif mapped == "minutes":
                delta += timedelta(minutes=amount)
        return datetime.now().astimezone() + delta

    def _parse_chinese_time_only(self, value: str) -> datetime:
        now = datetime.now().astimezone()
        hour, minute = [int(part) for part in value.split(":", 1)]
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate < now:
            candidate += timedelta(days=1)
        return candidate

    def _parse_chinese_datetime(self, value: str) -> datetime:
        normalized = re.sub(r"\s+", " ", value.strip())
        match = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})", normalized)
        if not match:
            raise AnalyticsPageChangedError(f"Unsupported Chinese datetime payload: {value}")
        year, month, day, hour, minute = [int(item) for item in match.groups()]
        now = datetime.now().astimezone()
        return now.replace(
            year=year,
            month=month,
            day=day,
            hour=hour,
            minute=minute,
            second=0,
            microsecond=0,
        )

    def _looks_like_login_gate(self, title: str, body_text: str) -> bool:
        haystack = f"{title} {body_text}".lower()
        signals = [
            "log in",
            "sign in",
            "continue with",
            "verify you are human",
            "welcome back",
        ]
        return any(signal in haystack for signal in signals)

    def _coerce_datetime(self, value: Any) -> Optional[datetime]:
        if value in {None, ""}:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc).astimezone()
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        raise AnalyticsPageChangedError(f"Unsupported datetime payload: {value}")

    def _normalize_text(self, value: str) -> str:
        return re.sub(r"\s+", " ", value or "").strip()

    def _build_mock_payload(self, account: AccountRecord) -> dict:
        digest = md5(account.account_id.encode("utf-8")).hexdigest()
        session_pct = 65 + int(digest[:2], 16) % 36
        weekly_pct = 40 + int(digest[2:4], 16) % 56
        session_hours = 2 + int(digest[4:6], 16) % 6
        weekly_days = 2 + int(digest[6:8], 16) % 6
        weekly_hours = 4 + int(digest[8:10], 16) % 18
        now = datetime.now().astimezone()
        return {
            "session_remaining_pct": session_pct,
            "session_reset_at": now + timedelta(hours=session_hours),
            "weekly_remaining_pct": weekly_pct,
            "weekly_reset_at": now + timedelta(days=weekly_days, hours=weekly_hours),
            "updated_at": now,
            "is_estimated": True,
            "source_detail": "mock",
        }
