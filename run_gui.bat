@echo off
cd /d "%~dp0"
echo 启动 PZ 存档备份工具...
python pz_save_backup_gui.py
if errorlevel 1 pause
