#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文件占用测试：验证游戏（或别的程序）占着存档文件时，备份会怎么表现。

场景 A：文件一直被独占占用 → 重试 4 次仍失败 → **整次备份失败**，并且把半成品清掉
        （全量备份原则：宁可没有备份，也不留一个缺文件的坏备份）。
场景 B：文件只被占用 0.3 秒（游戏写档的瞬时占用）→ 重试救回来，备份完整。

运行（项目目录下）：
    python tests/locked_file_test.py
"""
import ctypes
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pz_save_backup_gui as m  # noqa: E402

k32 = ctypes.windll.kernel32
k32.CreateFileW.restype = ctypes.c_void_p
k32.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
                            ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
k32.CloseHandle.argtypes = [ctypes.c_void_p]

GENERIC_READ = 0x80000000
OPEN_EXISTING = 3
SHARE_NONE = 0          # 独占：别的进程读不了

results = []


def check(label, ok, extra=""):
    print(f"  {'✔' if ok else '✘'} {label}{(' — ' + str(extra)) if extra else ''}")
    results.append(bool(ok))


def lock_file(path: Path):
    h = k32.CreateFileW(str(path), GENERIC_READ, SHARE_NONE, None, OPEN_EXISTING, 0, None)
    if not h or h == ctypes.c_void_p(-1).value:
        raise OSError(f"无法锁住 {path}")
    return h


def unlock(h):
    k32.CloseHandle(h)


def build_save(base: Path, name: str):
    save = base / name
    save.mkdir(parents=True, exist_ok=True)
    (save / "players.db").write_bytes(b"P" * 65536)
    return save


tmp = Path(tempfile.mkdtemp(prefix="pz_lock_test_")).resolve()
print(f"临时目录: {tmp}\n")

# ---------------- 场景 A：一直被占用 ----------------
print("场景 A：players.db 被独占占用，全程不放")
save_a = build_save(tmp / "A", "被占用存档")
h = lock_file(save_a / "players.db")
eng = m.BackupEngine(log=lambda msg, lvl="info": print(f"    [{lvl}] {msg}"))
t0 = time.time()
raised = None
try:
    eng.make_backup(save_a, tmp / "BackupsA")
except Exception as exc:
    raised = exc
elapsed_a = time.time() - t0
unlock(h)

check("整次备份失败（不是悄悄跳过这个文件）", isinstance(raised, OSError), type(raised).__name__)
check("错误信息指出是哪个文件被占用",
      raised is not None and "players.db" in str(raised), str(raised)[:80])
check("重试确实等过（耗时 ≥ 1.4s）", elapsed_a >= 1.4, f"{elapsed_a:.2f}s")
leftovers = list((tmp / "BackupsA").iterdir()) if (tmp / "BackupsA").is_dir() else []
check("没有留下半成品备份（全量原则）", leftovers == [], [p.name for p in leftovers])

# ---------------- 场景 B：只占用 0.3 秒 ----------------
print("\n场景 B：players.db 被占用 0.3 秒后释放（模拟游戏写档瞬间）")
save_b = build_save(tmp / "B", "瞬时占用存档")
h = lock_file(save_b / "players.db")


def release_later():
    time.sleep(0.3)
    unlock(h)


threading.Thread(target=release_later, daemon=True).start()
eng2 = m.BackupEngine()
t0 = time.time()
out_b = eng2.make_backup(save_b, tmp / "BackupsB")
elapsed_b = time.time() - t0

check("备份完成", out_b.is_dir())
check("文件内容完整", (out_b / "players.db").is_file()
      and (out_b / "players.db").stat().st_size == 65536)
check("耗时说明重试生效（≥0.2s）", elapsed_b >= 0.2, f"{elapsed_b:.2f}s")

# ---------------- 场景 C：备份期间源被写入 → 作废 ----------------
print("\n场景 C：备份途中源存档被写入（模拟游戏正好在保存）")
save_c = build_save(tmp / "C", "边写边备份存档")
for i in range(50):                      # 弄得大一点，让复制过程有足够时间被打断
    (save_c / f"chunk{i}.bin").write_bytes(b"C" * 200_000)
eng3 = m.BackupEngine()
raised_c = None


def tamper_c():
    time.sleep(0.05)
    (save_c / "during.bin").write_bytes(b"D" * 100_000)


threading.Thread(target=tamper_c, daemon=True).start()
try:
    eng3.make_backup(save_c, tmp / "BackupsC")
except m.SaveChangedDuringBackup as exc:
    raised_c = exc
except Exception as exc:                 # 也可能因为别的 OSError 失败，这里只关心“不产出坏备份”
    raised_c = exc

check("备份期间源被写入 → 抛 SaveChangedDuringBackup",
      isinstance(raised_c, m.SaveChangedDuringBackup), type(raised_c).__name__)
leftovers_c = list((tmp / "BackupsC").iterdir()) if (tmp / "BackupsC").is_dir() else []
check("作废的备份被清掉了", leftovers_c == [], [p.name for p in leftovers_c])

shutil.rmtree(tmp, ignore_errors=True)
print("\n结果：", "全部通过 ✔" if all(results) else "存在失败 ✘")
print("临时目录已清理:", tmp)
sys.exit(0 if all(results) else 1)
