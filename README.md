# PZ Save Backup

Backup tool for Project Zomboid saves. Plain Python + tkinter, **zero third-party runtime dependencies**.
Bilingual UI (English / 中文) — switch it in the top-right corner.

[中文说明](README.zh-CN.md)

## What it does

Copies a save **into the same folder as the original**, side by side, with a timestamped name:

```
%USERPROFILE%\Zomboid\Saves\Sandbox\
├─ MySave\                              ← your save
├─ MySave_20261015_140620\              ← backup #1
├─ MySave_20261015_161205\              ← backup #2
└─ AnotherSave\
```

To restore, copy a backup folder back and drop the `_<timestamp>` suffix — no unzip needed.

## How backups are recognised

By file name:

* `<save name>_YYYYMMDD_HHMMSS` → a backup
* duplicates within the same second get `_2`, `_3`, …
* anything else → a save (PZ's default save name `2026-10-15_12-46-42` uses dashes, so it is **not** mistaken for a backup)

**Important exception**: if a backup folder is loaded and played, it becomes a save again — it shows up in the
save list (highlighted orange, "a backup being played"), is monitored automatically, and gets backed up like any
other save (its backups are named `<backup>_<old timestamp>_<new timestamp>`).

Two independent signals decide this:

| Signal | Meaning |
| --- | --- |
| `Zomboid\latestSave.ini` first line | the save the game loaded last — authoritative; works even for a brand-new backup you start playing immediately |
| file mtime newer than the folder's timestamp | the folder was written to after it was created (+60 s tolerance) |

A pristine backup matches neither, so it is never mistaken for a save. Timestamps in the future (clock skew,
files copied from another machine) do not count as evidence either.

**Renaming follows through**: renaming a save renames all of its backups too (timestamps and `_2` suffixes kept),
so they never become orphaned.

## How automatic backup works

Every N minutes (1–1440, configurable) the timer fires, then:

1. **Wait for a quiet moment** — every monitored save is checked; if files were written less than "idle seconds"
   ago (default 5 s), it waits and re-checks every 2 s for up to 180 s. Writing a backup while the game is
   saving can **corrupt the save**, so this tool refuses to touch a busy save.
2. **Fingerprint compare** — new files / total bytes / latest mtime against the most recent backup; unchanged
   saves are skipped.
3. **Full copy** — every file, no exceptions; if any file can't be read the whole backup fails (**never leaves a
   partial backup**).
4. **Void if the source changed during the copy** — the source fingerprint is checked again afterwards; if it
   moved, the new copy is deleted (a half-old/half-new backup is exactly what corrupts a save on restore).
5. **Re-arm** — the timer restarts only after the backup finishes.

This is why backing up while playing is safe: the tool simply waits until the game goes quiet.

You don't need to pick saves — all of them are monitored; a newly appearing save (including an old backup you
started playing) joins automatically. Click a row to exclude it (☐).

The right-hand panel shows live state: green "Save idle for Xs — safe to back up" / orange "⚠ Writing now…".

## Features

| Feature | Notes |
| --- | --- |
| Scheduled backup | Interval 1–1440 min; waits for idle, re-arms after completion |
| Write protection | Never copies while the save is being written; discards a copy if the source changed mid-copy |
| Change detection | Skips unchanged saves (file count / total bytes / newest mtime) |
| Full backup | All-or-nothing: a single unreadable file fails the whole backup, no partial copies |
| Save selection | All saves monitored by default; click to exclude; new saves join automatically |
| Rename save | Double-click, context menu or the button; **all its backups are renamed too** |
| Delete save | Moved to the Recycle Bin (restorable) with confirmation |
| Grouped history | Each save shows its backup count; a dropdown lists that save's backups |
| Zero hard-coded paths | Save folder auto-detected via `latestSave.ini` / `Saves`, editable, stored in config |
| Retention | Keep the newest N backups per save (0 = keep all); **backups being played are never deleted** |
| Integrity check | File count verified after copying; 4 retries per locked file |
| Legacy support | Older `.zip` backups are still listed (marked "legacy zip") |

