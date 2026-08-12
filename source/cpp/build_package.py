#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compile and package the sp_tools plug-in.

Layout:
    sp_tools/
      source/__init__.py   plug-in entry
      source/cpp/          C++ delegate sources + build_package.py
      source/native/       built binaries
      sdks/                bundled Qt SDKs
      dist/sp_tools.zip    release archive

One-click build (run from the plug-in root):
    python source/cpp/build_package.py

Always compiles ``sp_layer_tools_delegate_qt6.dll`` (Painter 10.1+ / Qt6) and
``sp_layer_tools_delegate_qt5.dll`` (Painter 7.2-10.0 / Qt5) before creating
the ZIP; a compile failure stops packaging.

The ZIP root is the plug-in content. Install by extracting into a folder
named ``sp_tools`` under Documents/Adobe/Adobe Substance 3D Painter/python/plugins.
"""

import ast
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "source"
CPP_SRC = SRC / "cpp"
CPP_BUILD = CPP_SRC / "build"
DIST = ROOT / "dist"
OUT = DIST / "sp_tools.zip"
README = ROOT / "README.md"
NATIVE_DIR = SRC / "native"
DELEGATE_QT6_DLL = CPP_BUILD / "Release" / "sp_layer_tools_delegate_qt6.dll"
DELEGATE_QT5_DLL = CPP_BUILD / "Release" / "sp_layer_tools_delegate_qt5.dll"


def _check_required_files() -> None:
    required = [
        SRC / "__init__.py",
        README,
        CPP_SRC / "CMakeLists.txt",
        CPP_SRC / "sp_tools_delegate.cpp",
        ROOT / "sdks" / "qt" / "6.5.3" / "msvc2019_64" / "lib" / "Qt6Core.lib",
        ROOT / "sdks" / "qt" / "6.5.3" / "msvc2019_64" / "lib" / "Qt6Gui.lib",
        ROOT / "sdks" / "qt" / "6.5.3" / "msvc2019_64" / "lib" / "Qt6Widgets.lib",
        ROOT / "sdks" / "qt" / "5.12.5" / "msvc2017_64" / "lib" / "Qt5Core.lib",
        ROOT / "sdks" / "qt" / "5.12.5" / "msvc2017_64" / "lib" / "Qt5Gui.lib",
        ROOT / "sdks" / "qt" / "5.12.5" / "msvc2017_64" / "lib" / "Qt5Widgets.lib",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        print("缺少必要文件:")
        for path in missing:
            print("  -", path)
        sys.exit(1)


def _validate_sources() -> None:
    """打包前校验插件源码，且拒绝 Python 3.8+ 语法（旧版 Painter 是 3.7）。"""
    source = SRC / "__init__.py"
    text = source.read_text(encoding="utf-8")
    compile(text, str(source), "exec")
    try:
        ast.parse(text, filename=str(source), feature_version=(3, 7))
    except TypeError:
        # Python 3.7 本身没有 feature_version 参数；退化为普通语法检查。
        ast.parse(text, filename=str(source))


def _build_native() -> None:
    cmake = shutil.which("cmake")
    if cmake is None:
        raise RuntimeError("未找到 CMake，请先安装 CMake 并加入 PATH。")
    print("配置 C++ 原生模块……")
    subprocess.run(
        [cmake, "-S", str(CPP_SRC), "-B", str(CPP_BUILD)],
        check=True,
    )
    print("编译 C++ 原生模块（Release）……")
    subprocess.run(
        [cmake, "--build", str(CPP_BUILD), "--config", "Release"],
        check=True,
    )
    missing = [path for path in (DELEGATE_QT6_DLL, DELEGATE_QT5_DLL)
               if not path.is_file()]
    if missing:
        raise RuntimeError(f"编译完成但缺少产物：{missing}")

    if NATIVE_DIR.is_dir():
        for stale in list(NATIVE_DIR.iterdir()):
            if stale.suffix.lower() in (".dll", ".old"):
                stale.unlink(missing_ok=True)
    NATIVE_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(DELEGATE_QT6_DLL, NATIVE_DIR / "sp_layer_tools_delegate_qt6.dll")
    shutil.copy2(DELEGATE_QT5_DLL, NATIVE_DIR / "sp_layer_tools_delegate_qt5.dll")
    print("已更新 Qt6 图层工具模块:", NATIVE_DIR / "sp_layer_tools_delegate_qt6.dll")
    print("已更新 Qt5 图层工具模块:", NATIVE_DIR / "sp_layer_tools_delegate_qt5.dll")


def _create_archive() -> None:
    DIST.mkdir(parents=True, exist_ok=True)
    OUT.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix="sp_tools_pkg_") as tmp:
        pkg = Path(tmp) / "sp_tools"
        pkg.mkdir()
        shutil.copy2(SRC / "__init__.py", pkg / "__init__.py")
        shutil.copy2(README, pkg / "README.md")
        shutil.copytree(NATIVE_DIR, pkg / "native")

        file_count = 0
        with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(pkg.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(pkg).as_posix())
                    file_count += 1

    with zipfile.ZipFile(OUT, "r") as archive:
        names = archive.namelist()
        required = {
            "__init__.py",
            "README.md",
            "native/sp_layer_tools_delegate_qt5.dll",
            "native/sp_layer_tools_delegate_qt6.dll",
        }
        missing = required.difference(names)
        if missing:
            OUT.unlink(missing_ok=True)
            raise RuntimeError(f"发布包缺少必要文件: {sorted(missing)}")
        if any("__pycache__" in name or name.endswith(".pyc")
               for name in names):
            OUT.unlink(missing_ok=True)
            raise RuntimeError("发布包包含 Python 缓存文件")
        if any(name.endswith((".dll.old", ".exe.old")) for name in names):
            OUT.unlink(missing_ok=True)
            raise RuntimeError("发布包包含更新残留文件")

    size_mb = OUT.stat().st_size / (1024 * 1024)
    print(f"已生成 {OUT}  ({file_count} 个文件, {size_mb:.2f} MB)")


def main() -> None:
    # 失败的打包不得留下看起来是新的旧包。
    OUT.unlink(missing_ok=True)
    _check_required_files()
    _validate_sources()
    _build_native()
    _create_archive()


if __name__ == "__main__":
    main()
