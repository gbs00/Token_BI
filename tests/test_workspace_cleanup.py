import json
import os
import plistlib
import time
from pathlib import Path

import pytest

from scripts.clean_workspace import apply_cleanup, plan_cleanup


NOW = time.time()
OLD = NOW - 90 * 86400


def make_old(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "data").write_text("fixture")
    for item in [*path.rglob("*"), path]:
        os.utime(item, (OLD, OLD))
    return path


@pytest.fixture
def root(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config/accounts.json").write_text('{"accounts":[]}')
    return tmp_path


def test_cleanup_only_selects_old_unreferenced_idle_profiles(root):
    contexts = root / "runtime/contexts"
    orphan = make_old(contexts / "acc_orphan")
    referenced = make_old(contexts / "acc_known")
    cdp = make_old(contexts / "acc_known-cdp")
    busy = make_old(contexts / "acc_busy")
    recent = make_old(contexts / "acc_recent")
    (recent / "data").write_text("recent activity")
    (root / "config/accounts.json").write_text(json.dumps({"accounts": [{"account_id": "acc_known"}]}))
    plan = plan_cleanup(root, [], {busy / "data"}, NOW)
    assert [Path(entry["path"]) for entry in plan] == [orphan]
    assert referenced.exists() and cdp.exists()


def test_other_data_roots_protect_referenced_profiles(root):
    profile = make_old(root / "runtime/contexts/acc_keep")
    installed = root / "installed-data"
    (installed / "config").mkdir(parents=True)
    (installed / "config/accounts.json").write_text(json.dumps({"accounts": [
        {"account_id": "acc_other", "session_storage_path": str(profile)}
    ]}))
    assert plan_cleanup(root, [installed], set(), NOW) == []


def test_missing_or_invalid_registry_never_allows_profile_deletion(root):
    make_old(root / "runtime/contexts/acc_orphan")
    accounts = root / "config/accounts.json"
    accounts.unlink()
    assert plan_cleanup(root, [], set(), NOW) == []
    accounts.write_text("broken json")
    with pytest.raises(json.JSONDecodeError):
        plan_cleanup(root, [], set(), NOW)


def test_cleanup_skips_redirected_directories(root):
    outside = make_old(root / "outside")
    contexts = root / "runtime/contexts"
    contexts.mkdir(parents=True)
    (contexts / "acc_link").symlink_to(outside)
    assert plan_cleanup(root, [], set(), NOW) == []
    (root / "dist").symlink_to(outside)
    release = make_old(outside / "release-v1.0.0")
    make_old(outside / "release-v1.0.1")
    make_old(outside / "release-v1.0.2")
    assert plan_cleanup(root, [], set(), NOW) == []
    assert release.exists()


def test_retention_keeps_two_backups_and_releases_and_current_build(root):
    backups = []
    for index in range(4):
        backup = make_old(root / "dist" / f"Token BI-before-{index}.noindex")
        (backup / "Contents").mkdir()
        (backup / "Contents/Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": "com.gbs00.tokenbi"}))
        os.utime(backup, (OLD + index, OLD + index))
        backups.append(backup)
        make_old(root / "dist" / f"release-v1.2.{index}")
    target = make_old(root / "src-tauri/target")
    (target / ".rustc_info.json").write_text("{}")
    current = make_old(root / "src-tauri/target.noindex")
    other = make_old(root / "dist/user-file")
    plan = plan_cleanup(root, [], set(), NOW)
    paths = {Path(entry["path"]) for entry in plan}
    assert paths == {*backups[:2], target, root / "dist/release-v1.2.0", root / "dist/release-v1.2.1"}
    assert current.exists() and other.exists()
    assert target not in {Path(entry["path"]) for entry in plan_cleanup(root, [], {target / "debug/running"}, NOW)}


def test_cleanup_rechecks_ownership_before_removing(root, monkeypatch):
    orphan = make_old(root / "runtime/contexts/acc_orphan")
    plan = plan_cleanup(root, [], set(), NOW)
    monkeypatch.setattr("scripts.clean_workspace.process_paths", lambda: {orphan / "data"})
    with pytest.raises(RuntimeError, match="目标已变化"):
        apply_cleanup(root, [], plan)
    assert orphan.exists()
    monkeypatch.setattr("scripts.clean_workspace.process_paths", lambda: set())
    assert apply_cleanup(root, [], plan) == plan
    assert not orphan.exists()


def test_cleanup_refuses_forged_external_target(root, monkeypatch):
    target = make_old(root / "valuable")
    monkeypatch.setattr("scripts.clean_workspace.process_paths", lambda: set())
    with pytest.raises(RuntimeError, match="目标已变化"):
        apply_cleanup(root, [], [{"path": str(target)}])
    assert target.exists()
