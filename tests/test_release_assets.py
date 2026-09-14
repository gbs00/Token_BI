import base64
import hashlib
import json

import pytest

from scripts.prepare_release import prepare


@pytest.fixture
def release_root(tmp_path):
    (tmp_path / "src-tauri").mkdir()
    (tmp_path / "docs").mkdir()
    config = {"version": "1.2.1", "plugins": {"updater": {"pubkey": base64.b64encode(b"untrusted comment: minisign public key: fixture").decode()}}}
    (tmp_path / "package.json").write_text('{"version":"1.2.1"}')
    (tmp_path / "src-tauri/tauri.conf.json").write_text(json.dumps(config))
    (tmp_path / "docs/RELEASE_NOTES_v1.2.1.md").write_text("Release fixture")
    bundle = tmp_path / "src-tauri/target.noindex/release/bundle"
    (bundle / "macos").mkdir(parents=True)
    (bundle / "dmg").mkdir()
    (bundle / "macos/Token BI.app.tar.gz").write_bytes(b"archive fixture")
    (bundle / "macos/Token BI.app.tar.gz.sig").write_text(base64.b64encode(b"untrusted comment: fixture signature").decode())
    (bundle / "dmg/Token BI_1.2.1_aarch64.dmg").write_bytes(b"dmg fixture")
    return tmp_path


def test_manifest_names_signature_and_checksums_match_assets(release_root):
    output = prepare(release_root)
    manifest = json.loads((output / "latest.json").read_text())
    platform = manifest["platforms"]["darwin-aarch64"]
    assert manifest["version"] == "1.2.1"
    name = platform["url"].rsplit("/", 1)[-1]
    assert (output / name).read_bytes() == b"archive fixture"
    assert platform["signature"] == (output / (name + ".sig")).read_text().strip()
    for line in (output / "SHA256SUMS").read_text().splitlines():
        digest, filename = line.split("  ")
        assert digest == hashlib.sha256((output / filename).read_bytes()).hexdigest()


def test_incomplete_release_is_not_staged(release_root):
    (release_root / "src-tauri/target.noindex/release/bundle/macos/Token BI.app.tar.gz.sig").unlink()
    with pytest.raises(AssertionError, match="Missing artifact"):
        prepare(release_root)
    assert not (release_root / "dist/release-v1.2.1").exists()


def test_inconsistent_versions_are_rejected(release_root):
    (release_root / "package.json").write_text('{"version":"1.2.2"}')
    with pytest.raises(AssertionError, match="Version files disagree"):
        prepare(release_root)
