#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用 Nuitka 把 pz_save_backup_gui.py 编译成单文件 exe

用法：
    python build_nuitka.py              # 正常编译（单文件）
    python build_nuitka.py --onedir     # 编译成文件夹（启动更快）
    python build_nuitka.py --no-test    # 编译后不自动试运行
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCRIPT = "pz_save_backup_gui.py"
APP_NAME = "PZ存档备份工具"
OUT_DIR = "dist_nuitka"

try:
    from PIL import Image  # noqa: F401
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


def ensure(pkg: str, import_name: str | None = None) -> bool:
    name = import_name or pkg
    try:
        __import__(name)
        return True
    except ImportError:
        print(f"📦 正在安装 {pkg} …")
        r = subprocess.run([sys.executable, "-m", "pip", "install", pkg])
        if r.returncode != 0:
            print(f"❌ {pkg} 安装失败")
            return False
        return True


def prepare_icon() -> str | None:
    ico = ROOT / "app_icon.ico"
    if ico.exists():
        print(f"🎨 使用图标：{ico.name}")
        return ico.name
    if not HAS_PIL:
        print("⚠️ 未安装 Pillow，无法生成图标，将使用默认图标")
        return None
    print("🎨 生成图标 app_icon.ico …")
    subprocess.run([sys.executable, str(ROOT / "create_icon.py")], cwd=ROOT, check=True)
    return ico.name if ico.exists() else None


def build(onedir: bool, run_test: bool) -> bool:
    if not ensure("nuitka"):
        return False
    if not (ROOT / SCRIPT).exists():
        print(f"❌ 找不到源文件：{SCRIPT}")
        return False

    icon = prepare_icon()
    out_dir = ROOT / OUT_DIR
    if out_dir.exists():
        shutil.rmtree(out_dir, ignore_errors=True)

    args = [
        sys.executable, "-m", "nuitka",
        "--standalone",
        f"--output-dir={OUT_DIR}",
        f"--output-filename={APP_NAME}.exe",
        "--assume-yes-for-downloads",
        "--windows-console-mode=disable",
        "--enable-plugin=tk-inter",
        "--nofollow-import-to=unittest,pydoc,doctest,test,tkinter.test",
        "--company-name=BlueGary233",
        f"--product-name={APP_NAME}",
        "--file-version=1.0.0",
        "--product-version=1.0.0",
        "--show-progress",
        "--show-memory",
        SCRIPT,
    ]
    if not onedir:
        args.insert(3, "--onefile")   # 单文件 exe（插入在 python -m nuitka 之后）

    if icon:
        args.insert(-1, f"--windows-icon-from-ico={icon}")

    print("=" * 60)
    print("🔨 编译命令：")
    print(" ".join(str(a) for a in args))
    print("=" * 60)

    r = subprocess.run(args, cwd=ROOT)
    if r.returncode != 0:
        print("❌ 编译失败，请查看上方输出")
        return False

    exe = out_dir / f"{APP_NAME}.exe"
    if not exe.exists():
        exe = out_dir / f"{APP_NAME}.dist" / f"{APP_NAME}.exe"
    if not exe.exists():
        print("❌ 未找到输出文件，请检查 dist_nuitka 目录")
        return False

    print(f"\n✅ 编译完成：{exe}（{exe.stat().st_size / 1024 / 1024:.1f} MB）")

    if run_test:
        print("🧪 试运行（会自动弹出程序窗口，请手动关闭）…")
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        subprocess.Popen([str(exe)], cwd=str(exe.parent), creationflags=flags)
    return True


def main():
    ap = argparse.ArgumentParser(description="用 Nuitka 编译 PZ 存档备份工具")
    ap.add_argument("--onedir", action="store_true", help="编译成文件夹而不是单文件")
    ap.add_argument("--no-test", action="store_true", help="编译完不自动试运行")
    a = ap.parse_args()

    print(f"🐍 Python：{sys.version.split()[0]}  ({sys.executable})")
    print(f"📁 工作目录：{ROOT}")
    ok = build(a.onedir, run_test=not a.no_test)
    if ok:
        print(f"\n🎉 完成！可执行文件在 {ROOT / OUT_DIR}")
        print("   config.json 会生成在 exe 同目录（存档路径、间隔等设置都记在里面）")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
