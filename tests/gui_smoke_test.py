#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GUI 冒烟测试：在临时目录里跑一遍关键链路，不碰真实存档。

覆盖：
  · 自动备份启动 / 立即备份按钮
  · 备份文件夹生成（含子目录、journal 也复制）
  · 保留份数自动清理
  · 勾选 / 取消勾选、重命名存档、删除存档（回收站）
  · 同目录模式：备份与原存档并排，且**不会被误当成存档**
  · 按存档名分类归纳（备份下拉 / 每份备份的归属）
  · 变化检测：存档没变就跳过，变了才备份

运行（项目目录下）：
    python tests/gui_smoke_test.py
"""
import os
import shutil
import sys
import tempfile
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pz_save_backup_gui as m  # noqa: E402

m.CONFIG_NAME = "config_smoke.json"      # 独立配置，不动用户设置
m.config_path = lambda docs=None, program_dir=None: tmp / "config_smoke.json"  # 别写进文档目录

tmp = Path(tempfile.mkdtemp(prefix="pz_gui_smoke_")).resolve()
saves = tmp / "Saves" / "Sandbox"          # 期望的“同目录”备份位置
(saves / "冒烟测试存档" / "chunkdata").mkdir(parents=True)
(saves / "冒烟测试存档" / "a.bin").write_bytes(os.urandom(2_000_000))
(saves / "冒烟测试存档" / "players.db-journal").write_bytes(b"")
(saves / "第二个存档").mkdir()
(saves / "第二个存档" / "c.bin").write_bytes(os.urandom(300_000))
custom_backups = tmp / "CustomBackups"     # 第一阶段先用自定义目录跑基础链路

results = []
before_count = 0          # 供「变化检测」几个步骤共用


def check(label, ok, extra=""):
    print(f"  {'✔' if ok else '✘'} {label}{(' — ' + str(extra)) if extra else ''}")
    results.append(bool(ok))


def run_backup(next_step, timeout_ms=20000):
    """等上一次备份收尾 → 触发一次备份 → 等它真的结束 → 进入下一步。

    （固定 sleep 遇到偶发卡顿会误判，这里改成轮询状态。）
    """
    if app.backing_up.is_set():
        root.after(400, lambda: run_backup(next_step, timeout_ms))
        return
    app.backup_now_clicked()
    t0 = time.time()

    def poll():
        elapsed = (time.time() - t0) * 1000
        if app.backing_up.is_set() and elapsed < timeout_ms:
            root.after(400, poll)
        else:
            root.after(300, next_step)

    root.after(400, poll)


def dig(tree):
    return list(tree.get_children())


def step_basic():
    log = app.log_text.get("1.0", "end")
    items = app.engine.list_backups(custom_backups)
    check("自动备份已启动", app.scheduler.running)
    check("两个存档都备份了", len(items) == 2, [i["name"] for i in items])
    check("状态栏有倒计时", "下次备份" in app.next_label.cget("text"), app.next_label.cget("text"))
    run_backup(step_basic2)


def step_basic2():
    log = app.log_text.get("1.0", "end")
    check("立即备份按钮生效", "手动备份结束：成功 2，失败 0" in log)

    per = {}
    for it in app.engine.list_backups(custom_backups):
        per[it["save"]] = per.get(it["save"], 0) + 1
    check("保留策略自动清理（keep=1）", all(v == 1 for v in per.values()) and "清理旧备份" in log, per)

    # 认准「冒烟测试存档」的备份来验（另一个存档里没有 chunkdata，挑错对象会误判）
    folder = next((b for b in app.engine.list_backups(custom_backups)
                   if b["save"] == "冒烟测试存档"), None)
    check("备份是文件夹形式", folder is not None and folder["path"].is_dir())
    if folder:
        check("备份内容完整（子目录 + journal 都在）",
              (folder["path"] / "a.bin").is_file()
              and (folder["path"] / "chunkdata").is_dir()
              and (folder["path"] / "players.db-journal").is_file())

    app.stop_auto()
    check("停止自动备份", not app.scheduler.running)

    # 勾选切换
    app.saves_tree.selection_set(["冒烟测试存档"])
    app._toggle_current_check()
    check("切换勾选生效", "冒烟测试存档" not in app.checked, sorted(app.checked))
    app._toggle_current_check()
    check("再次切换恢复勾选", "冒烟测试存档" in app.checked)

    # 重命名存档
    m.simpledialog.askstring = lambda *a, **k: "改过名的存档"
    m.messagebox.askyesno = lambda *a, **k: True
    app.saves_tree.selection_set(["冒烟测试存档"])
    app.rename_save()
    check("重命名存档：目录真的改了",
          (saves / "改过名的存档").is_dir() and not (saves / "冒烟测试存档").exists())
    check("存档改名后，它的备份也改名了",
          any(b["save"] == "改过名的存档" for b in app.engine.list_backups(custom_backups)),
          [b["name"] for b in app.engine.list_backups(custom_backups)])
    check("没有留下认不到主人的孤儿备份",
          not any(b["save"] == "冒烟测试存档" for b in app.engine.list_backups(custom_backups)),
          [b["name"] for b in app.engine.list_backups(custom_backups)])
    check("重命名后勾选状态跟着走", "改过名的存档" in app.checked, sorted(app.checked))

    # 右键菜单 / 双击
    labels = []
    for i in range(app.saves_menu.index("end") + 1):
        if app.saves_menu.type(i) != "separator":
            labels.append(app.saves_menu.entrycget(i, "label"))
    check("存档右键菜单含重命名/删除", "重命名存档…" in labels and "删除存档…" in labels)
    check("双击绑定存在", bool(app.saves_tree.bind("<Double-1>")))
    check("备份区右键菜单存在", app.backup_menu.index("end") is not None)

    # 删除存档
    real_delete = m.delete_to_recycle_bin
    m.delete_to_recycle_bin = lambda p: shutil.rmtree(p)
    app.saves_tree.selection_set(["第二个存档"])
    app.delete_save()
    m.delete_to_recycle_bin = real_delete
    check("删除存档：目录已删除", not (saves / "第二个存档").exists())
    check("删除后勾选状态同步", "第二个存档" not in app.checked, sorted(app.checked))

    junk = tmp / "recycle_test.txt"
    junk.write_text("test", encoding="utf-8")
    try:
        m.delete_to_recycle_bin(junk)
        check("delete_to_recycle_bin 可用（文件已移走）", not junk.exists())
    except Exception as exc:
        check("delete_to_recycle_bin 可用", False, exc)

    # ---- 切到同目录模式 ----
    app.set_backup_root(None)        # same_as_saves
    app.refresh_saves()
    check("备份位置已切到同目录", app.backup_root == saves, app.backup_root)
    app.skip_unchanged_var.set(False)
    run_backup(step_same_folder)


def step_same_folder():
    global before_count
    app.keep_var.set("10")          # 保留策略已在前面验证过，这里调大让计数直观
    log = app.log_text.get("1.0", "end")
    entries = sorted(d.name for d in saves.iterdir() if d.is_dir())
    backups = [n for n in entries if m.BackupEngine.parse_backup_name(n)]
    saves_only = [n for n in entries if not m.BackupEngine.parse_backup_name(n)]
    check("备份确实生成在存档目录里", bool(backups), backups)
    check("同一目录里能区分出原存档", saves_only == ["改过名的存档"], saves_only)
    check("存档列表不把备份当存档",
          [s["name"] for s in app.saves] == ["改过名的存档"], [s["name"] for s in app.saves])

    bs = app.backups_by_save.get("改过名的存档", [])
    check("备份按存档名归类到 backups_by_save", len(bs) >= 1, [b["name"] for b in bs])
    check("存档列表显示备份份数",
          app.saves_tree.set("改过名的存档", "backups").endswith("份"),
          app.saves_tree.set("改过名的存档", "backups"))

    combo_values = list(app.backup_view_combo.cget("values"))
    check("下拉列表=原存档（不含备份）", combo_values == ["改过名的存档"], combo_values)
    app.backup_view_var.set("改过名的存档")
    app._refresh_save_backups()
    check("备份区列出该存档的备份", len(dig(app.save_backups_tree)) == len(bs),
          dig(app.save_backups_tree))

    # ---- 变化检测 ----
    before_count = len(app.engine.list_backups(app.backup_root))
    app.skip_unchanged_var.set(True)
    run_backup(step_unchanged)


def step_unchanged():
    log = app.log_text.get("1.0", "end")
    after_count = len(app.engine.list_backups(app.backup_root))
    check("存档没变化 → 跳过，不新增备份",
          "没有变化，跳过" in log and after_count == before_count,
          f"{before_count} → {after_count}")

    # 改一下存档，再备份 → 这次应该真的备份
    (saves / "改过名的存档" / "new_chunk.bin").write_bytes(b"N" * 1234)
    run_backup(step_changed)


def step_changed():
    log = app.log_text.get("1.0", "end")
    after_count = len(app.engine.list_backups(app.backup_root))
    check("存档有变化 → 真的备份了一份",
          after_count > before_count and "备份结束：成功 1" in log,
          f"{before_count} → {after_count}")

    # ---- 不需要手动选存档：全排除也照样监控全部 ----
    app.skip_unchanged_var.set(False)
    app.select_none()
    check("先把监控全部排除", not app.checked, sorted(app.checked))
    run_backup(step_noselect)


def step_noselect():
    log = app.log_text.get("1.0", "end")
    check("没勾任何存档时自动恢复为监控全部",
          len(app.checked) == len(app.saves) and len(app.saves) > 0,
          f"{len(app.checked)}/{len(app.saves)}")
    check("而且真的备份了", "备份结束：成功 1" in log)
    root.after(300, step_played)


def step_played():
    """玩家拿一个旧备份继续玩 → 它要变回“存档”，并且能被继续备份。"""
    from datetime import timedelta
    old_stamp = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d_%H%M%S")
    played = saves / f"改过名的存档_{old_stamp}"
    shutil.copytree(saves / "改过名的存档", played)
    (played / "a.bin").write_bytes(b"PLAYED-ON" * 100)      # 游戏继续写这个存档

    app.refresh_saves()
    names = [s["name"] for s in app.saves]
    check("被继续玩的备份回到存档列表", played.name in names, names)
    row = next((s for s in app.saves if s["name"] == played.name), None)
    check("标成了“从备份继续玩”", bool(row and row["from_backup"]))
    check("它被自动勾选（会参与备份）", played.name in app.checked, sorted(app.checked))
    check("它不再算作备份记录",
          played.name not in [b["name"] for b in app.engine.list_backups(app.backup_root)
                              if b["name"] == played.name] or
          played.name not in [i["name"] for i in app.backup_items],
          [i["name"] for i in app.backup_items])

    app.saves_tree.selection_set([played.name])
    run_backup(step_played2)


def step_played2():
    log = app.log_text.get("1.0", "end")
    kids = [b for b in app.engine.list_backups(app.backup_root)
            if b["save"].startswith("改过名的存档_") or b["save"] == "改过名的存档"]
    nested = [b for b in kids if b["save"].startswith("改过名的存档_")]
    check("玩起来的备份也能被备份（生成了它的备份）", bool(nested), [b["name"] for b in nested])
    root.after(300, step_idle)


def count_backups():
    return len(app.engine.list_backups(app.backup_root))


# ---- 静止保护：正在被写入就不备份 ----
def step_idle():
    app.only_when_idle_var.set(True)
    app.idle_seconds_var.set("5")
    app.skip_unchanged_var.set(False)
    (saves / "改过名的存档" / "just_written.bin").write_bytes(b"HOT" * 100)   # 模拟游戏刚写过
    app.refresh_saves()
    global before_idle
    before_idle = count_backups()
    run_backup(step_idle2)


def step_idle2():
    log = app.log_text.get("1.0", "end")
    after = count_backups()
    check("存档正在被写入 → 本轮不备份",
          "正在被写入" in log and "本轮不备份" in log and after == before_idle,
          f"{before_idle} → {after}")

    # 把文件时间调老（模拟游戏停下、回到主菜单）
    old = time.time() - 60
    for f in (saves / "改过名的存档").rglob("*"):
        if f.is_file():
            os.utime(f, (old, old))
    app.refresh_saves()
    run_backup(step_idle3)


def step_idle3():
    after = count_backups()
    check("存档静止后正常备份", after > before_idle, f"{before_idle} → {after}")
    root.after(300, step_write_during)


# ---- 备份途中源被写入 → 这次备份作废、不留残次品 ----
def step_write_during():
    """在复制进行中修改源存档（用 progress 钩子保证命中时机）。"""
    global before_tamper
    before_tamper = count_backups()
    names_before = {p.name for p in saves.iterdir()}
    src = saves / "改过名的存档"
    eng = m.BackupEngine()
    fired = {"done": False}

    def tamper_progress(i, total, done_bytes, total_bytes, cur):
        if not fired["done"]:
            fired["done"] = True
            (src / "sneaky.bin").write_bytes(b"X" * 200_000)      # 复制途中游戏正好在写档

    raised = None
    try:
        eng.make_backup(src, app.backup_root, progress=tamper_progress)
    except Exception as exc:
        raised = exc

    after = count_backups()
    leftovers = {p.name for p in saves.iterdir()} - names_before
    check("备份途中源被写入 → 这次备份作废",
          isinstance(raised, m.SaveChangedDuringBackup), type(raised).__name__)
    check("作废的备份没有留在目录里（不留残次品）",
          after == before_tamper
          and not any(m.BackupEngine.parse_backup_name(n) for n in leftovers),
          f"{before_tamper} → {after}，残留 {sorted(leftovers)}")

    app.on_close()
    print("结果：", "全部通过 ✔" if all(results) else "存在失败 ✘")
    sys.exit(0 if all(results) else 1)


root = tk.Tk()
root.withdraw()
app = m.App(root)
app.set_saves_root(saves)
app.set_backup_root(custom_backups)      # 第一阶段：自定义目录
app.interval_var.set("1")
app.keep_var.set("1")
app.backup_on_start_var.set(True)
app.skip_unchanged_var.set(False)
app.only_when_idle_var.set(False)     # 基础链路先关掉静止门槛（测试里文件都是刚写的）
app.start_auto()
root.after(12000, step_basic)
root.mainloop()
