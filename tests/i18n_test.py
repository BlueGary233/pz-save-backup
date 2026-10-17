#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""双语测试：tr() 翻译、语言切换（运行时重建界面）、选择持久化

运行（项目目录下）：
    python tests/i18n_test.py
"""
import json
import shutil
import sys
import tempfile
import tkinter as tk
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pz_save_backup_gui as m  # noqa: E402

results = []


def check(label, ok, extra=""):
    print(f"  {'✔' if ok else '✘'} {label}{(' — ' + str(extra)) if extra else ''}")
    results.append(bool(ok))


tmp = Path(tempfile.mkdtemp(prefix="pz_i18n_test_")).resolve()
m.config_path = lambda docs=None, program_dir=None: tmp / "config.json"

saves = tmp / "Saves" / "Sandbox"
(saves / "双语测试存档").mkdir(parents=True)
(saves / "双语测试存档" / "a.bin").write_bytes(b"A" * 1024)

# ---------- 1. tr() 基本行为 ----------
m.set_lang("zh")
check("中文模式返回原文", m.tr("存档目录") == "存档目录")
check("中文模式模板正常", m.tr("已备份 {0} 份", 3) == "已备份 3 份")

m.set_lang("en")
check("英文模式命中词表", m.tr("存档目录") == "Save folder", m.tr("存档目录"))
check("英文模式模板带参数正常",
      m.tr("✔ {0} → {1}（{2}，{3}s）", "a", "b", "1 MB", "0.5") == "✔ a → b (1 MB, 0.5s)",
      m.tr("✔ {0} → {1}（{2}，{3}s）", "a", "b", "1 MB", "0.5"))
check("词表缺失时回退中文（不崩）", m.tr("这条没翻译") == "这条没翻译")

# ---------- 2. 运行时切换语言（重建界面） ----------
m.set_lang("zh")


def all_texts(widget):
    out = []
    for w in widget.winfo_children():
        try:
            out.append(str(w.cget("text")))
        except tk.TclError:
            pass
        out += all_texts(w)
    return out


root = tk.Tk()
root.withdraw()
app = m.App(root)
app.set_saves_root(saves)
app.refresh_saves()
root.update()

zh_texts = all_texts(root)
check("启动是中文界面", "存档目录" in zh_texts and "自动备份" in zh_texts,
      [t for t in zh_texts if t in ("存档目录", "Save folder")])

app.apply_language("en")
root.update()
en_texts = all_texts(root)
check("切换到英文后界面变英文",
      "Save folder" in en_texts and "Auto backup" in en_texts, 
      [t for t in en_texts if t in ("存档目录", "Save folder")])
check("切换到英文后没有残留中文标签",
      not any(t == "存档目录" for t in en_texts), [t for t in en_texts if t == "存档目录"])
check("窗口标题跟着翻译", "PZ Save Backup" in root.title(), root.title())
check("语言选择写进配置", app.cfg.get("language") == "en", app.cfg.get("language"))

app.apply_language("zh")
root.update()
back_texts = all_texts(root)
check("切回中文正常", "存档目录" in back_texts and app.cfg.get("language") == "zh")

# ---------- 3. 配置持久化（重开还是上次的语言） ----------
app.cfg.set("language", "en")
app.cfg.save()
app.on_close()
saved = json.loads((tmp / "config.json").read_text(encoding="utf-8"))
check("语言被保存到配置文件", saved.get("language") == "en", saved.get("language"))

root2 = tk.Tk()
root2.withdraw()
app2 = m.App(root2)
root2.update()
texts2 = all_texts(root2)
check("重新打开后仍是英文", "Save folder" in texts2, app2.lang_code)
app2.on_close()

shutil.rmtree(tmp, ignore_errors=True)
print("\n结果：", "全部通过 ✔" if all(results) else "存在失败 ✘")
sys.exit(0 if all(results) else 1)
