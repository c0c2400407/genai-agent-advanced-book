@echo off
cd /d "%~dp0"
if not exist ".venv-secure\Scripts\pythonw.exe" (
  echo Python environment not found. See workshop\README.md.
  pause
  exit /b 1
)
start "" ".venv-secure\Scripts\pythonw.exe" -m workshop gui
