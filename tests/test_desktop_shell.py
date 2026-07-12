from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_desktop_shell_is_normal_console_not_error_page() -> None:
    html = (PROJECT_ROOT / "desktop" / "index.html").read_text(encoding="utf-8")

    assert "Token BI 控制台" in html
    assert "快捷操作" in html
    assert "服务状态" in html
    assert "正在准备本地服务" in html
    assert "Token BI 启动失败" not in html


def test_desktop_shell_can_render_async_startup_failure() -> None:
    html = (PROJECT_ROOT / "desktop" / "index.html").read_text(encoding="utf-8")

    assert "window.__TOKEN_BI_BOOTSTRAP__" in html
    assert "fail(error)" in html
    assert 'id="controlState"' in html
