# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


project_root = Path(SPECPATH)
excluded = ["playwright", "greenlet", "httpx._main", "pygments"]

backend = Analysis(
    ["app/cli.py"],
    pathex=[str(project_root)],
    datas=[
        (str(project_root / "app/templates"), "app/templates"),
        (str(project_root / "app/static"), "app/static"),
    ],
    hiddenimports=collect_submodules("app") + collect_submodules("uvicorn"),
    excludes=[*excluded, "uvloop", "watchfiles"],
    optimize=0,
)
control = Analysis(
    ["scripts/control_cli.py"],
    pathex=[str(project_root)],
    hiddenimports=["qrcode.image.svg"],
    excludes=[*excluded, "pydantic", "starlette", "uvicorn"],
    optimize=0,
)

# 两个入口保留独立模块归档，控制服务不预加载额度服务；公共动态库只收集一次。
backend_exe = EXE(
    PYZ(backend.pure), backend.scripts, [],
    name="token-bi-backend", exclude_binaries=True, console=True, upx=False,
)
control_exe = EXE(
    PYZ(control.pure), control.scripts, [],
    name="token-bi-control", exclude_binaries=True, console=True, upx=False,
)
COLLECT(
    backend_exe, control_exe,
    backend.binaries, control.binaries,
    backend.datas, control.datas,
    name="token-bi-runtime", upx=False,
)
