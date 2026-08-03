# -*- mode: python ; coding: utf-8 -*-

import importlib.util
import sys
from pathlib import Path
import shutil

from PyInstaller.utils.hooks import collect_all

# ============================================================
# 基础配置
# ============================================================

datas = [
    ("template", "template"),
]

binaries = []
hiddenimports = []

NAME = "月饼的三角洲通用脚本v1.2.24-开源版"

# ============================================================
# 1. Cython
# 解决 Cython/Utility/CppSupport.cpp 缺失
# ============================================================

cython_datas, cython_binaries, cython_hiddenimports = collect_all("Cython")

datas.extend(cython_datas)
binaries.extend(cython_binaries)
hiddenimports.extend(cython_hiddenimports)


# ============================================================
# 2. PaddleOCR
# 解决 paddleocr/tools/__init__.py 等源码文件缺失
# ============================================================

paddleocr_datas, paddleocr_binaries, paddleocr_hiddenimports = collect_all(
    "paddleocr",
    include_py_files=True,
)

datas.extend(paddleocr_datas)
binaries.extend(paddleocr_binaries)
hiddenimports.extend(paddleocr_hiddenimports)

# ============================================================
# Paddle MKL DLL
# ============================================================

paddle_spec = importlib.util.find_spec("paddle")

if paddle_spec is None:
    raise ModuleNotFoundError("当前环境中未找到 paddle")

paddle_dir = Path(
    next(iter(paddle_spec.submodule_search_locations))
).resolve()

mklml_path = paddle_dir / "libs" / "mklml.dll"

if not mklml_path.exists():
    raise FileNotFoundError(f"未找到 Paddle MKL 动态库: {mklml_path}")

binaries.append(
    (
        str(mklml_path),
        "paddle/libs",
    )
)

# ============================================================
# 3. requests
# ============================================================

requests_datas, requests_binaries, requests_hiddenimports = collect_all("requests")

datas.extend(requests_datas)
binaries.extend(requests_binaries)
hiddenimports.extend(requests_hiddenimports)


# ============================================================
# 4. urllib3
# ============================================================

urllib3_datas, urllib3_binaries, urllib3_hiddenimports = collect_all("urllib3")

datas.extend(urllib3_datas)
binaries.extend(urllib3_binaries)
hiddenimports.extend(urllib3_hiddenimports)


# ============================================================
# 5. Shapely
# ============================================================

shapely_datas, shapely_binaries, shapely_hiddenimports = collect_all("shapely")

datas.extend(shapely_datas)
binaries.extend(shapely_binaries)
hiddenimports.extend(shapely_hiddenimports)


# ============================================================
# 6. 收集 pip 安装的 Shapely 外部 DLL
# DLL 一般位于 site-packages/shapely.libs
# ============================================================

shapely_spec = importlib.util.find_spec("shapely")

if shapely_spec is not None and shapely_spec.submodule_search_locations:
    shapely_dir = Path(
        next(iter(shapely_spec.submodule_search_locations))
    )

    shapely_libs_dir = shapely_dir.parent / "shapely.libs"

    if shapely_libs_dir.exists():
        for dll_path in shapely_libs_dir.rglob("*.dll"):
            relative_parent = dll_path.relative_to(
                shapely_libs_dir
            ).parent

            target_dir = Path("shapely.libs") / relative_parent

            binaries.append(
                (str(dll_path), str(target_dir))
            )


# ============================================================
# 7. 收集 Conda 环境中的 GEOS DLL
# 一般位于虚拟环境的 Library/bin
# ============================================================

conda_bin_dir = Path(sys.prefix) / "Library" / "bin"

if conda_bin_dir.exists():
    for pattern in (
        "geos*.dll",
        "libgeos*.dll",
    ):
        for dll_path in conda_bin_dir.glob(pattern):
            binaries.append(
                (str(dll_path), ".")
            )


# 去重
datas = list(dict.fromkeys(datas))
binaries = list(dict.fromkeys(binaries))
hiddenimports = list(dict.fromkeys(hiddenimports))


a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=NAME,
    uac_admin=True,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=NAME,
)

# 将项目目录下的 inference 复制到 EXE 同级目录
source_inference = Path(SPECPATH) / "inference"
target_inference = Path(DISTPATH) / NAME / "inference"

if not source_inference.is_dir():
    raise FileNotFoundError(
        f"找不到 inference 目录：{source_inference}"
    )

if target_inference.exists():
    shutil.rmtree(target_inference)

shutil.copytree(
    source_inference,
    target_inference,
)

# 删除不使用的 OpenCV FFmpeg 视频后端
app_dir = Path(DISTPATH) / NAME

for dll_name in (
    "opencv_videoio_ffmpeg500_64.dll",
    "opencv_videoio_ffmpeg4110_64.dll",
):
    for dll_path in app_dir.rglob(dll_name):
        dll_path.unlink()
        print(f"已删除无用 DLL: {dll_path}")