#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""配置文件相关测试：位置、迁移、读写、写失败要报错（不能静默）

运行（项目目录下）：
    python tests/config_test.py
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pz_save_backup_gui as m  # noqa: E402

results = []


def check(label, ok, extra=""):
    print(f"  {'✔' if ok else '✘'} {label}{(' — ' + str(extra)) if extra else ''}")
    results.append(bool(ok))


tmp = Path(tempfile.mkdtemp(prefix="pz_cfg_test_")).resolve()

# 1. 能拿到系统「文档」目录
docs = m.documents_dir()
print(f"  系统文档目录：{docs}")
check("能定位到文档目录", docs is not None and docs.is_dir())

# 2. 默认路径应落在 文档\PZSaveBackup\config.json
if docs:
    p = m.config_path()
    expected_dir = docs / m.CONFIG_DIR_NAME
    check("默认配置放在 文档\\PZSaveBackup\\ 下",
          p.parent == expected_dir, str(p))
    check("配置文件夹已自动创建", expected_dir.is_dir())

# 3. 迁移：程序目录有老 config.json，新位置没有 → 应该搬过去
prog = tmp / "prog"
docs2 = tmp / "docs"
prog.mkdir()
(docs2 / "docs").mkdir(parents=True)
(docs2).mkdir(exist_ok=True)
(docs2 / "dummy").write_text("", encoding="utf-8")
(old_path := prog / "config.json").write_text(
    json.dumps({"interval_minutes": 7, "keep_count": 3}), encoding="utf-8")
new_path = m.config_path(docs=docs2, program_dir=prog)
check("路径指向 文档\\PZSaveBackup\\config.json",
      new_path == docs2 / m.CONFIG_DIR_NAME / "config.json", str(new_path))
check("老配置被自动迁移过来", new_path.is_file(), str(new_path))
cfg = m.Config(new_path)
check("迁移后设置还在", cfg.get("interval_minutes") == 7 and cfg.get("keep_count") == 3,
      f"interval={cfg.get('interval_minutes')} keep={cfg.get('keep_count')}")

# 4. 已存在的新配置不会被老配置覆盖
cfg.set("interval_minutes", 99)
cfg.save()
m.config_path(docs=docs2, program_dir=prog)
cfg2 = m.Config(new_path)
check("重复启动不会用老配置覆盖新配置", cfg2.get("interval_minutes") == 99,
      cfg2.get("interval_minutes"))

# 5. 读写往返
rt = tmp / "roundtrip" / "config.json"
errs = []
c = m.Config(rt, on_error=errs.append)
c.set("interval_minutes", 15)
c.set("skip_unchanged", False)
ok = c.save()
c3 = m.Config(rt)
check("保存成功且父目录自动创建", ok and rt.is_file(), str(rt))
check("重新读取内容一致",
      c3.get("interval_minutes") == 15 and c3.get("skip_unchanged") is False)

# 6. 未知字段不写入（防止配置被污染）
c.set("some_unknown", 1)
c.save()
check("未声明的字段不会落盘", "some_unknown" not in json.loads(rt.read_text(encoding="utf-8")))

# 7. 写失败必须报错，不能静默
blocker = tmp / "blocker"
blocker.write_text("x", encoding="utf-8")           # 拿文件当目录用
errs2 = []
c4 = m.Config(blocker / "config.json", on_error=errs2.append)
ok4 = c4.save()
check("写不进去时 save() 返回 False", ok4 is False)
check("并且把错误报出来（不静默）", len(errs2) == 1, errs2)

# 8. 文档目录不可用时退回程序目录（拿文件当目录用，mkdir 必然失败）
prog2 = tmp / "prog2"
prog2.mkdir()
blocker2 = tmp / "not_a_dir.txt"
blocker2.write_text("x", encoding="utf-8")
p2 = m.config_path(docs=blocker2, program_dir=prog2)
check("文档目录不可用时退回程序目录", p2 == prog2 / "config.json", str(p2))

import shutil  # noqa: E402
shutil.rmtree(tmp, ignore_errors=True)
print("结果：", "全部通过 ✔" if all(results) else "存在失败 ✘")
sys.exit(0 if all(results) else 1)
