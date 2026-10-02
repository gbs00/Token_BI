import json
import stat

import pytest

from app.services import local_json_store


def test_private_json_write_atomically_replaces_existing_file(tmp_path):
    path = tmp_path / "metadata.json"
    path.write_text('{"old": true}', encoding="utf-8")
    path.chmod(0o644)

    local_json_store.write_private_json(path, {"new": True})

    assert json.loads(path.read_text()) == {"new": True}
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not list(tmp_path.glob("*.tmp"))


def test_failed_atomic_replace_keeps_original_and_cleans_temporary_file(tmp_path, monkeypatch):
    path = tmp_path / "metadata.json"
    original = '{"old": true}'
    path.write_text(original, encoding="utf-8")
    def fail_replace(*args):
        raise OSError("replace fixture failure")
    monkeypatch.setattr(local_json_store.os, "replace", fail_replace)

    with pytest.raises(OSError, match="fixture"):
        local_json_store.write_private_json(path, {"new": True})

    assert path.read_text() == original
    assert not list(tmp_path.glob("*.tmp"))
