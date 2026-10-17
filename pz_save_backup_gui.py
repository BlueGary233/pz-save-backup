#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
僵尸毁灭工程 (Project Zomboid) 存档自动备份工具

功能
----
* 可配置间隔的定时自动备份（后台线程，界面不卡）
* 存档列表可选择（多选）、可重命名存档目录
* 备份文件命名：<存档名>_YYYYMMDD_HHMMSS.zip（可直接解压回存档根目录恢复）
* 存档根目录 **不硬编码**：自动探测 + 界面任意修改 + config.json 持久化
* 每个存档可保留最近 N 份，自动清理旧备份
* 检测游戏是否正在运行（写入中的存档可能不完整，仅提示不阻止）

命令行
------
    python pz_save_backup_gui.py            启动图形界面
    python pz_save_backup_gui.py --selftest 在临时目录跑一遍核心备份逻辑（自检）
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog

APP_TITLE = "PZ 存档备份工具"
APP_VERSION = "1.0.0"
CONFIG_NAME = "config.json"
CONFIG_DIR_NAME = "PZSaveBackup"      # 文档目录下的配置文件夹名

# --------------------------------------------------------------------------- #
# 多语言（中 / 英）
# --------------------------------------------------------------------------- #
LANG = "zh"          # 当前界面语言：zh / en


def set_lang(code: str):
    global LANG
    LANG = "en" if str(code).lower().startswith("en") else "zh"


def tr(text: str, *args) -> str:
    """取当前语言的文案。中文直接用原文；英文查 EN 表，查不到就回退中文。

    带变量的句子统一写成模板（位置参数），例如：
        tr("已备份 {0} 份", n)
    """
    s = text if LANG == "zh" else EN.get(text, text)
    if args:
        try:
            return s.format(*args)
        except (IndexError, KeyError, ValueError):
            return s
    return s


EN = {
    # ---- 标题 / 页签 / 页头 ----
    "PZ 存档备份": "PZ Save Backup",
    "备份": "Backups",
    "高级": "Advanced",
    "自动备份：已停止": "Auto backup: stopped",
    "自动备份：运行中 · 每 {0} 分钟": "Auto backup: running · every {0} min",

    # ---- 主界面 ----
    "存档目录": "Save folder",
    "选择": "Choose",
    "探测": "Detect",
    "存档（默认全部监控）": "Saves (all monitored by default)",
    "存档名": "Save name",
    "备份数": "Backups",
    "大小": "Size",
    "备份（先选一个存档）": "Backups (pick a save first)",
    "备份文件夹": "Backup folder",
    "时间": "Time",
    "自动备份": "Auto backup",
    "每": "Every",
    "分钟检测一次": "min, check once",
    "有变化才备份，没变化跳过": "only back up when changed",
    "▶ 开始自动备份": "▶ Start auto backup",
    "■ 停止自动备份": "■ Stop auto backup",
    "⏱ 立即备份": "⏱ Back up now",
    "存档操作": "Save actions",
    "重命名": "Rename",
    "删除": "Delete",
    "自动备份：未开启": "Auto backup: off",
    "正在等存档静止，然后备份…": "Waiting for the save to go idle…",
    "下次备份 {0}（剩 {1}:{2}）": "Next backup {0} (in {1}:{2})",
    "存档已静止 {0} 秒，可以安全备份": "Save idle for {0}s — safe to back up",
    "⚠ 正在写入（{0}，{1} 秒前），暂不备份": "⚠ Writing now ({0}, {1}s ago) — holding off",

    # ---- 高级页 ----
    "备份目录": "Backup folder",
    "同目录": "Same folder",
    "自定义": "Custom",
    "更改": "Change",
    "打开": "Open",
    "默认": "Default",
    "每个存档保留": "Keep per save",
    "份（0=不清理）": "copies (0 = keep all)",
    "开启即备份一次": "Back up once on start",
    "仅在存档静止时备份（防复制坏档）": "Only back up when the save is idle (prevents corrupt copies)",
    "静止": "Idle for",
    "秒以上才动它": "s or more",
    "存档没变就跳过（不重复备份）": "Skip unchanged saves",
    "全部监控": "Monitor all",
    "全部排除": "Exclude all",
    "重命名存档": "Rename save",
    "删除存档": "Delete save",
    "打开存档目录": "Open save folder",
    "刷新": "Refresh",
    "备份记录": "Backup history",
    "删除选中": "Delete selected",
    "重命名选中": "Rename selected",
    "备份时间": "Backed up at",
    "日志": "Log",

    # ---- 菜单 ----
    "重命名存档…": "Rename save…",
    "删除存档…": "Delete save…",
    "监控 / 不监控这个存档": "Monitor / don't monitor this save",
    "打开存档文件夹": "Open save folder",
    "刷新列表": "Refresh list",
    "在资源管理器中打开": "Show in Explorer",
    "重命名备份…": "Rename backup…",
    "删除备份…": "Delete backup…",

    # ---- 对话框 ----
    "请先在列表里点选一个存档（高亮那一行）。": "Select one save in the list first (the highlighted row).",
    "把存档「{0}」重命名为：": "Rename save \"{0}\" to:",
    "存档名不能为空": "Save name cannot be empty",
    "存档名不能包含 \\ / : * ? \" < > | 这些字符": "Save name cannot contain \\ / : * ? \" < > |",
    "存档名不能以句点结尾": "Save name cannot end with a dot",
    "{0} 是 Windows 保留名，请换一个": "{0} is a reserved Windows name, please pick another",
    "已存在同名存档：{0}": "A save with that name already exists: {0}",
    "重命名失败：{0}\n（如果游戏正在运行，请先退出游戏再试）":
        "Rename failed: {0}\n(if the game is running, quit it first and retry)",
    "把存档「{0}」（{1}）移入回收站？\n\n存档会进回收站，之后仍可从回收站还原。\n要是还想留着它，建议先点「立即备份」。":
        "Move save \"{0}\" ({1}) to the Recycle Bin?\n\nIt goes to the Recycle Bin and can be restored later.\nIf you might still want it, click \"Back up now\" first.",
    "删除失败：{0}\n（如果游戏正在运行，请先退出游戏再试）":
        "Delete failed: {0}\n(if the game is running, quit it first and retry)",
    "请选择且只选择一份备份。": "Select exactly one backup.",
    "名字不符合 <存档名>_时间戳 规则，无法自动改名。":
        "This name doesn't match the <save>_<timestamp> pattern, so it can't be renamed automatically.",
    "把这份备份归属的存档名改为：": "Change the save name this backup belongs to:",
    "把选中的 {0} 份备份移入回收站？\n（之后仍可从回收站还原）":
        "Move the {0} selected backup(s) to the Recycle Bin?\n(they can be restored later)",
    "重命名失败：{0}": "Rename failed: {0}",
    "请先设置有效的存档目录。": "Please set a valid save folder first.",
    "间隔必须是数字（分钟）。": "The interval must be a number (minutes).",
    "未能自动探测到存档目录：{0}\n请手动选择。":
        "Could not auto-detect the save folder: {0}\nPlease pick it manually.",
    "选择的目录不存在。": "The selected folder doesn't exist.",
    "选择存档目录（Zomboid / Saves / 具体存档类型目录都行）":
        "Choose the save folder (Zomboid / Saves / a specific save-type folder all work)",
    "选择备份存放目录（默认与原存档同一个文件夹）":
        "Choose where backups go (default: the same folder as the save)",

    # ---- 日志 ----
    "配置文件：{0}": "Config file: {0}",
    "就绪。备份目录：{0}": "Ready. Backup folder: {0}",
    "备份位置：与原存档同目录（{0}）": "Backup location: same folder as the save ({0})",
    "备份位置：自定义目录 {0}": "Backup location: custom folder {0}",
    "自动探测存档目录：{0}（{1}）": "Save folder auto-detected: {0} ({1})",
    "自动探测到存档目录：{0}（{1}）": "Save folder detected: {0} ({1})",
    "自动探测失败：{0}": "Auto-detect failed: {0}",
    "未找到，请手动指定存档目录": "not found — please pick the save folder manually",
    "依据 {0} 定位": "located via {0}",
    "存档目录已更改为：{0}": "Save folder changed to: {0}",
    "备份目录已更改为自定义位置：{0}": "Backup folder changed to a custom location: {0}",
    "备份位置已切回同目录模式：{0}": "Backup location switched back to the save folder: {0}",
    "已开启自动备份：每 {0} 分钟检查一次所有存档，有变化才备份":
        "Auto backup on: checks every {0} min, backs up only changed saves",
    "（现在先检查一次）": " (checking once now)",
    "自动备份已停止": "Auto backup stopped",
    "── {0}检查：{1} 个存档": "── {0} check: {1} save(s)",
    "定时": "Scheduled",
    "手动": "Manual",
    "· {0} 正在被写入（{1} 秒前刚写过），本轮不备份（需要静止 {2} 秒）":
        "· {0} is being written ({1}s ago) — skipping (needs {2}s idle)",
    "· {0} 没有变化，跳过（上次备份 {1}）": "· {0} unchanged, skipped (last backup {1})",
    "✔ {0} → {1}（{2}，{3}s）": "✔ {0} → {1} ({2}, {3}s)",
    "⚠ {0} 备份途中被游戏写入，这次备份已作废并删除（等它安静下来会自动重做）":
        "⚠ {0} was written to during the copy — this backup was discarded (it will retry once idle)",
    "✘ {0} 备份失败：{1}": "✘ {0} backup failed: {1}",
    "  清理旧备份 {0} 份（保留最近 {1} 份）": "  removed {0} old backup(s), keeping the latest {1}",
    "── {0}备份结束：成功 {1}，失败 {2}{3}": "── {0} backup done: {1} ok, {2} failed{3}",
    "，{0} 个没变化": ", {0} unchanged",
    "，{0} 个正在写入没碰": ", {0} being written (skipped)",
    "，{0} 个备份途中被写入已作废": ", {0} discarded (written during copy)",
    "· 等了 {0} 秒存档还在写，本轮不备份了（下轮再试）":
        "· Waited {0}s but the save is still being written — skipping this round",
    "── {0}备份结束：成功 0，失败 0，没等到存档静止":
        "── {0} backup done: 0 ok, 0 failed (never went idle)",
    "── {0}备份已取消（自动备份被停止）": "── {0} backup cancelled (auto backup stopped)",
    "等待存档静止：{0}（{1} 秒前刚写过）…": "Waiting for {0} to go idle ({1}s ago)…",
    "上一次备份还在进行中，本次跳过": "A backup is already running — skipped this time",
    "存档目录无效，无法备份": "Invalid save folder — cannot back up",
    "备份目录未设置，无法备份": "No backup folder set — cannot back up",
    "存档目录里还没有存档，无法备份": "There are no saves in that folder yet",
    "没有勾选任何存档，已自动改为监控全部（{0} 个）":
        "Nothing was monitored — switched to monitoring all ({0})",
    "发现一个被继续玩的备份存档：{0}（已自动勾选，会一起备份）":
        "Found a backup that is being played: {0} (now monitored and backed up too)",
    "⚠ 游戏最近加载的存档「{0}」不在存档目录里（被改名或删除了？）":
        "⚠ The save the game loaded last, \"{0}\", is not in the folder (renamed or deleted?)",
    "存档已重命名：{0} → {1}": "Save renamed: {0} → {1}",
    "  {0} 份备份也跟着改名了（{1} → {2}）": "  renamed {0} backup(s) too ({1} → {2})",
    "  ⚠ 有 {0} 份备份改名失败，可在备份区右键手动改名":
        "  ⚠ {0} backup(s) could not be renamed — rename them manually in the backups pane",
    "存档已移入回收站：{0}（可从回收站还原）": "Save moved to the Recycle Bin: {0} (restorable)",
    "已把 {0} 份备份移入回收站": "Moved {0} backup(s) to the Recycle Bin",
    "备份已重命名：{0} → {1}": "Backup renamed: {0} → {1}",
    "⚠ 保留清理跳过 {0}：它正被当成存档使用，不能当旧备份删":
        "⚠ Retain cleanup skipped {0}: it is being used as a save, not an old backup",
    "⚠ 无法删除旧备份 {0}：{1}": "⚠ Could not delete old backup {0}: {1}",
    "⚠ 删除失败 {0}：{1}": "⚠ Delete failed for {0}: {1}",
    "⚠ 备份改名失败 {0}：{1}": "⚠ Backup rename failed for {0}: {1}",
    "读取存档目录失败：{0}": "Failed to read the save folder: {0}",
    "配置保存失败（{0}）：{1}": "Failed to save config ({0}): {1}",
    "存档目录：{0}": "Save folder: {0}",
    "状态：备份中…": "Status: backing up…",
    "存档：监控 {0}/{1} 个 · {2}": "Saves: monitoring {0}/{1} · {2}",
    " · 橙色=在玩的备份": " · orange = a backup being played",
    "（未设置）": "(not set)",
    "未设置": "not set",
    "未设置存档目录": "No save folder set",
    "（还没有备份）": "(no backups yet)",
    "份": "",
    # ---- 补充（动态片段 / 命令行）----
    "PZ 存档备份工具": "PZ Save Backup",
    "界面语言已切换：{0}": "UI language switched to {0}",
    "{0}：{1} 份备份": "{0}: {1} backup(s)",
    "{0} 份备份": "{0} backup(s)",
    "{0} 份 · {1}": "{0} backup(s) · {1}",
    "[{0}/{1}] {2}：{3}/{4} 个文件（{5}/{6}）": "[{0}/{1}] {2}: {3}/{4} files ({5}/{6})",
    "[{0}/{1}] 检查 {2} 有没有变化 …": "[{0}/{1}] checking {2} for changes…",
    "[{0}/{1}] 正在备份 {2} …": "[{0}/{1}] backing up {2}…",
    "· {0} 不存在了，跳过": "· {0} no longer exists, skipped",
    "存档目录不存在：{0}": "Save folder not found: {0}",
    "文件被占用/无法读取：{0}（{1}）": "File is locked/unreadable: {0} ({1})",
    "复制校验失败：应有 {0} 个文件，实际 {1} 个":
        "Copy verification failed: expected {0} file(s), got {1}",
    "已存在同名备份：{0}": "A backup with that name already exists: {0}",
    "移入回收站失败（代码 {0}）": "Failed to move to the Recycle Bin (code {0})",
    "移入回收站失败：路径仍然存在": "Failed to move to the Recycle Bin: the path still exists",
    "非 Windows 平台不支持回收站删除": "Recycle Bin delete is only supported on Windows",
}


