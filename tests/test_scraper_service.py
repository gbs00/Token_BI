from __future__ import annotations

from datetime import datetime

import pytest

from app.services.scraper_service import AnalyticsPageChangedError, ScraperService, SessionExpiredError


class _FakePage:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    def goto(self, *args, **kwargs):
        self.calls.append(("goto", args, kwargs))

    def reload(self, *args, **kwargs):
        self.calls.append(("reload", args, kwargs))

    def wait_for_load_state(self, *args, **kwargs):
        self.calls.append(("wait_for_load_state", args, kwargs))


def test_scraper_parses_usage_from_body_text(test_settings) -> None:
    scraper = ScraperService(test_settings)
    payload = scraper._parse_artifacts(
        {
            "title": "Codex Usage",
            "bodyText": """
            Codex Updated just now
            Session 100% left Resets in 5h
            Weekly 92% left Resets in 6d 12h
            """,
            "networkJsonTexts": [],
            "directUsageJsonTexts": [],
            "scriptJsonTexts": [],
        }
    )

    assert payload["session_remaining_pct"] == 100
    assert payload["weekly_remaining_pct"] == 92
    assert payload["source_detail"] == "dom_fallback"
    assert isinstance(payload["session_reset_at"], datetime)
    assert isinstance(payload["weekly_reset_at"], datetime)


def test_scraper_parses_weekly_only_body_text_when_session_quota_removed(test_settings) -> None:
    scraper = ScraperService(test_settings)
    payload = scraper._parse_artifacts(
        {
            "title": "Codex Usage",
            "bodyText": """
            Codex 分析
            Weekly 89% left Resets in 5d 7h
            """,
            "networkJsonTexts": [],
            "directUsageJsonTexts": [],
            "scriptJsonTexts": [],
        }
    )

    assert "session_remaining_pct" not in payload
    assert payload["weekly_remaining_pct"] == 89
    assert payload["source_detail"] == "dom_fallback"
    assert isinstance(payload["weekly_reset_at"], datetime)


def test_scraper_prefers_network_json_over_script_and_dom(test_settings) -> None:
    scraper = ScraperService(test_settings)
    payload = scraper._parse_artifacts(
        {
            "title": "Codex Usage",
            "bodyText": "Session 10% left Resets in 5h Weekly 10% left Resets in 6d",
            "networkJsonTexts": [
                """
                {
                  "data": {
                    "session_remaining_pct": 99,
                    "session_reset_at": "2026-04-22T05:00:00+08:00",
                    "weekly_remaining_pct": 83,
                    "weekly_reset_at": "2026-04-29T00:00:00+08:00",
                    "updated_at": "2026-04-21T23:10:00+08:00"
                  }
                }
                """
            ],
            "directUsageJsonTexts": [],
            "scriptJsonTexts": [
                """
                {
                  "data": {
                    "session_remaining_pct": 88,
                    "session_reset_at": "2026-04-22T03:00:00+08:00",
                    "weekly_remaining_pct": 70,
                    "weekly_reset_at": "2026-04-28T00:00:00+08:00",
                    "updated_at": "2026-04-21T23:00:00+08:00"
                  }
                }
                """
            ],
        }
    )

    assert payload["session_remaining_pct"] == 99
    assert payload["weekly_remaining_pct"] == 83
    assert payload["source_detail"] == "network_response"
    assert payload["updated_at"].isoformat() == "2026-04-21T23:10:00+08:00"


def test_scraper_parses_usage_from_script_json(test_settings) -> None:
    scraper = ScraperService(test_settings)
    payload = scraper._parse_artifacts(
        {
            "title": "Codex Usage",
            "bodyText": "Unused",
            "networkJsonTexts": [],
            "directUsageJsonTexts": [],
            "scriptJsonTexts": [
                """
                {
                  "data": {
                    "session_remaining_pct": 88,
                    "session_reset_at": "2026-04-22T03:00:00+08:00",
                    "weekly_remaining_pct": 70,
                    "weekly_reset_at": "2026-04-28T00:00:00+08:00",
                    "updated_at": "2026-04-21T23:00:00+08:00"
                  }
                }
                """
            ],
        }
        )

    assert payload["session_remaining_pct"] == 88
    assert payload["weekly_remaining_pct"] == 70
    assert payload["source_detail"] == "script_json"
    assert payload["updated_at"].isoformat() == "2026-04-21T23:00:00+08:00"


def test_scraper_parses_usage_from_direct_wham_payload(test_settings) -> None:
    scraper = ScraperService(test_settings)
    payload = scraper._parse_artifacts(
        {
            "title": "Codex",
            "bodyText": "中文界面",
            "networkJsonTexts": [],
            "directUsageJsonTexts": [
                """
                {
                  "rate_limit": {
                    "primary_window": {
                      "used_percent": 9,
                      "reset_at": 1776843664
                    },
                    "secondary_window": {
                      "used_percent": 1,
                      "reset_at": 1777430464
                    }
                  }
                }
                """
            ],
            "scriptJsonTexts": [],
        }
    )

    assert payload["session_remaining_pct"] == 91
    assert payload["weekly_remaining_pct"] == 99
    assert payload["source_detail"] == "direct_usage_fetch"
    assert isinstance(payload["session_reset_at"], datetime)
    assert isinstance(payload["weekly_reset_at"], datetime)


