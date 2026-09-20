"""清理项目内的过期产物；默认只预览，不操作已安装 App 的数据。"""
from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil


ROOT = Path(__file__).resolve().parents[1]
KEEP_BACKUPS = 2
KEEP_RELEASES = 2
ORPHAN_DAYS = 30


def within(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def process_paths() -> set[Path]:
    paths = set()
    for process in psutil.process_iter():
        try:
            if process.uids().real != os.getuid():
                continue
            values = [process.exe(), process.cwd(), *process.cmdline()]
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied as exc:
            raise RuntimeError("无法确认进程占用，停止清理。") from exc
        try:
            values.extend(item.path for item in process.open_files())
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            # macOS 可限制文件句柄枚举；已读取的可执行路径、工作目录和 profile 参数仍参与保护。
            pass
        for value in values:
            value = value.split("=", 1)[1] if value.startswith("--user-data-dir=") else value
            if value.startswith("/"):
                paths.add(Path(value).resolve())
    return paths


def profile_references(data_roots: list[Path]) -> set[Path]:
    references = set()
    for root in data_roots:
        accounts = root / "config/accounts.json"
        if not accounts.exists():
            continue
        payload = json.loads(accounts.read_text(encoding="utf-8"))
        for account in payload["accounts"]:
            account_id = account["account_id"]
            if not re.fullmatch(r"acc_[A-Za-z0-9_]+", account_id):
                raise ValueError("账号标识无效，停止清理。")
            context = root / "runtime/contexts" / account_id
            references.update((context.resolve(), context.with_name(account_id + "-cdp").resolve()))
            if account.get("session_storage_path"):
                references.add(Path(account["session_storage_path"]).expanduser().resolve())
    return references


def tree_stats(path: Path) -> tuple[int, float]:
    size, modified = 0, path.lstat().st_mtime
    for directory, dirs, files in os.walk(path, followlinks=False):
        for name in dirs + files:
            item = Path(directory) / name
            stat = item.lstat()
            modified = max(modified, stat.st_mtime)
            if not item.is_symlink() and item.is_file():
                size += stat.st_size
    return size, modified


def plan_cleanup(root: Path, protected_data: list[Path], busy: set[Path], now: float) -> list[dict]:
    root = root.resolve()
    references = profile_references([root, *protected_data])
    candidates: list[tuple[Path, str]] = []
    contexts = root / "runtime/contexts"
    if (root / "config/accounts.json").is_file() and contexts.is_dir():
        for path in contexts.iterdir():
            if re.fullmatch(r"acc_[A-Za-z0-9_]+(?:-cdp)?", path.name):
                if not any(within(ref, path) or within(path, ref) for ref in references):
                    candidates.append((path, "orphan_profile"))

    retired_target = root / "src-tauri/target"
    if (retired_target / ".rustc_info.json").is_file():
        candidates.append((retired_target, "retired_rust_target"))

    dist = root / "dist"
    backups = []
    releases = []
    if dist.is_dir():
        for path in dist.iterdir():
            if path.is_symlink() or not path.is_dir():
                continue
            if path.name.startswith("Token BI-") and path.name.endswith(".noindex"):
                info = path / "Contents/Info.plist"
                if info.is_file() and plistlib.loads(info.read_bytes()).get("CFBundleIdentifier") == "com.gbs00.tokenbi":
                    backups.append(path)
            match = re.fullmatch(r"release-v(\d+)\.(\d+)\.(\d+)", path.name)
            if match:
                releases.append((tuple(map(int, match.groups())), path))
    backups.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    candidates.extend((path, "old_app_backup") for path in backups[KEEP_BACKUPS:])
    candidates.extend((path, "old_release") for _, path in sorted(releases, reverse=True)[KEEP_RELEASES:])

    plan = []
    for path, reason in candidates:
        # 只接受项目内部的实体目录，拒绝父级或目标被链接重定向的路径。
        if not path.is_dir() or path.is_symlink() or path.resolve() != path or not within(path, root):
            continue
        if any(within(ref, path) for ref in busy):
            continue
        size, modified = tree_stats(path)
        if reason == "orphan_profile" and now - modified < ORPHAN_DAYS * 86400:
            continue
        stat = path.stat()
        plan.append({"path": str(path), "reason": reason, "bytes": size,
                     "device": stat.st_dev, "inode": stat.st_ino})
    return plan


def apply_cleanup(root: Path, protected_data: list[Path], reviewed: list[dict]) -> list[dict]:
    # 删除前重新检查账号引用和占用，清单变化时不继续删除该项。
    fresh = {entry["path"]: entry for entry in plan_cleanup(root, protected_data, process_paths(), time.time())}
    removed = []
    for entry in reviewed:
        if fresh.get(entry["path"]) != entry:
            raise RuntimeError(f"清理目标已变化，停止：{entry['path']}")
        path = Path(entry["path"])
        stat = path.lstat()
        if path.is_symlink() or (stat.st_dev, stat.st_ino) != (entry["device"], entry["inode"]):
            raise RuntimeError(f"清理目标已替换，停止：{path}")
        shutil.rmtree(path)
        removed.append(entry)
        print(f"已清理：{path.relative_to(root)}", flush=True)
    return removed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="执行清理；不指定时只预览")
    args = parser.parse_args()
    protected = [Path.home() / "Library/Application Support/Token BI"]
    override = os.getenv("TOKEN_BI_APP_DATA_DIR")
    if override:
        protected.append(Path(override).expanduser().resolve())
    plan = plan_cleanup(ROOT, protected, process_paths(), time.time())
    print(json.dumps({"mode": "apply" if args.apply else "preview", "candidates": plan,
                      "bytes": sum(entry["bytes"] for entry in plan)}, ensure_ascii=False, indent=2), flush=True)
    if args.apply:
        report_dir = ROOT / "dist/cleanup-reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        report = report_dir / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".json")
        report.write_text(json.dumps({"planned": plan}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        removed = apply_cleanup(ROOT, protected, plan)
        report.write_text(json.dumps({"planned": plan, "removed": removed}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"清理记录：{report}")


if __name__ == "__main__":
    main()