## UI

Default window 640×520, resizable. Tab buttons sit right beside the title.

**Backups** (main page)

* Top-left: save list — `☑` monitored, click to toggle, "Backups" column shows how many copies each save has;
  orange rows are backups being played
* Bottom-left: backups of the selected save — dropdown to switch saves, double-click to open in Explorer,
  right-click to rename/delete
* Right: interval, `▶ Start` / `⏱ Back up now`, save actions (rename/delete), countdown and idle indicator

**Advanced**

* Backup folder (same folder by default; can be changed / reset)
* Retention count, "back up once on start", "only when idle" (+ idle seconds), "skip unchanged"
* Bulk actions: monitor all / exclude all / rename / delete / open folder / refresh
* Backup history (left) and log (right), side by side

## Quick start

```bat
python pz_save_backup_gui.py     :: run it
run_gui.bat                      :: or double-click
```

Self-tests (all run in temp folders, they never touch your real saves):

```bat
python pz_save_backup_gui.py --selftest
python tests\gui_smoke_test.py      :: UI flow: grouping, change detection, played backups, idle guard
python tests\schedule_test.py       :: timer: fire → wait for idle → backup → re-arm
python tests\locked_file_test.py    :: locked files / writing during a copy
python tests\config_test.py         :: config location, migration, save failures
python tests\i18n_test.py           :: bilingual strings, live language switch, persistence
```

## Build an exe (Nuitka)

```bat
pip install nuitka Pillow zstandard
python create_icon.py             :: optional: generate app_icon.ico
python build_nuitka.py            :: one-file exe
python build_nuitka.py --onedir   :: folder build (starts faster)
python build_nuitka.py --no-test  :: don't launch it after building
```

Output: `dist_nuitka\PZ存档备份工具.exe`

**Troubleshooting** — `Failed unexpectedly in Scons C backend compilation` usually means no C compiler was
found. Nuitka downloads MinGW64 automatically with `--assume-yes-for-downloads`; if that fails, install
Visual Studio Build Tools (Desktop C++) or run `python -m nuitka --mingw64 ...`.

## Files

```
pz_save_backup_gui.py   main program (GUI + engine + scheduler + self-test)
build_nuitka.py         Nuitka build script
create_icon.py          generates app_icon.ico in pure code
run_gui.bat             one-click launcher
tests/                  self-tests
README.zh-CN.md         Chinese readme
```

**Config file location** (not next to the exe, so a read-only install folder is fine):

```
%USERPROFILE%\Documents\PZSaveBackup\config.json
```

* Windows "Documents" is resolved through the shell API, so OneDrive-redirected setups work
* An old `config.json` next to the exe/script is migrated automatically on first run
* If the Documents folder is unwritable it falls back to the program folder and **reports the error** in the log

```json
{
  "saves_root": "C:\\Users\\<you>\\Zomboid\\Saves\\Sandbox",
  "backup_root": "",
  "backup_mode": "same_as_saves",
  "interval_minutes": 30,
  "keep_count": 10,
  "backup_on_start": true,
  "skip_unchanged": true,
  "only_when_idle": true,
  "idle_seconds": 5,
  "language": "en",
  "selected_saves": null,
  "window_geometry": ""
}
```

## Restoring

1. Close the game.
2. Find the backup folder, e.g. `MySave_20261015_140620`.
3. Either copy it and strip the `_20261015_140620` suffix (rename the current save first), or copy its contents
   over the original save folder.
4. Start the game — the save is back.

## Notes

* Because backups live in the same folder, **the game also lists them as saves**. That's inherent to
  "same folder" mode — don't open one by accident.
* Backups are full copies (no compression), so they take as much space as the save itself; use the retention
  setting.
* Deleting saves/backups goes to the Recycle Bin — recoverable.
* Don't rename backup folders by hand into something else, or the tool will treat them as saves.

## License

MIT — see [LICENSE](LICENSE).
