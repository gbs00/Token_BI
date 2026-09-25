"""构建按需运行的 WKWebView 登录组件，不包含浏览器引擎或 Node。"""
from __future__ import annotations

import json
import plistlib
import shutil
import subprocess
from pathlib import Path


def build(root: Path) -> Path:
    bundle = root / "dist/native/Token BI Web Session.app"
    contents = bundle / "Contents"
    executable = contents / "MacOS/TokenBIWebSession"
    resources = contents / "Resources"
    executable.parent.mkdir(parents=True, exist_ok=True)
    resources.mkdir(parents=True, exist_ok=True)
    source = root / "native/web-session"
    subprocess.run(["xcrun", "swiftc", "-O", "-swift-version", "5", "-warnings-as-errors",
                    "-target", "arm64-apple-macos11.0", "-framework", "AppKit", "-framework", "WebKit", "-framework", "Network",
                    str(source / "NavigationPolicy.swift"), str(source / "Session.swift"),
                    "-o", str(executable)], check=True)
    shutil.copy2(source / "collect.js", resources / "collect.js")
    shutil.copy2(root / "src-tauri/icons/icon.icns", resources / "icon.icns")
    version = json.loads((root / "package.json").read_text())["version"]
    with (contents / "Info.plist").open("wb") as stream:
        plistlib.dump({"CFBundleIdentifier": "com.gbs00.tokenbi.web-session",
                      "CFBundleName": "Token BI Web Session", "CFBundleExecutable": executable.name,
                      "CFBundlePackageType": "APPL", "CFBundleShortVersionString": version,
                      "CFBundleVersion": version, "CFBundleIconFile": "icon.icns",
                      "LSMinimumSystemVersion": "11.0", "LSUIElement": True,
                      "NSHighResolutionCapable": True,
                      "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True}}, stream)
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(bundle)], check=True)
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(bundle)], check=True)
    return bundle


if __name__ == "__main__":
    print(build(Path(__file__).resolve().parents[1]))
