@echo off
title Askateroov Launcher
rem ============================================================
rem  Askateroov - MediaTek device management suite
rem  This launcher is ASCII-only on purpose: cmd.exe mis-parses
rem  batch files that contain non-ASCII text (Hebrew etc).
rem  The Hebrew portable-python path is resolved inside the app,
rem  here we only use the safe short 8.3 path:
rem    DOWNLO~1 = Downloads      8106~1 = (Hebrew-named folder)
rem ============================================================
setlocal
set "PYDIR=C:\Users\karnaf\DOWNLO~1\8106~1\MTKCliantPortable\MTKCliantPortable"

if not exist "%PYDIR%\python.exe" (
  echo [ERROR] Portable python.exe not found at:
  echo         %PYDIR%
  echo Fix: edit this .bat and set PYDIR to the real path.
  pause
  exit /b 1
)

cd /d "%~dp0"
"%PYDIR%\python.exe" "%~dp0run.py" %*

echo.
if errorlevel 1 (
  echo [ERROR] Askateroov exited with an error. Screenshot this window and send it for review.
) else (
  echo Askateroov closed normally. You can close this window.
)
pause
endlocal
