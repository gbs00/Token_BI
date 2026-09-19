import os
from pathlib import Path
import select
import subprocess

import httpx
import pytest

from app.config import get_settings


def test_legacy_mock_flag_fails_closed(monkeypatch):
    monkeypatch.setenv("TOKEN_BI_USE_MOCK_SCRAPER", "true")
    with pytest.raises(ValueError, match="start_mock_preview.sh"):
        get_settings.__wrapped__()


def test_mock_entrypoint_never_initializes_real_services_or_changes_accounts(tmp_path):
    root = Path(__file__).resolve().parents[1]
    config = tmp_path / "config" / "accounts.json"
    config.parent.mkdir()
    original = b'{"accounts":[{"account_id":"keep-me"}]}'
    config.write_bytes(original)
    environment = {**os.environ, "TOKEN_BI_APP_DATA_DIR": str(tmp_path),
                   "TOKEN_BI_USE_MOCK_SCRAPER": "true", "PYTHONDONTWRITEBYTECODE": "1"}
    process = subprocess.Popen(["/bin/zsh", str(root / "scripts/start_mock_preview.sh"), "0"],
                               cwd=root, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True)
    try:
        assert select.select([process.stdout], [], [], 8)[0], "preview did not become ready"
        line = process.stdout.readline().strip()
        assert line.startswith("Sample dashboard: http://127.0.0.1:")
        url = line.removeprefix("Sample dashboard: ").removesuffix("/dashboard")
        with httpx.Client(base_url=url, trust_env=False) as client:
            assert client.get("/dashboard").status_code == 200
            payload = client.post("/api/v1/dashboard/refresh").json()
            assert payload["account"]["masked_email"] == "demo****@example.com"
            assert [item["remaining_pct"] for item in payload["metrics"]] == [100, 61]
            assert client.post("/api/v1/accounts").status_code == 404
        assert config.read_bytes() == original
        assert sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()) == ["config/accounts.json"]
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        process.stdout.close()
        process.stderr.close()
