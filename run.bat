@echo off
setlocal
cd /d "%~dp0"
if "%~1"=="" (
  echo Starting the server. Open http://127.0.0.1:8000/app after "startup complete" appears.
  echo Keep this window open; close it to stop the server.
  ".venv\Scripts\python.exe" -m persian_ocr serve
) else (
  ".venv\Scripts\python.exe" -m persian_ocr %*
)
if errorlevel 1 pause