def test_scraper_parses_weekly_only_direct_wham_payload(test_settings) -> None:
    scraper = ScraperService(test_settings)
    payload = scraper._parse_artifacts(
        {
            "title": "Codex",
            "bodyText": "中文界面",
            "networkJsonTexts": [],
            "directUsageJsonTexts": [
                """
                {
                  "rate_limit": {
                    "secondary_window": {
                      "used_percent": 11,
                      "reset_at": 1777430464
                    }
                  }
                }
                """
            ],
            "scriptJsonTexts": [],
        }
    )

    assert "session_remaining_pct" not in payload
    assert payload["weekly_remaining_pct"] == 89
    assert payload["source_detail"] == "direct_usage_fetch"
    assert isinstance(payload["weekly_reset_at"], datetime)


def test_scraper_treats_single_weekly_wham_primary_window_as_weekly(test_settings) -> None:
    scraper = ScraperService(test_settings)
    payload = scraper._parse_artifacts(
        {
            "title": "Codex",
            "bodyText": "中文界面",
            "networkJsonTexts": [
                """
                {
                  "rate_limit": {
                    "primary_window": {
                      "used_percent": 11,
                      "reset_at": 1777430464,
                      "limit_window_seconds": 604800
                    },
                    "secondary_window": null
                  }
                }
                """
            ],
            "directUsageJsonTexts": [],
            "scriptJsonTexts": [],
        }
    )

    assert "session_remaining_pct" not in payload
    assert payload["weekly_remaining_pct"] == 89
    assert payload["source_detail"] == "network_response"
    assert isinstance(payload["weekly_reset_at"], datetime)


def test_scraper_extracts_masked_account_identity_from_json(test_settings) -> None:
    scraper = ScraperService(test_settings)
    payload = scraper._parse_artifacts(
        {
            "title": "Codex",
            "bodyText": "中文界面",
            "networkJsonTexts": [],
            "directIdentityJsonTexts": [
                """
                {
                  "user": {
                    "name": "Real User",
                    "email": "someone.long@example.com"
                  }
                }
                """
            ],
            "directUsageJsonTexts": [
                """
                {
                  "rate_limit": {
                    "primary_window": {
                      "used_percent": 10,
                      "reset_at": 1776843664
                    },
                    "secondary_window": {
                      "used_percent": 3,
                      "reset_at": 1777430464
                    }
                  }
                }
                """
            ],
            "scriptJsonTexts": [],
        }
    )

    assert payload["account_masked_email"] == "some****@example.com"
    assert payload["session_remaining_pct"] == 90
    assert payload["weekly_remaining_pct"] == 97


def test_scraper_parses_usage_from_chinese_dom_text(test_settings) -> None:
    scraper = ScraperService(test_settings)
    payload = scraper._parse_artifacts(
        {
            "title": "Codex",
            "bodyText": """
            Codex 分析
            5 小时使用限额 91% 剩余 重置时间：15:41
            每周使用限额 99% 剩余 重置时间：2026年4月29日 10:41
            """,
            "networkJsonTexts": [],
            "directUsageJsonTexts": [],
            "scriptJsonTexts": [],
        }
    )

    assert payload["session_remaining_pct"] == 91
    assert payload["weekly_remaining_pct"] == 99
    assert payload["source_detail"] == "dom_fallback"
    assert isinstance(payload["session_reset_at"], datetime)
    assert isinstance(payload["weekly_reset_at"], datetime)


def test_scraper_parses_weekly_only_chinese_dom_text(test_settings) -> None:
    scraper = ScraperService(test_settings)
    payload = scraper._parse_artifacts(
        {
            "title": "Codex",
            "bodyText": """
            Codex 分析
            每周使用限额 89% 剩余 重置时间：2026年4月30日 10:41
            """,
            "networkJsonTexts": [],
            "directUsageJsonTexts": [],
            "scriptJsonTexts": [],
        }
    )

    assert "session_remaining_pct" not in payload
    assert payload["weekly_remaining_pct"] == 89
    assert payload["source_detail"] == "dom_fallback"
    assert isinstance(payload["weekly_reset_at"], datetime)


def test_scraper_detects_login_gate(test_settings) -> None:
    scraper = ScraperService(test_settings)
    with pytest.raises(SessionExpiredError):
        scraper._parse_artifacts(
            {
                "title": "Sign in - ChatGPT",
                "bodyText": "Please log in to continue",
                "networkJsonTexts": [],
                "directUsageJsonTexts": [],
                "scriptJsonTexts": [],
            }
        )


def test_scraper_raises_when_structure_unknown(test_settings) -> None:
    scraper = ScraperService(test_settings)
    with pytest.raises(AnalyticsPageChangedError):
        scraper._parse_artifacts(
            {
                "title": "Codex Usage",
                "bodyText": "Usage page without recognizable metrics",
                "networkJsonTexts": [],
                "directUsageJsonTexts": [],
                "scriptJsonTexts": [],
            }
        )


def test_scraper_forces_reload_after_analytics_navigation(test_settings) -> None:
    scraper = ScraperService(test_settings)
    page = _FakePage()

    scraper._navigate_to_fresh_analytics_page(page)

    assert page.calls[0][0] == "goto"
    assert page.calls[0][1][0] == test_settings.analytics_url
    assert page.calls[1][0] == "wait_for_load_state"
    assert page.calls[2][0] == "reload"
    assert page.calls[3][0] == "wait_for_load_state"
