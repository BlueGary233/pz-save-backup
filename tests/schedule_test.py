#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""定时机制测试：到点 → 等时机 → 备份 → 重新计时

覆盖：
  · 定时到点后存档还在写 → 进入等待；等不到（超时）就放弃本轮，并把定时器重新武装
  · 存档安静下来后再到点 → 正常备份 → 完成后重新计时（next_run 从备份完成算起）
  · 手动备份不受“停止自动备份”的取消信号影响

运行（项目目录下）：
    python tests/schedule_test.py
"""
import os
import shutil
import sys
import tempfile
import threading
import time
import tkinter as tk
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pz_save_backup_gui as m  # noqa: E402

m.IDLE_WAIT_SECONDS = 6          # 缩短“等时机”上限，让测试跑得完
m.CONFIG_NAME = "config_sched.json"

tmp = Path(tempfile.mkdtemp(prefix="pz_sched_test_")).resolve()
m.config_path = lambda docs=None, program_dir=None: tmp / "config_sched.json"

saves = tmp / "Saves" / "Sandbox"
(saves / "计时测试存档" / "chunkdata").mkdir(parents=True)
(saves / "计时测试存档" / "a.bin").write_bytes(b"A" * 500_000)
(saves / "计时测试存档" / "chunkdata" / "b.bin").write_bytes(os.urandom(300_000))

results = []


def check(label, ok, extra=""):
    print(f"  {'✔' if ok else '✘'} {label}{(' — ' + str(extra)) if extra else ''}")
    results.append(bool(ok))


def pump(seconds):
    t0 = time.time()
    while time.time() - t0 < seconds:
        root.update()
        time.sleep(0.05)


def wait_idle_cycle(timeout=30):
    """等到这一轮备份（含等待）结束。"""
    t0 = time.time()
    while not app.backing_up.is_set() and time.time() - t0 < 2:
        pump(0.1)
    while app.backing_up.is_set() and time.time() - t0 < timeout:
        pump(0.1)
    pump(0.6)


root = tk.Tk()
root.withdraw()
app = m.App(root)
app.set_saves_root(saves)
app.set_backup_root(None)          # 同目录模式
app.interval_var.set("1")
app.keep_var.set("10")
app.only_when_idle_var.set(True)
app.idle_seconds_var.set("5")
app.skip_unchanged_var.set(False)
app.refresh_saves()

log_start = 0

# ---- 场景 1：到点时存档正在被写 → 等，等不到就放弃本轮并重新武装定时器 ----
print("场景 1：定时到点，但游戏一直在写这个存档")
app.backup_on_start_var.set(False)
app.start_auto()
pump(0.3)
log_start = len(app.log_text.get("1.0", "end"))

stop_writing = threading.Event()


def keep_writing():
    """模拟游戏持续写档（每隔 1 秒写一次，永远达不到 5 秒静止）。"""
    while not stop_writing.is_set():
        try:
            (saves / "计时测试存档" / "hot.bin").write_bytes(b"H" * 1000)
        except OSError:
            pass
        time.sleep(1)


threading.Thread(target=keep_writing, daemon=True).start()
pump(1.0)

before = len(app.engine.list_backups(app.backup_root))
app._on_timer()                     # 模拟定时到点
check("到点后进入等待（正在忙）", app.backing_up.is_set() or app.scheduler.next_run is None)
wait_idle_cycle(timeout=35)
stop_writing.set()
log = app.log_text.get("1.0", "end")[log_start:]
after = len(app.engine.list_backups(app.backup_root))
check("一直等不到静止 → 本轮不备份", after == before, f"{before} → {after}")
check("日志说明了放弃原因", "没等到存档静止" in log,
      [ln for ln in log.splitlines() if "等" in ln][-1:] or "（无）")
check("定时器被重新武装（不会停摆）", app.scheduler.next_run is not None)

# ---- 场景 2：存档安静了 → 正常备份 → 备份完成后重新计时 ----
print("\n场景 2：存档安静下来后到点")
old = time.time() - 120
for f in (saves / "计时测试存档").rglob("*"):
    if f.is_file():
        os.utime(f, (old, old))
app.refresh_saves()
before2 = len(app.engine.list_backups(app.backup_root))
log_start = len(app.log_text.get("1.0", "end"))
app._on_timer()
wait_idle_cycle(timeout=30)
log = app.log_text.get("1.0", "end")[log_start:]
after2 = len(app.engine.list_backups(app.backup_root))
check("安静后备份成功", after2 > before2, f"{before2} → {after2}")
check("备份结束后重新计时", app.scheduler.next_run is not None
      and app.scheduler.next_run > m.datetime.now(), app.scheduler.next_run)
check("日志里有成功记录", "备份结束：成功 1" in log,
      [ln for ln in log.splitlines() if "成功" in ln][-1:] or "（无）")

# ---- 场景 3：停止自动备份后，手动备份照样能用 ----
print("\n场景 3：停止自动备份后手动备份")
app.stop_auto()
check("停止后定时器已停", not app.scheduler.running)
(saves / "计时测试存档" / "manual.bin").write_bytes(b"M" * 1000)
for f in (saves / "计时测试存档").rglob("*"):
    if f.is_file():
        os.utime(f, (old, old))          # 假装已经安静
app.refresh_saves()
before3 = len(app.engine.list_backups(app.backup_root))
log_start = len(app.log_text.get("1.0", "end"))
app.backup_now_clicked()
wait_idle_cycle(timeout=30)
log = app.log_text.get("1.0", "end")[log_start:]
after3 = len(app.engine.list_backups(app.backup_root))
check("手动备份没有被“停止”信号取消", after3 > before3, f"{before3} → {after3}")
check("手动备份日志正常", "手动备份结束" in log,
      [ln for ln in log.splitlines() if "结束" in ln][-1:] or "（无）")

app.on_close()
shutil.rmtree(tmp, ignore_errors=True)
print("\n结果：", "全部通过 ✔" if all(results) else "存在失败 ✘")
sys.exit(0 if all(results) else 1)
