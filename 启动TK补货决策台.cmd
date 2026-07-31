@echo off
chcp 65001 >nul
cd /d "%~dp0"
python run_webapp.py
if errorlevel 1 (
  echo.
  echo 启动失败，请确认 Python 以及 requirements.txt 中的依赖已安装。
  pause
)