WIN = os.name == "nt"

# 单个文件复制失败时的重试次数（游戏写文件的瞬间占用通常是毫秒级，重试基本能救回来）
COPY_RETRIES = 3          # 加上首次尝试，每个文件最多试 4 次

# 存档“安静”多久才算可以安全备份（游戏写档期间复制会把存档复制坏）
DEFAULT_IDLE_SECONDS = 5

# 定时到点后，最多等这么久让存档安静下来（等不到就放弃本轮，下轮再试）
IDLE_WAIT_SECONDS = 180

# 备份目录里若出现比“备份时间戳”晚这么多的文件，就说明这个备份已经被当成存档继续玩过了
BACKUP_TOUCH_TOLERANCE = 60      # 秒


class SaveChangedDuringBackup(RuntimeError):
    """备份过程中源存档被写入 → 这次备份作废（避免产出半新半旧的坏备份）。"""

BACKUP_RE = re.compile(
    r"^(?P<name>.+)_(?P<stamp>\d{8}_\d{6})(?:_(?P<seq>\d+))?(?:\.zip)?$", re.IGNORECASE
)


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #
def app_dir() -> Path:
    """程序所在目录（打包成 exe 后是 exe 所在目录）。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def documents_dir() -> Path | None:
    """Windows「文档」目录——走系统 API，OneDrive 重定向过的也能拿到正确位置。"""
    if WIN:
        try:
            class _GUID(ctypes.Structure):
                _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                            ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]

            # FOLDERID_Documents {FDD39AD0-238F-46AF-ADB4-6C85480369C7}
            fid = _GUID(0xFDD39AD0, 0x238F, 0x46AF,
                        (ctypes.c_ubyte * 8)(0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7))
            shell32 = ctypes.windll.shell32
            shell32.SHGetKnownFolderPath.argtypes = [
                ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_wchar_p),
            ]
            ptr = ctypes.c_wchar_p()
            if shell32.SHGetKnownFolderPath(ctypes.byref(fid), 0, None, ctypes.byref(ptr)) == 0 \
                    and ptr.value:
                try:
                    return Path(ptr.value)
                finally:
                    ctypes.windll.ole32.CoTaskMemFree(ctypes.cast(ptr, ctypes.c_void_p))
        except Exception:
            pass
    home = Path.home()
    for name in ("Documents", "文档"):
        p = home / name
        if p.is_dir():
            return p
    return None


def latest_played_save(saves_root: Path) -> str | None:
    """游戏自己记的「最近加载过的存档名」——Zomboid\\latestSave.ini 的第一行。

    这是最权威的证据：只要玩家加载过某个存档（哪怕它是个备份文件夹），ini 里就会写它的名字。
    """
    saves_root = Path(saves_root)
    for cand in (saves_root.parent.parent / "latestSave.ini",
                 saves_root.parent / "latestSave.ini",
                 saves_root / "latestSave.ini"):
        try:
            if not cand.is_file():
                continue
            lines = [ln.strip() for ln in
                     cand.read_text(encoding="utf-8", errors="ignore").splitlines() if ln.strip()]
        except OSError:
            continue
        if lines:
            return lines[0]
    return None


def config_path(docs: Path | None = None, program_dir: Path | None = None) -> Path:
    """配置文件位置：<文档>\\PZSaveBackup\\config.json

    · 先在文档目录把文件夹建好；实在建不了（没权限）就退回程序目录，至少还能用
    · 老版本把 config.json 放在程序/exe 目录，这里会自动搬一次，免得丢设置
    """
    program_dir = Path(program_dir) if program_dir else app_dir()
    docs = Path(docs) if docs else documents_dir()
    if docs:
        target_dir = docs / CONFIG_DIR_NAME
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            new_path = target_dir / CONFIG_NAME
            old_path = program_dir / CONFIG_NAME
            if not new_path.exists() and old_path.is_file():
                shutil.copy2(old_path, new_path)
            return new_path
        except OSError:
            pass
    return program_dir / CONFIG_NAME


def human_size(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1024.0:
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} PB"


def dir_size(path: Path) -> int:
    """快速统计目录字节数（scandir 递归，比 os.walk+getsize 省一次 syscall）。"""
    total = 0
    stack = [str(path)]
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        else:
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        pass
        except OSError:
            pass
    return total


def save_idle_state(path: Path, idle_seconds: int = DEFAULT_IDLE_SECONDS) -> tuple[bool, float]:
    """存档是否已经安静下来：(是否达到静止要求, 距最后一次写入经过了多少秒)。

    用文件的最新修改时间判断——游戏正在写档时它一直在跳，写完就停。
    （Windows 默认不更新“最后访问时间”，所以“读”追踪不到，只能以“写”为准。）
    """
    newest = fingerprint(path)[2]
    if not newest:
        return True, float("inf")
    age = time.time() - newest
    return age >= idle_seconds, age


def count_files(path: Path) -> int:
    n = 0
    stack = [str(path)]
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        else:
                            n += 1
                    except OSError:
                        pass
        except OSError:
            pass
    return n


def delete_to_recycle_bin(path) -> None:
    """把文件/文件夹送进回收站（Windows），失败则抛异常而不是静默直删。"""
    path = Path(path)
    if not WIN:
        raise OSError(tr("非 Windows 平台不支持回收站删除"))
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", wintypes.UINT),
            ("pFrom", wintypes.LPCWSTR),
            ("pTo", wintypes.LPCWSTR),
            ("fFlags", ctypes.c_uint16),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", ctypes.c_void_p),
            ("lpszProgressTitle", wintypes.LPCWSTR),
        ]

    FO_DELETE = 3
    FOF_ALLOWUNDO = 0x40          # 进回收站
    FOF_NOCONFIRMATION = 0x10
    FOF_NOERRORUI = 0x400
    FOF_SILENT = 0x4

    buf = ctypes.create_unicode_buffer(str(path) + "\0")   # 双 NUL 结尾
    op = SHFILEOPSTRUCTW()
    op.wFunc = FO_DELETE
    op.pFrom = ctypes.cast(buf, wintypes.LPCWSTR)
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_NOERRORUI | FOF_SILENT
    res = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if res != 0 or op.fAnyOperationsAborted:
        raise OSError(tr("移入回收站失败（代码 {0}）", res))
    if path.exists():
        raise OSError(tr("移入回收站失败：路径仍然存在"))


# --------------------------------------------------------------------------- #
# 存档根目录探测（不硬编码任何绝对路径）
# --------------------------------------------------------------------------- #
def _zomboid_candidates() -> list[Path]:
    """枚举本机可能的 Zomboid 用户数据目录（全部基于环境变量推导）。"""
    cands: list[Path] = []
    home = Path.home()

    env_userprofile = os.environ.get("USERPROFILE")
    if env_userprofile:
        cands.append(Path(env_userprofile) / "Zomboid")

    cands.append(home / "Zomboid")

    # Documents / 文档 / OneDrive 下的变体
    doc_roots = []
    for env in ("USERPROFILE",):
        base = os.environ.get(env)
        if base:
            doc_roots.append(Path(base) / "Documents")
            doc_roots.append(Path(base) / "OneDrive" / "Documents")
            doc_roots.append(Path(base) / "OneDrive" / "文档")
    doc_roots.append(home / "Documents")
    doc_roots.append(home / "文档")
    for d in doc_roots:
        cands.append(d / "Zomboid")

    # 去重、保持顺序、只留存在的
    seen, out = set(), []
    for p in cands:
        key = str(p).lower()
        if key not in seen:
            seen.add(key)
            if p.is_dir():
                out.append(p)
    return out


def _saves_subdirs(zomboid_dir: Path) -> list[Path]:
    """Zomboid 根目录下的 Saves\\<类型> 目录列表。"""
    saves = zomboid_dir / "Saves"
    if not saves.is_dir():
        return []
    return [d for d in sorted(saves.iterdir()) if d.is_dir()]


def _read_latest_save(zomboid_dir: Path):
    """latestSave.ini 里记着最近一次存档名与类型，用它反查最可靠的 Saves 路径。"""
    ini = zomboid_dir / "latestSave.ini"
    if not ini.is_file():
        return None
    try:
        lines = [ln.strip() for ln in ini.read_text(encoding="utf-8", errors="ignore").splitlines()]
    except OSError:
        return None
    lines = [ln for ln in lines if ln]
    if len(lines) < 2:
        return None
    save_name, save_type = lines[0], lines[1]
    cand = zomboid_dir / "Saves" / save_type / save_name
    return cand if cand.is_dir() else None


def detect_saves_root() -> tuple[Path | None, str]:
    """返回 (存档根目录, 探测说明)。存档根 = 直接存放各个存档文件夹的那一级。"""
    for zomboid in _zomboid_candidates():
        hit = _read_latest_save(zomboid)
        if hit is not None:
            return hit.parent, tr("依据 {0} 定位", zomboid / "latestSave.ini")

    for zomboid in _zomboid_candidates():
        subs = _saves_subdirs(zomboid)
        if len(subs) == 1:
            return subs[0], tr("依据 {0} 定位", zomboid / "Saves")
        if subs:
            # 多个类型：挑包含存档最多的那个
            best = max(subs, key=lambda d: len([x for x in d.iterdir() if x.is_dir()]))
            return best, tr("依据 {0} 定位", zomboid / "Saves")

    return None, tr("未找到，请手动指定存档目录")


def resolve_saves_root(path: Path) -> Path | None:
    """把用户选的目录“下沉”到真正存放存档的那一级。

    允许用户选择：Zomboid 根 / Saves / Saves\\Sandbox / 任意存档所在目录。
    """
    path = Path(path)
    if not path.is_dir():
        return None
    if path.name.lower() == "saves":
        subs = [d for d in sorted(path.iterdir()) if d.is_dir()]
        if not subs:
            return path
        return max(subs, key=lambda d: len([x for x in d.iterdir() if x.is_dir()]))
    if (path / "Saves").is_dir():
        subs = [d for d in sorted((path / "Saves").iterdir()) if d.is_dir()]
        if subs:
            return max(subs, key=lambda d: len([x for x in d.iterdir() if x.is_dir()]))
        return path / "Saves"
    return path


def default_backup_root(saves_root: Path) -> Path:
    """默认备份位置 = 存档目录本身（备份文件夹与原存档平级放在一起）。"""
    return Path(saves_root)


def fingerprint(path: Path) -> tuple[int, int, int]:
    """目录指纹：(文件数, 总字节, 最新修改时间取整秒)。

    用来判断存档自上次备份以来有没有变化——存档没动就不必再复制一份。
    """
    n = 0
    total = 0
    newest = 0
    stack = [str(path)]
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        else:
                            st = entry.stat(follow_symlinks=False)
                            n += 1
                            total += st.st_size
                            newest = max(newest, int(st.st_mtime))
                    except OSError:
                        pass
        except OSError:
            pass
    return (n, total, newest)


# --------------------------------------------------------------------------- #
# 配置
# --------------------------------------------------------------------------- #
DEFAULT_CONFIG = {
    "saves_root": "",
    "backup_root": "",                       # backup_mode=custom 时才用
    "backup_mode": "same_as_saves",           # same_as_saves = 备份放在存档目录里（与原存档平级）
    "interval_minutes": 30,
    "keep_count": 10,
    "backup_on_start": True,
    "skip_unchanged": True,                   # 存档没变化就跳过，不重复备份
    "only_when_idle": True,                   # 只在存档静止时备份（防把写档中的存档复制坏）
    "idle_seconds": DEFAULT_IDLE_SECONDS,     # 静止多少秒才动手
    "language": "zh",                         # 界面语言：zh / en
    "selected_saves": None,   # None = 还没设置过（默认全勾选）；[] = 一个都不勾选
    "window_geometry": "",
}


class Config:
    def __init__(self, path: Path, on_error=None):
        self.path = path
        self.on_error = on_error
        self.data = dict(DEFAULT_CONFIG)
        self.load()

    def load(self):
        try:
            if self.path.is_file():
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self.data.update({k: v for k, v in loaded.items() if k in DEFAULT_CONFIG})
        except Exception:
            pass  # 配置坏了就用默认值，不打扰用户

    def save(self) -> bool:
        """写入配置，返回是否成功（失败会通过 on_error 报告，不再静默吞掉）。"""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            return True
        except OSError as exc:
            if self.on_error:
                self.on_error(tr("配置保存失败（{0}）：{1}", self.path, exc))
            return False

    def get(self, key, default=None):
        return self.data.get(key, DEFAULT_CONFIG.get(key, default))

    def set(self, key, value) -> bool:
        """只接受已声明的配置项，避免把脏字段写进配置文件。"""
        if key not in DEFAULT_CONFIG:
            return False
        self.data[key] = value
        return True


# --------------------------------------------------------------------------- #
# 备份引擎
# --------------------------------------------------------------------------- #
class BackupEngine:
    """纯逻辑层：复制备份 / 列出 / 清理 / 重命名备份。不依赖 GUI。

    备份方式 = 把整个存档目录原样复制一份，目录名就是 <存档名>_YYYYMMDD_HHMMSS，
    恢复时直接把备份文件夹拷回存档根目录即可，不需要解压。
    """

    def __init__(self, log=lambda msg, level="info": None):
        self.log = log
        self.last_target: Path | None = None  # 最近一次备份的产物路径

    # -- 复制备份 ---------------------------------------------------------- #
    def make_backup(self, save_dir: Path, backup_root: Path, progress=None,
                    verify_unchanged: bool = True) -> Path:
        """把存档目录复制成 <备份目录>/<存档名>_YYYYMMDD_HHMMSS/，返回备份文件夹路径。

        全量备份：文件一个不落地复制，任何一个文件读不了就整次失败（不留残缺备份）；
        复制期间源存档被写过也会作废，避免产出半新半旧的备份。
        """
        save_dir = Path(save_dir)
        backup_root = Path(backup_root)
        if not save_dir.is_dir():
            raise FileNotFoundError(tr("存档目录不存在：{0}", save_dir))
        backup_root.mkdir(parents=True, exist_ok=True)

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        target = backup_root / f"{save_dir.name}_{stamp}"
        seq = 2
        while target.exists():
            target = backup_root / f"{save_dir.name}_{stamp}_{seq}"
            seq += 1

        # 先收集目录与文件（含空目录、含 SQLite 的 *-journal，1:1 原样复制）
        rel_dirs: list[Path] = []
        files: list[Path] = []
        for root, dirnames, filenames in os.walk(save_dir):
            rel = Path(root).relative_to(save_dir)
            for d in dirnames:
                rel_dirs.append(rel / d)
            for name in filenames:
                files.append(Path(root) / name)

        total_bytes = 0
        for f in files:
            try:
                total_bytes += f.stat().st_size
            except OSError:
                pass

        done_bytes = 0
        self.last_target = target
        fp_before = fingerprint(save_dir)
        try:
            target.mkdir(parents=True, exist_ok=True)
            for rel in sorted(rel_dirs, key=lambda p: len(p.parts)):
                (target / rel).mkdir(parents=True, exist_ok=True)
            for i, src in enumerate(files, 1):
                dst = target / src.relative_to(save_dir)
                last_exc = None
                for attempt in range(COPY_RETRIES + 1):
                    try:
                        shutil.copy2(src, dst)
                        last_exc = None
                        break
                    except (PermissionError, OSError) as exc:
                        last_exc = exc
                        if attempt < COPY_RETRIES:
                            time.sleep(0.2 * (2 ** attempt))   # 0.2s / 0.4s / 0.8s 后再试
                if last_exc is not None:
                    # 全量备份原则：宁可整次失败，也不留一个缺文件的备份
                    raise OSError(tr("文件被占用/无法读取：{0}（{1}）", src.name, last_exc))
                try:
                    done_bytes += src.stat().st_size
                except OSError:
                    pass
                if progress:
                    progress(i, len(files), done_bytes, total_bytes, src.name)

            # ① 文件数必须一个不差
            got = count_files(target)
            if got != len(files):
                raise OSError(tr("复制校验失败：应有 {0} 个文件，实际 {1} 个", len(files), got))
            # ② 复制期间源存档不能被写过——否则这份备份半新半旧，拿去恢复会弄坏存档
            if verify_unchanged and fingerprint(save_dir) != fp_before:
                raise SaveChangedDuringBackup(tr("备份过程中存档被写入"))
        except Exception:
            shutil.rmtree(target, ignore_errors=True)      # 不留残次品
            raise
        return target

    # -- 列出 -------------------------------------------------------------- #
    @staticmethod
    def parse_backup_name(foldername: str):
        m = BACKUP_RE.match(foldername)
        if not m:
            return None
        return m.group("name"), datetime.strptime(m.group("stamp"), "%Y%m%d_%H%M%S")

    def list_backups(self, backup_root: Path, with_size: bool = True,
                     exclude: set[str] | None = None) -> list[dict]:
        """列出备份文件夹（也兼容更早的 .zip 备份，会一起显示和管理）。

        with_size=False 时只解析名字/时间，不统计大小——变化检测那种高频调用会快很多。
        exclude 里的目录名会被跳过（用于保护“正在被当成存档玩”的目录）。
        """
        backup_root = Path(backup_root)
        exclude = exclude or set()
        items: list[dict] = []
        if not backup_root.is_dir():
            return items
        try:
            entries = list(os.scandir(backup_root))
        except OSError:
            return items
        for e in entries:
            if e.name in exclude:
                continue
            try:
                is_dir = e.is_dir(follow_symlinks=False)
                is_zip = e.is_file(follow_symlinks=False) and e.name.lower().endswith(".zip")
            except OSError:
                continue
            if not (is_dir or is_zip):
                continue
            parsed = self.parse_backup_name(e.name)
            if not parsed:
                continue          # 名字不符合 <存档名>_时间戳 → 不是备份（比如原存档文件夹）
            try:
                st = e.stat(follow_symlinks=False)
            except OSError:
                continue
            items.append({
                "path": Path(e.path),
                "name": e.name,
                "save": parsed[0],
                "time": parsed[1],
                "size": (dir_size(Path(e.path)) if is_dir else st.st_size) if with_size else 0,
                "kind": "zip" if is_zip else "dir",
            })
        items.sort(key=lambda x: x["time"], reverse=True)
        return items

    # -- 清理 -------------------------------------------------------------- #
    def enforce_keep(self, backup_root: Path, save_name: str, keep: int,
                     protect: set[str] | None = None) -> list[Path]:
        """只保留某个存档最近的 keep 份备份，返回被删掉的列表。keep<=0 表示不清理。

        protect：绝对不能删的目录名（正在被当成存档玩的那种备份——
                 它的名字解析出来可能归属到别的存档名上，误删就等于删了玩家的存档）。
        """
        if keep <= 0:
            return []
        protect = protect or set()
        mine = [b for b in self.list_backups(backup_root, exclude=protect)
                if b["save"] == save_name]
        removed = []
        for item in mine[keep:]:
            if item["name"] in protect:
                self.log(tr("⚠ 保留清理跳过 {0}：它正被当成存档使用，不能当旧备份删", item["name"]), "warn")
                continue
            try:
                delete_to_recycle_bin(item["path"])
                removed.append(item["path"])
            except Exception as exc:
                self.log(tr("⚠ 无法删除旧备份 {0}：{1}", item["name"], exc), "warn")
        return removed

    # -- 重命名备份 -------------------------------------------------------- #
    def rename_backup(self, backup_path: Path, new_save_name: str) -> Path:
        """重命名备份文件夹（只替换 <存档名> 部分，时间戳与序号保留）。"""
        backup_path = Path(backup_path)
        parsed = self.parse_backup_name(backup_path.name)
        if not parsed:
            raise ValueError(tr("名字不符合 <存档名>_时间戳 规则，无法自动改名。"))
        _old, when = parsed
        m = BACKUP_RE.match(backup_path.name)
        seq = m.group("seq") if m else None
        suffix = ".zip" if backup_path.suffix.lower() == ".zip" else ""
        new_name = f"{new_save_name}_{when.strftime('%Y%m%d_%H%M%S')}"
        if seq:
            new_name += f"_{seq}"          # 同一秒的第二、三份，序号必须留着，否则会互相撞名
        new_name += suffix

        target = backup_path.with_name(new_name)
        if target.exists():
            raise FileExistsError(tr("已存在同名备份：{0}", new_name))
        backup_path.rename(target)
        return target


def sanitize_save_name(name: str) -> str:
    """存档名合法性检查（Windows 文件名规则 + 不能只有空白）。"""
    name = (name or "").strip()
    if not name:
        raise ValueError(tr("存档名不能为空"))
    if any(c in name for c in '\\/:*?"<>|'):
        raise ValueError(tr('存档名不能包含 \\ / : * ? " < > | 这些字符'))
    if name != name.rstrip("."):
        raise ValueError(tr("存档名不能以句点结尾"))
    reserved = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}
    if name.split(".")[0].upper() in reserved:
        raise ValueError(tr("{0} 是 Windows 保留名，请换一个", name))
    return name


# --------------------------------------------------------------------------- #
# 定时器
# --------------------------------------------------------------------------- #
class BackupScheduler:
    """后台定时线程：到点就回调一次，可随时停止/更改间隔。"""

    def __init__(self):
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._tick = threading.Event()      # 用于打断等待（改间隔/停止）
        self.interval = 30 * 60
        self.next_run: datetime | None = None
        self._callback = None
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, interval_seconds: int, callback, first_delay: int | None = None):
        self.stop()
        with self._lock:
            self.interval = max(30, int(interval_seconds))
            self._callback = callback
            self._stop.clear()
            self.next_run = datetime.now() + timedelta(
                seconds=self.interval if first_delay is None else first_delay
            )
            self._thread = threading.Thread(target=self._loop, name="pz-backup-timer", daemon=True)
            self._thread.start()

    def set_interval(self, interval_seconds: int):
        with self._lock:
            self.interval = max(30, int(interval_seconds))
            self.next_run = datetime.now() + timedelta(seconds=self.interval)
        self._tick.set()

    def rearm(self):
        """备份做完后重新起算下一轮——定时周期从“备份完成”那一刻开始。

        （到点 → 等时机 → 备份 → 重新计时，而不是按固定节拍硬撞。）
        """
        with self._lock:
            self.interval = max(30, self.interval)
            if self._stop.is_set():
                return
            self.next_run = datetime.now() + timedelta(seconds=self.interval)
        self._tick.set()

    def stop(self):
        self._stop.set()
        self._tick.set()
        t = self._thread
        if t and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=2)
        self._thread = None
        self.next_run = None

    def _loop(self):
        while not self._stop.is_set():
            self._tick.clear()
            with self._lock:
                next_run = self.next_run
            if next_run is None:
                # 本轮已经在处理（等待时机 / 备份中），等备份结束调 rearm() 再重新计时
                self._tick.wait(0.5)
                continue
            remaining = (next_run - datetime.now()).total_seconds()
            if remaining <= 0:
                cb = self._callback
                with self._lock:
                    self.next_run = None
                if cb:
                    try:
                        cb()
                    except Exception:
                        pass
                continue
            self._tick.wait(min(remaining, 1.0))


# --------------------------------------------------------------------------- #
# 界面
# --------------------------------------------------------------------------- #
class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.cfg_path = config_path()
        self.cfg = Config(self.cfg_path, on_error=self._config_error)
        set_lang(self.cfg.get("language"))
        self.lang_code = "en" if LANG == "en" else "zh"
        self.engine = BackupEngine(log=self.log)
        self.scheduler = BackupScheduler()
        self.msg_queue: queue.Queue = queue.Queue()
        self.backing_up = threading.Event()
        self._wait_abort = threading.Event()      # 用于打断“等待存档静止”
        self.saves: list[dict] = []
        self.backup_items: list[dict] = []
        self.checked: set[str] = set()          # 勾选参与自动备份的存档名
        self._checked_loaded = False            # 勾选状态是否已从配置初始化过
        self._known_saves: set[str] = set()     # 见过的存档名（新出现的默认参与备份）
        self.backups_by_save: dict[str, list[dict]] = {}   # 存档名 → 它的备份

        self.saves_root: Path | None = None
        self.backup_root: Path | None = None

        self._build_style()
        self._build_ui()
        self._load_state()
        self._apply_geometry()

        self._pump_job = self.root.after(200, self._pump)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.log(tr("配置文件：{0}", self.cfg_path), "info")
        self.log(tr("就绪。备份目录：{0}", self.backup_root), "info")

    def _config_error(self, message: str):
        """配置文件写不进去时，明确告诉用户，而不是悄悄失败。"""
        try:
            self.log(message, "error")
        except Exception:
            pass

    # ---------------- 样式 ---------------- #
    def _build_style(self):
        style = ttk.Style()
        for theme in ("clam", "vista", "default"):
            try:
                style.theme_use(theme)
                break
            except tk.TclError:
                continue

        self.colors = {
            "primary": "#FF8999",
            "primary_hover": "#E86C7E",
            "primary_press": "#C9455A",
            "surface": "#FAFAFA",
            "surface_alt": "#F3F3F3",
            "background": "#FFFFFF",
            "text_primary": "#323130",
            "text_secondary": "#605E5C",
            "text_disabled": "#A19F9D",
            "border": "#E1DFDD",
            "success": "#107C10",
            "warning": "#B86E00",
            "error": "#D13438",
            "info": "#4A5568",
        }
        c = self.colors

        style.configure(".", font=("Segoe UI", 10))
        style.configure("TFrame", background=c["surface"])
        style.configure("Card.TFrame", background=c["background"])
        style.configure("Header.TFrame", background=c["surface"])
        style.configure("TLabel", background=c["surface"], foreground=c["text_primary"])
        style.configure("Card.TLabel", background=c["background"], foreground=c["text_primary"],
                        font=("Segoe UI", 10))
        style.configure("CardMuted.TLabel", background=c["background"], foreground=c["text_secondary"],
                        font=("Segoe UI", 9))
        style.configure("Title.TLabel", background=c["surface"], foreground=c["text_primary"],
                        font=("Segoe UI", 15, "bold"))
        style.configure("Subtitle.TLabel", background=c["surface"], foreground=c["text_secondary"],
                        font=("Segoe UI", 9))
        style.configure("Section.TLabel", background=c["background"], foreground=c["text_primary"],
                        font=("Segoe UI", 10, "bold"))
        style.configure("Status.TLabel", background=c["surface_alt"], foreground=c["text_secondary"],
                        font=("Segoe UI", 9))
        style.configure("Card.TCheckbutton", background=c["background"], foreground=c["text_primary"],
                        font=("Segoe UI", 9))
        style.configure("TEntry", fieldbackground=c["background"], foreground=c["text_primary"])
        style.configure("TSpinbox", fieldbackground=c["background"], arrowsize=12)
        style.configure("Treeview", background=c["background"], fieldbackground=c["background"],
                        foreground=c["text_primary"], rowheight=24, borderwidth=0,
                        font=("Segoe UI", 10))
        style.configure("Treeview.Heading", background=c["surface_alt"], foreground=c["text_secondary"],
                        font=("Segoe UI", 9, "bold"), relief="flat")
        style.map("Treeview", background=[("selected", "#FFE3E8")],
                  foreground=[("selected", c["text_primary"])])
        style.map("Treeview.Heading", background=[("active", c["border"])])
        style.configure("Horizontal.TProgressbar", background=c["primary"], troughcolor=c["surface_alt"],
                        borderwidth=0, lightcolor=c["primary"], darkcolor=c["primary"])

    def _flat_button(self, parent, text, command, kind="secondary", width=None,
                     small=False, bg_parent=None):
        """扁平化按钮（tk.Button 以便自绘颜色）。"""
        c = self.colors
        if kind == "primary":
            bg, fg, hover = c["primary"], "#FFFFFF", c["primary_hover"]
        elif kind == "danger":
            bg, fg, hover = c["surface_alt"], c["error"], "#F6E2E2"
        else:
            bg, fg, hover = c["surface_alt"], c["text_primary"], c["border"]

        btn = tk.Button(
            parent, text=text, command=command, relief="flat", bd=0, highlightthickness=0,
            bg=bg, fg=fg, activebackground=hover, activeforeground=fg,
            font=("Segoe UI", 9, "bold" if kind == "primary" else "normal"),
            cursor="hand2", padx=10 if small else 12, pady=3 if small else 6,
        )
        if width:
            btn.configure(width=width)
        btn.bind("<Enter>", lambda _e: btn.configure(bg=hover))
        btn.bind("<Leave>", lambda _e: btn.configure(bg=bg))
        return btn


    # ---------------- 界面搭建 ---------------- #
    def _build_ui(self):
        c = self.colors
        self.root.title(f"{tr(APP_TITLE)} v{APP_VERSION}")
        self.root.configure(bg=c["surface"])
        self.root.minsize(540, 330)

        # 状态栏先 pack，保证永远有位置
        self.status = ttk.Label(self.root, text="", style="Status.TLabel", anchor="w", padding=(10, 4))
        self.status.pack(fill="x", side="bottom")

        outer = ttk.Frame(self.root, style="TFrame", padding=(10, 8, 10, 4))
        outer.pack(fill="both", expand=True)

        # ---- 头部：标题 + 页签按钮 + 运行状态 ----
        header = ttk.Frame(outer, style="Header.TFrame")
        header.pack(fill="x")
        ttk.Label(header, text="🧟 " + tr("PZ 存档备份"), style="Title.TLabel").pack(side="left")
        self.header_state = ttk.Label(header, text=tr("自动备份：已停止"), style="Subtitle.TLabel")
        self.header_state.pack(side="right")

        # 语言切换（中文 / English）
        self.lang_var = tk.StringVar(value="English" if LANG == "en" else "中文")
        self.lang_combo = ttk.Combobox(header, textvariable=self.lang_var, state="readonly",
                                       width=8, values=["中文", "English"], font=("Segoe UI", 9))
        self.lang_combo.pack(side="right", padx=(0, 10))
        self.lang_combo.bind("<<ComboboxSelected>>", self._on_lang_changed)

        tabs = ttk.Frame(header, style="Header.TFrame")
        tabs.pack(side="left", padx=(14, 0))
        self._tab_buttons = {}
        for key, label in (("main", tr("备份")), ("adv", tr("高级"))):
            b = tk.Button(tabs, text=label, command=lambda k=key: self.show_page(k),
                          relief="flat", bd=0, highlightthickness=0, cursor="hand2",
                          font=("Segoe UI", 10), padx=16, pady=2)
            b.pack(side="left", padx=(0, 4))
            self._tab_buttons[key] = b

        # ---- 页面容器（两页重叠放置，靠 lift 切换）----
        holder = ttk.Frame(outer, style="TFrame")
        holder.pack(fill="both", expand=True, pady=(8, 0))
        self.pages = {}
        for key in ("main", "adv"):
            page = tk.Frame(holder, bg=c["background"],
                            highlightbackground=c["border"], highlightthickness=1)
            page.place(relx=0, rely=0, relwidth=1, relheight=1)
            self.pages[key] = page
        self._build_main_tab(self.pages["main"])
        self._build_advanced_tab(self.pages["adv"])
        self.current_page = "main"
        self.show_page("main")

    def _on_lang_changed(self, _event=None):
        code = "en" if self.lang_var.get().startswith("English") else "zh"
        self.apply_language(code)

    def apply_language(self, code: str):
        """切换界面语言：记住选择，然后重建界面（最省事也最不容易漏）。"""
        if code == getattr(self, "lang_code", "zh"):
            return
        self.cfg.set("language", code)
        self.cfg.save()
        set_lang(code)
        self.lang_code = code

        was_running = self.scheduler.running
        try:
            interval = int(float(self.interval_var.get()))
        except (ValueError, AttributeError):
            interval = 30
        prev_selected = list(self.saves_tree.selection()) if hasattr(self, "saves_tree") else []

        # 先停掉排队中的消息泵/重绘，否则重建界面后旧回调会打到已销毁的控件上
        for job in (getattr(self, "_pump_job", None),):
            if job:
                try:
                    self.root.after_cancel(job)
                except Exception:
                    pass
        self._pump_job = None

        for w in self.root.winfo_children():
            w.destroy()
        self._build_ui()
        self._load_state()
        self.interval_var.set(str(interval))
        keep = [n for n in prev_selected if self.saves_tree.exists(n)]
        if keep:
            self.saves_tree.selection_set(keep)
        if was_running:
            self.start_auto()
        self._pump_job = self.root.after(400, self._pump)   # 重新启动消息泵
        self.log(tr("界面语言已切换：{0}", "English" if code == "en" else "中文"), "success")

    def show_page(self, key: str):
        """切换「备份 / 高级」页（页签按钮式，不再用 ttk.Notebook）。"""
        self.current_page = key
        self.pages[key].lift()
        for k, btn in self._tab_buttons.items():
            if k == key:
                btn.configure(bg=self.colors["primary"], fg="#FFFFFF",
                              activebackground=self.colors["primary_hover"], activeforeground="#FFFFFF")
            else:
                btn.configure(bg=self.colors["surface"], fg=self.colors["text_secondary"],
                              activebackground=self.colors["surface_alt"],
                              activeforeground=self.colors["text_primary"])

    # ---- 主界面：左存档列表 / 右自动备份控制 ----
    def _build_main_tab(self, tab):
        c = self.colors
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)

        # 存档目录行
        path_bar = tk.Frame(tab, bg=c["background"])
        path_bar.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 8))
        path_bar.columnconfigure(1, weight=1)
        ttk.Label(path_bar, text=tr("存档目录"), style="CardMuted.TLabel").grid(row=0, column=0, sticky="w")
        self.saves_root_var = tk.StringVar(value=tr("（未设置）"))
        ttk.Entry(path_bar, textvariable=self.saves_root_var, font=("Consolas", 9)).grid(
            row=0, column=1, sticky="ew", padx=8)
        self._flat_button(path_bar, tr("选择"), self.choose_saves_root, small=True).grid(row=0, column=2)
        self._flat_button(path_bar, tr("探测"), self.auto_detect, small=True).grid(row=0, column=3, padx=(5, 0))

        body = tk.Frame(tab, bg=c["background"])
        body.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)

        # 左：上 = 存档列表，下 = 选中存档的备份（分类归纳）
        left = tk.Frame(body, bg=c["background"])
        left.grid(row=0, column=0, sticky="nsew")
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=3)
        left.rowconfigure(3, weight=2)

        self.saves_count_label = ttk.Label(left, text=tr("存档（默认全部监控）"), style="CardMuted.TLabel")
        self.saves_count_label.grid(row=0, column=0, sticky="w", pady=(0, 4))

        tree_wrap = tk.Frame(left, bg=c["background"])
        tree_wrap.grid(row=1, column=0, sticky="nsew")
        tree_wrap.columnconfigure(0, weight=1)
        tree_wrap.rowconfigure(0, weight=1)
        self.saves_tree = ttk.Treeview(
            tree_wrap, columns=("backups", "size"), show="tree headings",
            selectmode="extended", height=5,
        )
        self.saves_tree.heading("#0", text=tr("存档名"))
        self.saves_tree.heading("backups", text=tr("备份数"))
        self.saves_tree.heading("size", text=tr("大小"))
        self.saves_tree.column("#0", width=150, anchor="w")
        self.saves_tree.column("backups", width=54, anchor="center", stretch=False)
        self.saves_tree.column("size", width=72, anchor="e", stretch=False)
        sbar = ttk.Scrollbar(tree_wrap, orient="vertical", command=self.saves_tree.yview)
        self.saves_tree.configure(yscrollcommand=sbar.set)
        self.saves_tree.grid(row=0, column=0, sticky="nsew")
        sbar.grid(row=0, column=1, sticky="ns")
        self.saves_tree.tag_configure("off", foreground=c["text_disabled"])
        self.saves_tree.tag_configure("frombackup", foreground=c["warning"])
        self.saves_tree.bind("<ButtonRelease-1>", self._on_saves_click)
        self.saves_tree.bind("<<TreeviewSelect>>", self._on_saves_select)
        self.saves_tree.bind("<Double-1>", lambda _e: self.rename_save())
        self.saves_tree.bind("<Button-3>", self._on_saves_right_click)
        self.saves_menu = tk.Menu(self.root, tearoff=0, font=("Segoe UI", 10))
        self.saves_menu.add_command(label=tr("重命名存档…"), command=self.rename_save)
        self.saves_menu.add_command(label=tr("删除存档…"), command=self.delete_save)
        self.saves_menu.add_separator()
        self.saves_menu.add_command(label=tr("监控 / 不监控这个存档"), command=self._toggle_current_check)
        self.saves_menu.add_command(label=tr("打开存档文件夹"), command=self.open_save_folder)
        self.saves_menu.add_separator()
        self.saves_menu.add_command(label=tr("刷新列表"), command=self.refresh_saves)

        # 备份区标题：下拉选择要看哪个存档的备份
        bh = tk.Frame(left, bg=c["background"])
        bh.grid(row=2, column=0, sticky="ew", pady=(8, 2))
        ttk.Label(bh, text=tr("备份"), style="Section.TLabel").pack(side="left")
        self.backup_view_var = tk.StringVar()
        self.backup_view_combo = ttk.Combobox(bh, textvariable=self.backup_view_var,
                                              state="readonly", width=22, font=("Segoe UI", 9))
        self.backup_view_combo.pack(side="left", padx=(6, 0))
        self.backup_view_combo.bind("<<ComboboxSelected>>", self._refresh_save_backups)
        self.save_backups_label = ttk.Label(bh, text="", style="CardMuted.TLabel")
        self.save_backups_label.pack(side="right")

        bt_wrap = tk.Frame(left, bg=c["background"])
        bt_wrap.grid(row=3, column=0, sticky="nsew")
        bt_wrap.columnconfigure(0, weight=1)
        bt_wrap.rowconfigure(0, weight=1)
        self.save_backups_tree = ttk.Treeview(
            bt_wrap, columns=("size", "time"), show="tree headings",
            selectmode="extended", height=4,
        )
        self.save_backups_tree.heading("#0", text=tr("备份文件夹"))
        self.save_backups_tree.heading("size", text=tr("大小"))
        self.save_backups_tree.heading("time", text=tr("时间"))
        self.save_backups_tree.column("#0", width=150, anchor="w")
        self.save_backups_tree.column("size", width=66, anchor="e", stretch=False)
        self.save_backups_tree.column("time", width=76, anchor="center", stretch=False)
        btsb = ttk.Scrollbar(bt_wrap, orient="vertical", command=self.save_backups_tree.yview)
        self.save_backups_tree.configure(yscrollcommand=btsb.set)
        self.save_backups_tree.grid(row=0, column=0, sticky="nsew")
        btsb.grid(row=0, column=1, sticky="ns")
        self.save_backups_tree.bind("<Double-1>", lambda _e: self.open_backup_item())
        self.save_backups_tree.bind("<Button-3>", self._on_backup_item_right_click)
        self.backup_menu = tk.Menu(self.root, tearoff=0, font=("Segoe UI", 10))
        self.backup_menu.add_command(label=tr("在资源管理器中打开"), command=self.open_backup_item)
        self.backup_menu.add_command(label=tr("重命名备份…"), command=self.rename_backup_item)
        self.backup_menu.add_command(label=tr("删除备份…"), command=self.delete_backup_item)
        self.backup_menu.add_separator()
        self.backup_menu.add_command(label=tr("刷新"), command=self.refresh_saves)

        # 右：自动备份控制
        right = tk.Frame(body, bg=c["background"])
        right.grid(row=0, column=1, sticky="ns", padx=(14, 0))

        ttk.Label(right, text=tr("自动备份"), style="Section.TLabel").pack(anchor="w")

        row = tk.Frame(right, bg=c["background"])
        row.pack(anchor="w", pady=(8, 0))
        ttk.Label(row, text=tr("每"), style="Card.TLabel").pack(side="left")
        self.interval_var = tk.StringVar(value="30")
        ttk.Spinbox(row, from_=1, to=1440, textvariable=self.interval_var, width=6,
                    justify="center").pack(side="left", padx=5)
        ttk.Label(row, text=tr("分钟检测一次"), style="CardMuted.TLabel").pack(side="left")
        ttk.Label(right, text=tr("有变化才备份，没变化跳过"), style="CardMuted.TLabel").pack(
            anchor="w", pady=(2, 0))

        self.start_btn = self._flat_button(right, tr("▶ 开始自动备份"), self.toggle_auto,
                                           kind="primary", width=15)
        self.start_btn.pack(anchor="w", pady=(12, 0))
        self._flat_button(right, tr("⏱ 立即备份"), self.backup_now_clicked, width=15).pack(
            anchor="w", pady=(6, 0))

        tk.Frame(right, bg=c["border"], height=1, width=158).pack(anchor="w", pady=(12, 8))
        ttk.Label(right, text=tr("存档操作"), style="Section.TLabel").pack(anchor="w")
        sf = tk.Frame(right, bg=c["background"])
        sf.pack(anchor="w", pady=(6, 0))
        self._flat_button(sf, tr("重命名"), self.rename_save).pack(side="left")
        self._flat_button(sf, tr("删除"), self.delete_save, kind="danger").pack(side="left", padx=(6, 0))

        self.next_label = ttk.Label(right, text="", style="CardMuted.TLabel", justify="left")
        self.next_label.pack(anchor="w", pady=(12, 0))
        self.idle_label = ttk.Label(right, text="", style="CardMuted.TLabel", justify="left",
                                    wraplength=170)
        self.idle_label.pack(anchor="w", pady=(4, 0))
        self.progress = ttk.Progressbar(right, orient="horizontal", mode="determinate",
                                        style="Horizontal.TProgressbar", length=160)
        self.progress.pack(anchor="w", pady=(6, 0))
        self.progress_label = ttk.Label(right, text="", style="CardMuted.TLabel", wraplength=170,
                                        justify="left")
        self.progress_label.pack(anchor="w", pady=(4, 0))

    # ---- 高级页：设置 / 批量操作 / 备份记录与日志并排 ----
    def _build_advanced_tab(self, tab):
        c = self.colors
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(5, weight=1)
        tab.rowconfigure(7, weight=1)

        # 备份目录
        r0 = tk.Frame(tab, bg=c["background"])
        r0.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 4))
        r0.columnconfigure(1, weight=1)
        ttk.Label(r0, text=tr("备份目录"), style="CardMuted.TLabel").grid(row=0, column=0, sticky="w")
        mid = tk.Frame(r0, bg=c["background"])
        mid.grid(row=0, column=1, sticky="ew", padx=8)
        mid.columnconfigure(1, weight=1)
        self.backup_mode_label = ttk.Label(mid, text=tr("同目录"), style="Section.TLabel")
        self.backup_mode_label.grid(row=0, column=0, padx=(0, 6))
        self.backup_root_var = tk.StringVar(value=tr("（未设置）"))
        ttk.Entry(mid, textvariable=self.backup_root_var, font=("Consolas", 9)).grid(
            row=0, column=1, sticky="ew")
        self._flat_button(r0, tr("更改"), self.choose_backup_root, small=True).grid(row=0, column=2)
        self._flat_button(r0, tr("打开"), self.open_backup_dir, small=True).grid(row=0, column=3, padx=(5, 0))
        self._flat_button(r0, tr("默认"), self.reset_backup_root, small=True).grid(row=0, column=4, padx=(5, 0))

        # 保留份数 + 开关
        r1 = tk.Frame(tab, bg=c["background"])
        r1.grid(row=1, column=0, sticky="ew", padx=12, pady=(6, 0))
        ttk.Label(r1, text=tr("每个存档保留"), style="Card.TLabel").pack(side="left")
        self.keep_var = tk.StringVar(value="10")
        ttk.Spinbox(r1, from_=0, to=9999, textvariable=self.keep_var, width=6,
                    justify="center").pack(side="left", padx=5)
        ttk.Label(r1, text=tr("份（0=不清理）"), style="CardMuted.TLabel").pack(side="left")
        self.backup_on_start_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(r1, text=tr("开启即备份一次"), variable=self.backup_on_start_var,
                        style="Card.TCheckbutton").pack(side="left", padx=(14, 0))

        # 静止保护 + 变化检测
        r1b = tk.Frame(tab, bg=c["background"])
        r1b.grid(row=2, column=0, sticky="ew", padx=12, pady=(6, 0))
        self.only_when_idle_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(r1b, text=tr("仅在存档静止时备份（防复制坏档）"),
                        variable=self.only_when_idle_var,
                        style="Card.TCheckbutton").pack(side="left")
        ttk.Label(r1b, text=tr("静止"), style="CardMuted.TLabel").pack(side="left", padx=(10, 0))
        self.idle_seconds_var = tk.StringVar(value=str(DEFAULT_IDLE_SECONDS))
        ttk.Spinbox(r1b, from_=1, to=600, textvariable=self.idle_seconds_var, width=5,
                    justify="center").pack(side="left", padx=4)
        ttk.Label(r1b, text=tr("秒以上才动它"), style="CardMuted.TLabel").pack(side="left")
        self.skip_unchanged_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(r1b, text=tr("存档没变就跳过（不重复备份）"), variable=self.skip_unchanged_var,
                        style="Card.TCheckbutton").pack(side="left", padx=(14, 0))

        # 批量操作
        r2 = tk.Frame(tab, bg=c["background"])
        r2.grid(row=3, column=0, sticky="ew", padx=12, pady=(8, 0))
        self._flat_button(r2, tr("全部监控"), self.select_all, small=True).pack(side="left")
        self._flat_button(r2, tr("全部排除"), self.select_none, small=True).pack(side="left", padx=(5, 0))
        self._flat_button(r2, tr("重命名存档"), self.rename_save, small=True).pack(side="left", padx=(5, 0))
        self._flat_button(r2, tr("删除存档"), self.delete_save, small=True).pack(side="left", padx=(5, 0))
        self._flat_button(r2, tr("打开存档目录"), self.open_save_dir, small=True).pack(side="left", padx=(5, 0))
        self._flat_button(r2, tr("刷新"), self.refresh_saves, small=True).pack(side="left", padx=(5, 0))

        # 备份记录标题 + 操作
        r3 = tk.Frame(tab, bg=c["background"])
        r3.grid(row=4, column=0, sticky="ew", padx=12, pady=(8, 0))
        ttk.Label(r3, text=tr("备份记录"), style="Section.TLabel").pack(side="left")
        self.backup_count_label = ttk.Label(r3, text="", style="CardMuted.TLabel")
        self.backup_count_label.pack(side="left", padx=8)
        self._flat_button(r3, tr("删除选中"), self.delete_backups, kind="danger", small=True).pack(side="right")
        self._flat_button(r3, tr("重命名选中"), self.rename_backup, small=True).pack(side="right", padx=(0, 5))

        # 备份文件列表（高度 1，靠权重伸展，避免撑大窗口）
        bwrap = tk.Frame(tab, bg=c["background"])
        bwrap.grid(row=5, column=0, sticky="nsew", padx=12, pady=(2, 0))
        bwrap.columnconfigure(0, weight=1)
        bwrap.rowconfigure(0, weight=1)
        self.backup_tree = ttk.Treeview(
            bwrap, columns=("size", "time"), show="tree headings",
            selectmode="extended", height=1,
        )
        self.backup_tree.heading("#0", text=tr("备份文件夹"))
        self.backup_tree.heading("size", text=tr("大小"))
        self.backup_tree.heading("time", text=tr("备份时间"))
        self.backup_tree.column("#0", width=170, anchor="w")
        self.backup_tree.column("size", width=68, anchor="e", stretch=False)
        self.backup_tree.column("time", width=92, anchor="center", stretch=False)
        bsb = ttk.Scrollbar(bwrap, orient="vertical", command=self.backup_tree.yview)
        self.backup_tree.configure(yscrollcommand=bsb.set)
        self.backup_tree.grid(row=0, column=0, sticky="nsew")
        bsb.grid(row=0, column=1, sticky="ns")

        # 日志（同样 height=1 + 权重）
        ttk.Label(tab, text=tr("日志"), style="Section.TLabel").grid(row=6, column=0, sticky="w",
                                                                 padx=12, pady=(6, 0))
        lwrap = tk.Frame(tab, bg=c["background"])
        lwrap.grid(row=7, column=0, sticky="nsew", padx=12, pady=(2, 12))
        lwrap.columnconfigure(0, weight=1)
        lwrap.rowconfigure(0, weight=1)
        self.log_text = tk.Text(lwrap, height=1, wrap="word", relief="flat",
                                bg=c["background"], fg=c["text_secondary"],
                                font=("Consolas", 9), highlightthickness=1,
                                highlightbackground=c["border"], padx=6, pady=4)
        lsb = ttk.Scrollbar(lwrap, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=lsb.set)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        lsb.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(state="disabled")
        self.log_text.tag_configure("info", foreground=c["info"])
        self.log_text.tag_configure("success", foreground=c["success"])
        self.log_text.tag_configure("warn", foreground=c["warning"])
        self.log_text.tag_configure("error", foreground=c["error"])

    # ---------------- 状态 ---------------- #
    def _apply_geometry(self):
        geo = self.cfg.get("window_geometry") or ""
        if geo:
            try:
                self.root.geometry(geo)
                return
            except tk.TclError:
                pass
        w, h = 620, 420
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 3)}")

    def _load_state(self):
        self.interval_var.set(str(self.cfg.get("interval_minutes")))
        self.keep_var.set(str(self.cfg.get("keep_count")))
        self.backup_on_start_var.set(bool(self.cfg.get("backup_on_start")))
        self.skip_unchanged_var.set(bool(self.cfg.get("skip_unchanged")))
        self.only_when_idle_var.set(bool(self.cfg.get("only_when_idle")))
        self.idle_seconds_var.set(str(self.cfg.get("idle_seconds")))

        root_str = self.cfg.get("saves_root") or ""
        root = Path(root_str) if root_str else None
        if not root or not root.is_dir():
            detected, why = detect_saves_root()
            if detected:
                root = detected
                self.cfg.set("saves_root", str(detected))
                self.log(tr("自动探测存档目录：{0}（{1}）", detected, why), "info")
            else:
                root = None
                self.log(why, "warn")
        self.set_saves_root(root, keep_config=False)

        # 备份位置：默认就在存档目录里（同目录模式），跟随存档目录
        self.apply_backup_root(keep_config=False)
        if self.cfg.get("backup_mode") == "custom":
            self.log(tr("备份位置：自定义目录 {0}", self.backup_root), "info")
        else:
            self.log(tr("备份位置：与原存档同目录（{0}）", self.backup_root), "info")

    # ---------------- 存档根目录 ---------------- #
    def set_saves_root(self, path: Path | None, keep_config: bool = True):
        self.saves_root = Path(path) if path else None
        self.saves_root_var.set(str(self.saves_root) if self.saves_root else "（未设置）")
        if keep_config and self.saves_root:
            self.cfg.set("saves_root", str(self.saves_root))
            self.cfg.save()
        self.checked = set()            # 换了存档目录，勾选状态重新初始化
        self._checked_loaded = False
        self.apply_backup_root(keep_config=False)   # 同目录模式下备份位置跟着走
        self.refresh_saves()

    def choose_saves_root(self):
        init = str(self.saves_root or Path.home())
        chosen = filedialog.askdirectory(title=tr("选择存档目录（Zomboid / Saves / 具体存档类型目录都行）"),
                                         initialdir=init)
        if not chosen:
            return
        resolved = resolve_saves_root(Path(chosen))
        if not resolved:
            messagebox.showerror(tr(APP_TITLE), tr("选择的目录不存在。"), parent=self.root)
            return
        self.set_saves_root(resolved)
        self.log(tr("存档目录已更改为：{0}", resolved), "success")
        if not self.backup_root or not self.cfg.get("backup_root"):
            self.reset_backup_root()

    def auto_detect(self):
        detected, why = detect_saves_root()
        if not detected:
            messagebox.showwarning(tr(APP_TITLE), tr("未能自动探测到存档目录：{0}\n请手动选择。", why),
                                   parent=self.root)
            self.log(tr("自动探测失败：{0}", why), "warn")
            return
        self.set_saves_root(detected)
        self.log(tr("自动探测到存档目录：{0}（{1}）", detected, why), "success")

    def open_save_dir(self):
        if self.saves_root:
            self._open_path(self.saves_root)

    # ---------------- 存档列表 ---------------- #
    def refresh_saves(self):
        self.saves_tree.delete(*self.saves_tree.get_children())
        self.saves = []
        self.backups_by_save = {}
        if not self.saves_root or not self.saves_root.is_dir():
            self.saves_count_label.configure(text=tr("未设置存档目录"))
            self._refresh_save_backups()
            return
        try:
            entries = [d for d in sorted(self.saves_root.iterdir()) if d.is_dir() and not d.name.startswith(".")]
        except OSError as exc:
            self.log(tr("读取存档目录失败：{0}", exc), "error")
            return

        # 靠文件名区分：<存档名>_YYYYMMDD_HHMMSS 是备份，其余才是原存档；
        # 但备份若被拿去继续玩，它就是活存档，照样要能备份它。判定看两个信号：
        #   ① 游戏自己记的 latestSave.ini 指向它（最权威）
        #   ② 备份里有比它自己时间戳更新的文件（说明被写过）
        latest_played = latest_played_save(self.saves_root) if self.saves_root else None
        now = time.time()
        for d in entries:
            try:
                _n, size, newest = fingerprint(d)
                st = d.stat()
            except OSError:
                size, newest, st = 0, 0, None
            parsed = BackupEngine.parse_backup_name(d.name)
            from_backup = False
            if parsed:
                played = (latest_played == d.name)
                # “被写过”：最新文件时间落在「备份时间之后、且不在未来」的区间里
                # （未来时间的文件多半是时钟回拨或从别处拷进来的，不能当成玩过的证据）
                stamp_ts = int(parsed[1].timestamp())
                touched = stamp_ts + BACKUP_TOUCH_TOLERANCE < newest <= now + 60
                if not (played or touched):
                    continue                     # 静止的备份 → 不是存档
                from_backup = True
            mtime = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M") if st else "-"
            self.saves.append({"name": d.name, "path": d, "size": size, "mtime": mtime,
                               "from_backup": from_backup})

        # 归类：备份按归属的存档名分组（时间倒序）；“玩起来的备份”按存档看待，不算备份
        active_backups = {s["name"] for s in self.saves if s["from_backup"]}
        for b in self.engine.list_backups(self.backup_root or self.saves_root):
            if b["name"] in active_backups:
                continue
            self.backups_by_save.setdefault(b["save"], []).append(b)

        for s in self.saves:
            n = len(self.backups_by_save.get(s["name"], []))
            self.saves_tree.insert("", "end", iid=s["name"], text=s["name"],
                                   values=(f"{n} 份" if n else "—", human_size(s["size"])),
                                   tags=("frombackup",) if s["from_backup"] else ())

        names = [s["name"] for s in self.saves]
        if not self._checked_loaded:
            stored = self.cfg.get("selected_saves")
            # 配置里没有记录（首次使用）→ 全部勾选；记录为空列表 → 一个都不勾
            self.checked = set(names) if stored is None else {n for n in names if n in set(stored)}
            self._checked_loaded = True
        else:
            self.checked &= set(names)     # 存档被删掉后同步勾选状态
        # 新冒出来的存档（比如刚开始玩一个旧备份）默认纳入备份
        new_names = set(names) - self._known_saves
        if new_names:
            self.checked |= new_names
            for n in sorted(new_names):
                if n in active_backups:
                    self.log(tr("发现一个被继续玩的备份存档：{0}（已自动勾选，会一起备份）", n), "warn")
        self._known_saves = set(names)
        self._paint_saves()

        # 游戏最近加载的那个存档不在了？提醒一句（可能被改名/删除，或被误清理）
        if latest_played and latest_played not in names and \
                latest_played != getattr(self, "_missing_warned", None):
            self._missing_warned = latest_played
            self.log(tr("⚠ 游戏最近加载的存档「{0}」不在存档目录里（被改名或删除了？）", latest_played),
                     "warn")

        # 备份视图的下拉列表
        if hasattr(self, "backup_view_combo"):
            self.backup_view_combo.configure(values=names)
            if self.backup_view_var.get() not in names:
                # 默认挑一个有备份的存档来看，没有就取第一个
                with_backups = [n for n in names if self.backups_by_save.get(n)]
                self.backup_view_var.set((with_backups or names or [""])[0])

        self._refresh_save_backups()
        self.refresh_backups()

    def _on_saves_select(self, _event=None):
        """左侧选中的存档 → 下方备份区跟着切换（分类归纳）。"""
        sel = self.saves_tree.selection()
        if not sel or not hasattr(self, "backup_view_var"):
            return
        name = sel[0]
        if self.backup_view_var.get() != name:
            self.backup_view_var.set(name)
            self._refresh_save_backups()

    def _refresh_save_backups(self, _event=None):
        """显示下拉里选中存档的全部备份（时间倒序）。"""
        if not hasattr(self, "save_backups_tree"):
            return
        self.save_backups_tree.delete(*self.save_backups_tree.get_children())
        name = self.backup_view_var.get().strip() if hasattr(self, "backup_view_var") else ""
        items = self.backups_by_save.get(name, []) if name else []
        for it in items:
            label = it["name"] if it.get("kind") != "zip" else it["name"] + tr("（旧版 zip）")
            self.save_backups_tree.insert(
                "", "end", iid=it["name"], text=label, values=(
                    human_size(it["size"]), it["time"].strftime("%m-%d %H:%M"),
                ),
            )
        if hasattr(self, "save_backups_label"):
            self.save_backups_label.configure(
                text=tr("{0} 份备份", len(items)) if name else tr("备份（先选一个存档）")
            )

    def _paint_saves(self):
        for s in self.saves:
            on = s["name"] in self.checked
            tags = []
            if s.get("from_backup"):
                tags.append("frombackup")
            if not on:
                tags.append("off")
            self.saves_tree.item(
                s["name"], text=f"{'☑' if on else '☐'} {s['name']}", tags=tuple(tags),
            )
        playing = sum(1 for s in self.saves if s.get("from_backup"))
        tail = tr(" · 橙色=在玩的备份") if playing else ""
        self.saves_count_label.configure(
            text=tr("存档：监控 {0}/{1} 个 · {2}", len(self.checked), len(self.saves),
                    human_size(sum(s['size'] for s in self.saves))) + tail
        )

    def _on_saves_click(self, event):
        """单击某一行 = 切换它是否参与自动备份（不影响其他行）。"""
        row = self.saves_tree.identify_row(event.y)
        if not row or row not in [s["name"] for s in self.saves]:
            return
        if row in self.checked:
            self.checked.discard(row)
        else:
            self.checked.add(row)
        self._paint_saves()
        self._persist_checked()

    def _persist_checked(self):
        self.cfg.set("selected_saves", [s["name"] for s in self.saves if s["name"] in self.checked])
        self.cfg.save()

    def select_all(self):
        """监控全部存档（默认就是这样）。"""
        self.checked = {s["name"] for s in self.saves}
        self._paint_saves()
        self._persist_checked()

    def select_none(self):
        """排除全部存档；下次备份会自动恢复成全监控。"""
        self.checked = set()
        self._paint_saves()
        self._persist_checked()

    def selected_save_names(self) -> list[str]:
        return [s["name"] for s in self.saves if s["name"] in self.checked]

    # ---------------- 重命名存档 ---------------- #
    def rename_save(self):
        sel = self.saves_tree.selection()
        if len(sel) != 1:
            messagebox.showinfo(tr(APP_TITLE), tr("请先在列表里点选一个存档（高亮那一行）。"), parent=self.root)
            return
        old = sel[0]
        new = simpledialog.askstring(tr(APP_TITLE), tr("把存档「{0}」重命名为：", old), initialvalue=old,
                                     parent=self.root)
        if new is None or new.strip() == old:
            return
        try:
            name = sanitize_save_name(new)
        except ValueError as exc:
            messagebox.showerror(tr(APP_TITLE), str(exc), parent=self.root)
            return

        src = self.saves_root / old
        dst = self.saves_root / name
        if dst.exists():
            messagebox.showerror(tr(APP_TITLE), tr("已存在同名存档：{0}", name), parent=self.root)
            return
        try:
            src.rename(dst)
        except OSError as exc:
            messagebox.showerror(
                tr(APP_TITLE), tr("重命名失败：{0}\n（如果游戏正在运行，请先退出游戏再试）", exc),
                parent=self.root
            )
            return

        # 这个存档名下的备份要跟着改名，否则它们会认不到主人
        bak_ok, bak_fail = self._rename_backups_for_save(old, name)

        # 同步勾选/配置里的名字
        if old in self.checked:
            self.checked.discard(old)
            self.checked.add(name)
        self.cfg.set("selected_saves", [s["name"] for s in self.saves if s["name"] in self.checked])
        self.cfg.save()
        self.refresh_saves()
        self.saves_tree.selection_set([name])
        self.log(tr("存档已重命名：{0} → {1}", old, name), "success")
        if bak_ok:
            self.log(tr("  {0} 份备份也跟着改名了（{1} → {2}）", bak_ok, old, name), "info")
        if bak_fail:
            self.log(tr("  ⚠ 有 {0} 份备份改名失败，可在备份区右键手动改名", bak_fail), "warn")

    def _rename_backups_for_save(self, old_name: str, new_name: str) -> tuple[int, int]:
        """把归在 old_name 名下的备份都改成新名字，返回 (成功, 失败)。"""
        ok = fail = 0
        for b in list(self.backups_by_save.get(old_name, [])):
            try:
                self.engine.rename_backup(b["path"], new_name)
                ok += 1
            except Exception as exc:
                fail += 1
                self.log(tr("⚠ 备份改名失败 {0}：{1}", b["name"], exc), "warn")
        return ok, fail

    def delete_save(self):
        """把选中的存档移入回收站（可还原），需要二次确认。"""
        sel = self.saves_tree.selection()
        if len(sel) != 1:
            messagebox.showinfo(tr(APP_TITLE), tr("请先在列表里点选一个存档（高亮那一行）。"), parent=self.root)
            return
        name = sel[0]
        target = self.saves_root / name if self.saves_root else None
        if not target or not target.is_dir():
            self.log(f"存档不存在：{target}", "error")
            self.refresh_saves()
            return

        try:
            size = human_size(dir_size(target))
        except OSError:
            size = "?"
        if not messagebox.askyesno(
            tr(APP_TITLE),
            tr("把存档「{0}」（{1}）移入回收站？\n\n存档会进回收站，之后仍可从回收站还原。\n"
               "要是还想留着它，建议先点「立即备份」。", name, size),
            parent=self.root, icon="warning",
        ):
            return
        try:
            delete_to_recycle_bin(target)
        except Exception as exc:
            messagebox.showerror(
                tr(APP_TITLE), tr("删除失败：{0}\n（如果游戏正在运行，请先退出游戏再试）", exc),
                parent=self.root
            )
            return

        self.checked.discard(name)
        self._persist_checked()
        self.refresh_saves()
        self.log(tr("存档已移入回收站：{0}（可从回收站还原）", name), "warn")

    def _on_saves_right_click(self, event):
        row = self.saves_tree.identify_row(event.y)
        if not row:
            return
        self.saves_tree.selection_set(row)
        self.saves_tree.focus(row)
        try:
            self.saves_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.saves_menu.grab_release()

    def _toggle_current_check(self):
        sel = self.saves_tree.selection()
        if not sel:
            return
        for name in sel:
            if name in self.checked:
                self.checked.discard(name)
            else:
                self.checked.add(name)
        self._paint_saves()
        self._persist_checked()

    def open_save_folder(self):
        sel = self.saves_tree.selection()
        if len(sel) == 1 and self.saves_root:
            self._open_path(self.saves_root / sel[0])
        elif self.saves_root:
            self._open_path(self.saves_root)

    # ---------------- 备份目录（默认与原存档同目录） ---------------- #
    def _effective_backup_root(self) -> Path | None:
        """备份位置：默认就是存档目录本身（备份文件夹与原存档并排），也可自定义。"""
        if self.cfg.get("backup_mode") == "custom":
            p = (self.cfg.get("backup_root") or "").strip()
            if p:
                return Path(p)
        return self.saves_root

    def apply_backup_root(self, keep_config: bool = False):
        """按当前模式（同目录 / 自定义）刷新备份位置并更新界面。"""
        root = self._effective_backup_root()
        self.backup_root = root
        if root:
            same = self.cfg.get("backup_mode") != "custom"
            self.backup_root_var.set(str(root))
            if hasattr(self, "backup_mode_label"):
                self.backup_mode_label.configure(text=tr("同目录") if same else tr("自定义"))
        else:
            self.backup_root_var.set(tr("（未设置）"))
            if hasattr(self, "backup_mode_label"):
                self.backup_mode_label.configure(text="—")
        if keep_config:
            self.cfg.save()
        self.refresh_backups()

    def set_backup_root(self, path: Path | None, keep_config: bool = True):
        """直接指定备份目录（会切到自定义模式）——外部/测试调用入口。"""
        if path is None:
            self.cfg.set("backup_mode", "same_as_saves")
        else:
            self.cfg.set("backup_mode", "custom")
            self.cfg.set("backup_root", str(path))
        self.apply_backup_root(keep_config=keep_config)

    def choose_backup_root(self):
        init = str(self.backup_root or (self.saves_root or Path.home()))
        chosen = filedialog.askdirectory(title=tr("选择备份存放目录（默认与原存档同一个文件夹）"),
                                         initialdir=init)
        if not chosen:
            return
        self.set_backup_root(Path(chosen))
        self.log(tr("备份目录已更改为自定义位置：{0}", chosen), "success")

    def reset_backup_root(self):
        """切回默认：备份就放在存档目录里，与原存档并排。"""
        if not self.saves_root:
            return
        self.set_backup_root(None)
        self.log(tr("备份位置已切回同目录模式：{0}", self.backup_root), "info")

    def open_backup_dir(self):
        if self.backup_root:
            self.backup_root.mkdir(parents=True, exist_ok=True)
            self._open_path(self.backup_root)

    @staticmethod
    def _open_path(path: Path):
        try:
            if WIN:
                os.startfile(str(path))          # noqa: S606
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception:
            pass

    # ---------------- 备份列表 / 操作 ---------------- #
    def refresh_backups(self):
        self.backup_tree.delete(*self.backup_tree.get_children())
        self.backup_items = []
        if self.backup_root:
            active = {s["name"] for s in self.saves if s.get("from_backup")}
            items = [b for b in self.engine.list_backups(self.backup_root)
                     if b["name"] not in active]
            self.backup_items = items
            total = 0
            for item in items:
                total += item["size"]
                label = item["name"] if item.get("kind") != "zip" else item["name"] + tr("（旧版 zip）")
                self.backup_tree.insert(
                    "", "end", iid=item["name"], text=label, values=(
                        human_size(item["size"]),
                        item["time"].strftime("%m-%d %H:%M"),
                    ),
                )
            self.backup_count_label.configure(
                text=tr("{0} 份 · {1}", len(items), human_size(total)) if items else tr("（还没有备份）")
            )
        else:
            self.backup_count_label.configure(text="")
        self._refresh_save_backups()

    # -- 删除 / 重命名（高级页总览与主界面备份区共用）--
    def _delete_backup_names(self, names: list[str]):
        if not names:
            return
        if not messagebox.askyesno(
            tr(APP_TITLE),
            tr("把选中的 {0} 份备份移入回收站？\n（之后仍可从回收站还原）", len(names)),
            parent=self.root, icon="warning",
        ):
            return
        removed = 0
        for name in names:
            try:
                delete_to_recycle_bin(self.backup_root / name)
                removed += 1
            except Exception as exc:
                self.log(tr("⚠ 删除失败 {0}：{1}", name, exc), "warn")
        self.refresh_saves()
        self.log(tr("已把 {0} 份备份移入回收站", removed), "info")

    def _rename_backup_name(self, name: str):
        parsed = self.engine.parse_backup_name(name)
        if not parsed:
            messagebox.showerror(tr(APP_TITLE), tr("名字不符合 <存档名>_时间戳 规则，无法自动改名。"),
                                 parent=self.root)
            return
        old_save = parsed[0]
        new_save = simpledialog.askstring(tr(APP_TITLE), tr("把这份备份归属的存档名改为："),
                                          initialvalue=old_save, parent=self.root)
        if not new_save or new_save.strip() == old_save:
            return
        try:
            new_save = sanitize_save_name(new_save)
            target = self.engine.rename_backup(self.backup_root / name, new_save)
        except Exception as exc:
            messagebox.showerror(tr(APP_TITLE), tr("重命名失败：{0}", exc), parent=self.root)
            return
        self.refresh_saves()
        self.log(tr("备份已重命名：{0} → {1}", name, target.name), "success")

    # 高级页：备份记录总览
    def delete_backups(self):
        self._delete_backup_names(list(self.backup_tree.selection()))

    def rename_backup(self):
        sel = list(self.backup_tree.selection())
        if len(sel) != 1:
            messagebox.showinfo(tr(APP_TITLE), tr("请选择且只选择一份备份。"), parent=self.root)
            return
        self._rename_backup_name(sel[0])

    # 主界面：某个存档的备份区
    def delete_backup_item(self):
        self._delete_backup_names(list(self.save_backups_tree.selection()))

    def rename_backup_item(self):
        sel = list(self.save_backups_tree.selection())
        if len(sel) != 1:
            messagebox.showinfo(tr(APP_TITLE), tr("请选择且只选择一份备份。"), parent=self.root)
            return
        self._rename_backup_name(sel[0])

    def open_backup_item(self):
        sel = list(self.save_backups_tree.selection())
        if not sel or not self.backup_root:
            return
        self._open_path(self.backup_root / sel[0])

    def _on_backup_item_right_click(self, event):
        row = self.save_backups_tree.identify_row(event.y)
        if not row:
            return
        self.save_backups_tree.selection_set(row)
        self.save_backups_tree.focus(row)
        try:
            self.backup_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.backup_menu.grab_release()

    # ---------------- 自动备份 ---------------- #
    def toggle_auto(self):
        if self.scheduler.running:
            self.stop_auto()
        else:
            self.start_auto()

    def start_auto(self):
        if not self.saves_root or not self.saves_root.is_dir():
            messagebox.showwarning(tr(APP_TITLE), tr("请先设置有效的存档目录。"), parent=self.root)
            return
        try:
            minutes = max(1, int(float(self.interval_var.get())))
        except ValueError:
            messagebox.showerror(tr(APP_TITLE), tr("间隔必须是数字（分钟）。"), parent=self.root)
            return
        self.interval_var.set(str(minutes))
        self.cfg.set("interval_minutes", minutes)
        try:
            self.cfg.set("keep_count", max(0, int(float(self.keep_var.get()))))
        except ValueError:
            pass
        self.cfg.set("backup_on_start", bool(self.backup_on_start_var.get()))
        self.cfg.set("skip_unchanged", bool(self.skip_unchanged_var.get()))
        self.cfg.set("only_when_idle", bool(self.only_when_idle_var.get()))
        try:
            self.cfg.set("idle_seconds", max(1, int(float(self.idle_seconds_var.get()))))
        except ValueError:
            pass
        self.cfg.save()

        self._wait_abort.clear()
        first_delay = 1 if self.backup_on_start_var.get() else minutes * 60
        self.scheduler.start(minutes * 60, self._on_timer, first_delay=first_delay)
        self.start_btn.configure(text=tr("■ 停止自动备份"))
        self.header_state.configure(text=tr("自动备份：运行中 · 每 {0} 分钟", minutes))
        self.log(tr("已开启自动备份：每 {0} 分钟检查一次所有存档，有变化才备份", minutes)
                 + (tr("（现在先检查一次）") if self.backup_on_start_var.get() else ""), "success")

    def stop_auto(self):
        self._wait_abort.set()          # 打断“等待存档静止”
        self.scheduler.stop()
        self.start_btn.configure(text=tr("▶ 开始自动备份"))
        self.header_state.configure(text=tr("自动备份：已停止"))
        self.log(tr("自动备份已停止"), "warn")

    def _on_timer(self):
        """定时到点（定时器线程回调）：开始找时机备份，备份完成后再重新计时。"""
        if not self._start_backup(reason=tr("定时"), wait_for_idle=True):
            self.scheduler.rearm()      # 没跑起来也不能让定时器停摆

    def backup_now_clicked(self):
        self._start_backup(reason=tr("手动"))

    def _protected_save_dirs(self) -> set[str]:
        """这些目录不能被当成“旧备份”清理掉——它们要么是正在玩的备份，要么是游戏最近加载的存档。"""
        protect = {s["name"] for s in self.saves if s.get("from_backup")}
        try:
            latest = latest_played_save(self.saves_root) if self.saves_root else None
        except OSError:
            latest = None
        if latest:
            protect.add(latest)
        return protect

    def _start_backup(self, reason: str, wait_for_idle: bool = False) -> bool:
        if self.backing_up.is_set():
            self.log(tr("上一次备份还在进行中，本次跳过"), "warn")
            return False
        if not self.saves_root or not self.saves_root.is_dir():
            self.log(tr("存档目录无效，无法备份"), "error")
            return False
        if not self.backup_root:
            self.log(tr("备份目录未设置，无法备份"), "error")
            return False
        names = self.selected_save_names()
        if not names:
            # 没勾任何存档 = 用户就是想要“全都看着”，自动恢复成全监控
            names = [s["name"] for s in self.saves]
            self.checked = set(names)
            self._persist_checked()
            self._paint_saves()
            if names:
                self.log(tr("没有勾选任何存档，已自动改为监控全部（{0} 个）", len(names)), "info")
        if not names:
            self.log(tr("存档目录里还没有存档，无法备份"), "warn")
            return False

        try:
            keep = max(0, int(float(self.keep_var.get())))
        except ValueError:
            keep = int(self.cfg.get("keep_count"))
        skip_unchanged = bool(self.skip_unchanged_var.get())
        only_when_idle = bool(self.only_when_idle_var.get())
        try:
            idle_seconds = max(1, int(float(self.idle_seconds_var.get())))
        except ValueError:
            idle_seconds = DEFAULT_IDLE_SECONDS

        # 每个存档最近一份备份（不统计大小，只为下面比指纹）
        latest_map: dict[str, dict] = {}
        for b in self.engine.list_backups(self.backup_root, with_size=False):
            latest_map.setdefault(b["save"], b)

        self.backing_up.set()
        self._wait_abort.clear()      # 本次备份独立，别继承上一次“停止”留下的信号
        threading.Thread(target=self._backup_worker, name="pz-backup-worker", daemon=True,
                         args=(reason, names, keep, skip_unchanged, latest_map,
                               only_when_idle, idle_seconds,
                               self._protected_save_dirs(), wait_for_idle)).start()
        return True

    def _backup_worker(self, reason: str, names: list[str], keep: int,
                       skip_unchanged: bool = True, latest_map: dict | None = None,
                       only_when_idle: bool = True, idle_seconds: int = DEFAULT_IDLE_SECONDS,
                       protect: set[str] | None = None, wait_for_idle: bool = False):
        q = self.msg_queue
        q.put(("log", tr("── {0}检查：{1} 个存档", reason, len(names)), "info"))

        # 到点后先等时机：所有存档都安静下来才动手（最多等 IDLE_WAIT_SECONDS 秒）
        if wait_for_idle and only_when_idle:
            deadline = time.time() + IDLE_WAIT_SECONDS
            while not self._wait_abort.is_set():
                busy_names = []
                for nm in names:
                    p = self.saves_root / nm
                    if not p.is_dir():
                        continue
                    ok, age = save_idle_state(p, idle_seconds)
                    if not ok:
                        busy_names.append((nm, age))
                if not busy_names:
                    break
                if time.time() > deadline:
                    q.put(("log", tr("· 等了 {0} 秒存档还在写，本轮不备份了（下轮再试）",
                                     IDLE_WAIT_SECONDS), "warn"))
                    q.put(("log", tr("── {0}备份结束：成功 0，失败 0，没等到存档静止", reason), "warn"))
                    q.put(("done", None))
                    return
                who, age = busy_names[0]
                q.put(("status", tr("等待存档静止：{0}（{1} 秒前刚写过）…", who, f"{age:.0f}")))
                time.sleep(2)
            if self._wait_abort.is_set():
                q.put(("log", tr("── {0}备份已取消（自动备份被停止）", reason), "warn"))
                q.put(("done", None))
                return

        ok = fail = unchanged = busy = changed = 0
        for idx, name in enumerate(names, 1):
            src = self.saves_root / name
            if not src.is_dir():
                q.put(("log", f"· {name} 不存在了，跳过", "warn"))
                continue

            # ① 游戏正在写这个存档 → 绝对不碰（写档期间复制会做出坏备份，恢复时会弄坏存档）
            if only_when_idle:
                idle, age = save_idle_state(src, idle_seconds)
                if not idle:
                    busy += 1
                    q.put(("log",
                           tr("· {0} 正在被写入（{1} 秒前刚写过），本轮不备份（需要静止 {2} 秒）",
                              name, f"{age:.0f}", idle_seconds), "warn"))
                    continue

            # ② 存档没变化就不重复备份（拿最近一份备份比指纹）
            if skip_unchanged and latest_map:
                latest = latest_map.get(name)
                if latest:
                    q.put(("status", tr("[{0}/{1}] 检查 {2} 有没有变化 …", idx, len(names), name)))
                    try:
                        if fingerprint(src) == fingerprint(latest["path"]):
                            unchanged += 1
                            q.put(("log", tr("· {0} 没有变化，跳过（上次备份 {1}）", name, latest["name"]), "info"))
                            continue
                    except OSError:
                        pass

            q.put(("status", tr("[{0}/{1}] 正在备份 {2} …", idx, len(names), name)))
            q.put(("progress", 0.0))

            def prog(i, total, done_bytes, total_bytes, cur, _name=name, _idx=idx):
                frac = (i / total) if total else 1.0
                q.put(("progress", min(0.999, (_idx - 1 + frac) / len(names))))
                q.put(("status", tr("[{0}/{1}] {2}：{3}/{4} 个文件（{5}/{6}）", _idx, len(names),
                                     _name, i, total, human_size(done_bytes),
                                     human_size(total_bytes))))

            try:
                t0 = time.time()
                out = self.engine.make_backup(src, self.backup_root, progress=prog,
                                              verify_unchanged=only_when_idle)
                size = dir_size(out)
                ok += 1
                q.put(("log", tr("✔ {0} → {1}（{2}，{3}s）", name, out.name, human_size(size),
                                  f"{time.time() - t0:.1f}"), "success"))
                removed = self.engine.enforce_keep(self.backup_root, name, keep, protect=protect)
                if removed:
                    q.put(("log", tr("  清理旧备份 {0} 份（保留最近 {1} 份）", len(removed), keep), "info"))
            except SaveChangedDuringBackup:
                changed += 1
                q.put(("log", tr("⚠ {0} 备份途中被游戏写入，这次备份已作废并删除（等它安静下来会自动重做）",
                                  name), "warn"))
            except Exception as exc:
                fail += 1
                q.put(("log", tr("✘ {0} 备份失败：{1}", name, exc), "error"))

        bits = []
        if unchanged:
            bits.append(tr("，{0} 个没变化", unchanged))
        if busy:
            bits.append(tr("，{0} 个正在写入没碰", busy))
        if changed:
            bits.append(tr("，{0} 个备份途中被写入已作废", changed))
        tail = "".join(bits)
        q.put(("log", tr("── {0}备份结束：成功 {1}，失败 {2}{3}", reason, ok, fail, tail),
               "success" if fail == 0 else "warn"))
        q.put(("done", None))

    # ---------------- 消息泵 ---------------- #
    def _pump(self):
        try:
            while True:
                kind, payload, *rest = self.msg_queue.get_nowait()
                if kind == "log":
                    self.log(payload, rest[0] if rest else "info")
                elif kind == "progress":
                    self.progress.configure(value=payload * 100)
                elif kind == "status":
                    self.progress_label.configure(text=payload)
                elif kind == "done":
                    self.backing_up.clear()
                    if self.scheduler.running:
                        self.scheduler.rearm()      # 备份做完 → 下一轮从现在开始计时
                    self.progress.configure(value=0)
                    self.progress_label.configure(text="")
                    self.refresh_backups()
                    self.refresh_saves()
                elif kind == "alert":
                    messagebox.showwarning(tr(APP_TITLE), payload, parent=self.root)
        except queue.Empty:
            pass
        self._update_statusbar()
        self._pump_job = self.root.after(400, self._pump)

    def _update_statusbar(self):
        if self.scheduler.running:
            nxt = self.scheduler.next_run
            if nxt:
                remain = max(0, int((nxt - datetime.now()).total_seconds()))
                self.next_label.configure(
                    text=tr("下次备份 {0}（剩 {1}:{2}）", nxt.strftime("%H:%M"),
                            f"{remain // 60:02d}", f"{remain % 60:02d}")
                )
            else:
                self.next_label.configure(text=tr("正在等存档静止，然后备份…"))
        else:
            self.next_label.configure(text=tr("自动备份：未开启"))
        parts = [tr("存档目录：{0}", self.saves_root or tr("未设置"))]
        if self.backing_up.is_set():
            parts.append(tr("状态：备份中…"))
        self.status.configure(text="   |   ".join(parts))

        # 存档还在不在被写（约每 5 秒扫一次就够）
        self._idle_tick = getattr(self, "_idle_tick", 0) + 1
        if self._idle_tick % 12 == 0:
            self._update_idle_label()

    def _update_idle_label(self):
        """实时告诉用户：现在能不能安全备份（存档是否已经静止）。"""
        if not hasattr(self, "idle_label"):
            return
        if not self.saves:
            self.idle_label.configure(text="")
            return
        try:
            limit = max(1, int(float(self.idle_seconds_var.get())))
        except ValueError:
            limit = DEFAULT_IDLE_SECONDS
        newest, who = 0.0, ""
        for s in self.saves:
            n = fingerprint(s["path"])[2]
            if n > newest:
                newest, who = float(n), s["name"]
        if not newest:
            self.idle_label.configure(text="")
            return
        age = max(0.0, time.time() - newest)
        if age >= limit:
            self.idle_label.configure(
                text=tr("存档已静止 {0} 秒，可以安全备份", f"{age:.0f}"),
                foreground=self.colors["success"])
        else:
            self.idle_label.configure(
                text=tr("⚠ 正在写入（{0}，{1} 秒前），暂不备份", who, f"{age:.0f}"),
                foreground=self.colors["warning"])

    def log(self, message: str, level: str = "info"):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{ts}] {message}\n", level)
        self.log_text.see("end")
        # 控制日志行数，避免长时间运行后卡顿
        if int(self.log_text.index("end-1c").split(".")[0]) > 400:
            self.log_text.delete("1.0", "50.0")
        self.log_text.configure(state="disabled")

    def on_close(self):
        try:
            self.cfg.set("window_geometry", self.root.winfo_geometry())
            self.cfg.set("interval_minutes", int(float(self.interval_var.get())))
            self.cfg.set("keep_count", max(0, int(float(self.keep_var.get()))))
            self.cfg.set("backup_on_start", bool(self.backup_on_start_var.get()))
            self.cfg.set("skip_unchanged", bool(self.skip_unchanged_var.get()))
            self.cfg.set("only_when_idle", bool(self.only_when_idle_var.get()))
            try:
                self.cfg.set("idle_seconds", max(1, int(float(self.idle_seconds_var.get()))))
            except ValueError:
                pass
            self.cfg.set("selected_saves", [s["name"] for s in self.saves if s["name"] in self.checked])
            self.cfg.save()
        finally:
            self.scheduler.stop()
            self.root.destroy()


# --------------------------------------------------------------------------- #
# 自检（不启动界面，在临时目录验证核心逻辑）
# --------------------------------------------------------------------------- #
def selftest() -> int:
    print(f"{APP_TITLE} v{APP_VERSION} — 核心逻辑自检")
    with tempfile.TemporaryDirectory(prefix="pz_backup_test_") as tmp:
        tmp = Path(tmp).resolve()   # 去掉 Windows 8.3 短路径（ADMINI~1）
        saves_root = tmp / "Saves" / "Sandbox"
        save = saves_root / "测试存档"
        (save / "chunkdata").mkdir(parents=True)
        (save / "entity_data.bin").write_bytes(b"x" * 4096)
        (save / "map_visited.bin").write_bytes(os.urandom(100_000))
        (save / "players.db-journal").write_bytes(b"")
        (save / "chunkdata" / "a.bin").write_bytes(b"y" * 1024)
        (saves_root / "第二个存档").mkdir()
        (saves_root / "第二个存档" / "d.bin").write_bytes(b"z" * 512)

        root_resolved = resolve_saves_root(saves_root.parent)
        assert root_resolved == saves_root, root_resolved
        assert resolve_saves_root(tmp / "Saves" / "Sandbox") == saves_root
        assert [d.name for d in saves_root.iterdir() if d.is_dir()]
        backup_root = default_backup_root(saves_root)
        assert backup_root == saves_root, backup_root     # 默认：备份与原存档同一个文件夹

        # 自检时把「删除旧备份」换成直接删，避免污染回收站（只影响本进程）
        globals()["delete_to_recycle_bin"] = lambda p: shutil.rmtree(p)

        engine = BackupEngine(log=lambda m, l="info": print("   log:", m))
        for i in range(3):
            out = engine.make_backup(save, backup_root)
            assert out.is_dir(), out
            assert (out / "entity_data.bin").is_file(), out
            assert (out / "chunkdata" / "a.bin").is_file(), out
            assert (out / "players.db-journal").is_file(), out   # journal 也要原样复制
            assert count_files(out) == 4, count_files(out)
            time.sleep(1.1)

        items = engine.list_backups(backup_root)
        assert len(items) == 3, items
        assert all(b["save"] == "测试存档" for b in items), items
        assert items == sorted(items, key=lambda x: x["time"], reverse=True)

        # 保留策略：每个存档只留最近 2 份
        removed = engine.enforce_keep(backup_root, "测试存档", 2)
        assert len(removed) == 1, removed
        assert len([b for b in engine.list_backups(backup_root) if b["save"] == "测试存档"]) == 2

        # 重命名备份（只换存档名，时间戳保留）
        items = engine.list_backups(backup_root)
        ren = engine.rename_backup(items[0]["path"], "改名后的存档")
        assert ren.name.startswith("改名后的存档_"), ren
        assert ren.exists() and not items[0]["path"].exists()

        # 同一秒生成的两份备份，改名后不能互相撞名（序号必须保留）
        dup = tmp / "同秒测试"
        dup.mkdir()
        (dup / "f.bin").write_bytes(b"x" * 10)
        d1 = engine.make_backup(dup, tmp / "dupbak")
        d2 = engine.make_backup(dup, tmp / "dupbak")
        assert d2.name.endswith("_2"), d2.name
        n1 = engine.rename_backup(d1, "新名字")
        n2 = engine.rename_backup(d2, "新名字")
        assert n1.exists() and n2.exists() and n1.name != n2.name, (n1.name, n2.name)
        assert n2.name.endswith("_2"), n2.name
        print("   备份改名（含同秒序号）通过 ✔")

        # 保留清理绝对不能删掉“正在被当成存档玩”的备份
        guard = tmp / "guard"
        guard.mkdir()
        base = guard / "基础存档"
        base.mkdir()
        (base / "f.bin").write_bytes(b"x" * 32)
        for _ in range(3):
            engine.make_backup(base, guard)
            time.sleep(1.1)
        mine = [b for b in engine.list_backups(guard) if b["save"] == "基础存档"]
        assert len(mine) == 3, mine
        precious = mine[-1]["name"]            # 最旧的那份，假装玩家正在玩它
        removed = engine.enforce_keep(guard, "基础存档", 1, protect={precious})
        assert precious not in [p.name for p in removed], removed
        assert (guard / precious).is_dir(), "受保护的备份被删了！"
        assert len([b for b in engine.list_backups(guard)
                    if b["save"] == "基础存档"]) == 2, "应该只删掉 1 份"
        print("   保留清理保护“在玩的备份”通过 ✔")

        assert sanitize_save_name(" 好名字 ") == "好名字"
        for bad in ("", "a/b", "con", "x."):
            try:
                sanitize_save_name(bad)
            except ValueError:
                pass
            else:
                raise AssertionError(f"应拒绝的名字被接受：{bad!r}")

        print(f"   备份目录：{backup_root}")

        # 靠文件名区分原存档与备份
        assert BackupEngine.parse_backup_name("测试存档_20261015_143012") == \
            ("测试存档", datetime(2026, 10, 15, 14, 30, 12))
        assert BackupEngine.parse_backup_name("测试存档_20261015_143012_2")[0] == "测试存档"
        assert BackupEngine.parse_backup_name("测试存档_20261015_143012.zip")[0] == "测试存档"
        assert BackupEngine.parse_backup_name("2026-10-15_12-46-42") is None   # PZ 默认存档名，不是备份
        assert BackupEngine.parse_backup_name("快乐僵毁") is None
        assert BackupEngine.parse_backup_name("快乐僵毁 - 副本") is None
        print("   备份识别（文件名）通过 ✔")

        # 指纹：复制出来的备份与原目录一致；存档一改就不一致（用于“没变化就跳过”）
        fp_dir = tmp / "指纹测试"
        (fp_dir / "sub").mkdir(parents=True)
        (fp_dir / "sub" / "x.bin").write_bytes(b"12345")
        fp1 = fingerprint(fp_dir)
        bak = engine.make_backup(fp_dir, tmp / "fingerprints")
        assert fingerprint(bak) == fp1, (fingerprint(bak), fp1)
        time.sleep(1.1)
        (fp_dir / "sub" / "x.bin").write_bytes(b"1234567")
        assert fingerprint(fp_dir) != fp1
        print("   变化检测指纹通过 ✔")

        # 定时器：间隔生效 + 能按 first_delay 触发 + 能停下来
        hits = []
        sch = BackupScheduler()
        sch.start(interval_seconds=30, callback=lambda: hits.append(datetime.now()), first_delay=1)
        assert sch.running
        assert sch.next_run is not None
        deadline = time.time() + 8
        while not hits and time.time() < deadline:
            time.sleep(0.2)
        sch.stop()
        assert hits, "定时器未按首次延迟触发"
        assert not sch.running and sch.next_run is None

        # 到点后 next_run 置空（进入等时机/备份），备份结束 rearm() 才重新计时
        sch2 = BackupScheduler()
        fired = []
        sch2.start(interval_seconds=30, callback=lambda: fired.append(1), first_delay=1)
        deadline = time.time() + 8
        while not fired and time.time() < deadline:
            time.sleep(0.2)
        assert fired, "第二轮定时器没触发"
        assert sch2.next_run is None, "到点后应进入等待 rearm 状态"
        sch2.rearm()
        assert sch2.next_run is not None, "rearm 之后应该重新计时"
        sch2.stop()
        print("   定时器（到点→等时机→备份→重新计时）通过 ✔")
        assert (hits[0] - datetime.now()).total_seconds() < 30

        print("   全部通过 ✔")
    return 0


# --------------------------------------------------------------------------- #
def main():
    parser = argparse.ArgumentParser(
        description=f"{APP_TITLE} v{APP_VERSION}  (PZ save backup tool / 存档备份工具)")
    parser.add_argument("--selftest", action="store_true",
                        help="run the core self-test only, no GUI / 只运行核心逻辑自检，不启动界面")
    args = parser.parse_args()

    if args.selftest:
        sys.exit(selftest())

    if WIN:
        try:  # 让高分屏下界面不糊
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    root = tk.Tk()
    try:
        root.iconbitmap(str(app_dir() / "app_icon.ico"))
    except Exception:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
