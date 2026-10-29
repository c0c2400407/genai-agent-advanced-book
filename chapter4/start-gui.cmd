@echo off
cd /d "%~dp0"
set "APP_PYTHON="
for %%E in (.venv venv .venv-secure) do (
  if exist "%%E\Scripts\python.exe" if exist "%%E\Scripts\pythonw.exe" (
    "%%E\Scripts\python.exe" -c "from src.security import ensure_runtime; ensure_runtime(); import tkinter" >nul 2>&1
    if not errorlevel 1 (
      set "APP_PYTHON=%%E\Scripts\pythonw.exe"
      goto launch
    )
  )
)
echo Compatible Python environment not found.
echo See workshop\INSTALL_WINDOWS.md to create a new environment and install requirements.txt.
if /i not "%~1"=="--check" pause
exit /b 1

:launch
if /i "%~1"=="--check" (
  echo Selected Python: %APP_PYTHON%
  exit /b 0
)
start "" "%APP_PYTHON%" -m workshop gui
