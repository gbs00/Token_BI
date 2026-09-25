"""构建隔离的 WKWebView 可行性验证包，不改写正式 Token BI。"""
from __future__ import annotations

import argparse
import hashlib
import plistlib
import shutil
import subprocess
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dmg", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    directory = root / "dist" / "wkwebview-probe"
    bundle = directory / "Token BI Web Probe.app"
    contents = bundle / "Contents"
    executable = contents / "MacOS" / "TokenBIWebProbe"
    resources = contents / "Resources"
    executable.parent.mkdir(parents=True, exist_ok=True)
    resources.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "xcrun", "swiftc", "-O", "-swift-version", "5", "-warnings-as-errors",
        "-target", "arm64-apple-macos11.0", "-framework", "AppKit", "-framework", "WebKit",
        str(root / "scripts/wkwebview_probe/Probe.swift"),
        str(root / "scripts/wkwebview_probe/Diagnostics.swift"), "-o", str(executable),
    ], check=True)
    shutil.copy2(root / "native/web-session/collect.js", resources / "collect.js")
    shutil.copy2(root / "scripts/wkwebview_probe/diagnostics.js", resources / "diagnostics.js")
    shutil.copy2(root / "src-tauri/icons/icon.icns", resources / "icon.icns")
    with (contents / "Info.plist").open("wb") as stream:
        plistlib.dump({
            "CFBundleIdentifier": "com.gbs00.tokenbi.wkwebview-probe",
            "CFBundleName": "Token BI Web Probe",
            "CFBundleDisplayName": "Token BI Web Probe",
            "CFBundleExecutable": executable.name,
            "CFBundlePackageType": "APPL",
            "CFBundleShortVersionString": "0.1.3",
            "CFBundleVersion": "20260925.4",
            "CFBundleIconFile": "icon.icns",
            "LSMinimumSystemVersion": "11.0",
            "NSHighResolutionCapable": True,
            "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
        }, stream)
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(bundle)], check=True)
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(bundle)], check=True)
    print(bundle)
    if args.dmg:
        staging = directory / "dmg-root.noindex"
        staging.mkdir(exist_ok=True)
        shutil.copytree(bundle, staging / bundle.name, dirs_exist_ok=True)
        shortcut = staging / "Applications"
        if not shortcut.exists():
            shortcut.symlink_to("/Applications", target_is_directory=True)
        target = directory / "Token-BI-WKWebView-Probe-20260925.4-arm64.dmg"
        subprocess.run(["hdiutil", "create", "-ov", "-volname", "Token BI WKWebView Probe",
                        "-srcfolder", str(staging), "-format", "UDZO", str(target)], check=True)
        subprocess.run(["hdiutil", "verify", str(target)], check=True)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        target.with_suffix(".dmg.sha256").write_text(f"{digest}  {target.name}\n", encoding="ascii")
        print(target)
        print(f"SHA-256: {digest}")


if __name__ == "__main__":
    main()
