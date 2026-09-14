"""Stage versioned updater assets and a matching GitHub static manifest."""
from __future__ import annotations

import base64
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def prepare(root: Path = ROOT) -> Path:
    version = json.loads((root / "package.json").read_text())["version"]
    config = json.loads((root / "src-tauri/tauri.conf.json").read_text())
    assert config["version"] == version, "Version files disagree"
    pubkey = base64.b64decode(config["plugins"]["updater"]["pubkey"], validate=True)
    assert b"minisign public key" in pubkey, "Missing updater public key"
    bundle = root / "src-tauri/target.noindex/release/bundle"
    archive = bundle / "macos/Token BI.app.tar.gz"
    signature = Path(str(archive) + ".sig")
    dmg = bundle / f"dmg/Token BI_{version}_aarch64.dmg"
    notes = (root / f"docs/RELEASE_NOTES_v{version}.md").read_text(encoding="utf-8")
    for path in (archive, signature, dmg):
        assert path.is_file() and path.stat().st_size, f"Missing artifact: {path}"
    signature_text = signature.read_text().strip()
    assert b"untrusted comment:" in base64.b64decode(signature_text, validate=True)
    output = root / "dist" / f"release-v{version}"
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    archive_name = f"Token.BI_{version}_aarch64.app.tar.gz"
    for source, name in [(archive, archive_name), (signature, archive_name + ".sig"), (dmg, f"Token.BI_{version}_aarch64.dmg")]:
        shutil.copy2(source, output / name)
    manifest = {
        "version": version,
        "notes": notes,
        "pub_date": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "platforms": {"darwin-aarch64": {
            "url": f"https://github.com/gbs00/Token_BI/releases/download/v{version}/{archive_name}",
            "signature": signature_text,
        }},
    }
    (output / "latest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    checksums = [f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}" for path in sorted(output.iterdir())]
    (output / "SHA256SUMS").write_text("\n".join(checksums) + "\n")
    return output


if __name__ == "__main__":
    print(prepare())
