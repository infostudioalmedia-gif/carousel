@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0app"
echo ===== فحص النظام قبل التشغيل =====
python selftest.py
if errorlevel 1 (
  echo.
  echo الفحص فشل - راجع الأسطر اللي عليها علامة X فوق، وابعتها لمن يدعمك.
  pause
  exit /b 1
)
set ROOYA_PRECHECKED=1
echo.
echo سيستم كاروسيل رؤية - http://localhost:8765
start "" http://localhost:8765
python server.py
if errorlevel 1 pause
