@echo off
rem Run install.py with an interpreter that actually exists on this machine.
rem
rem The `python` on PATH under Windows is usually the Microsoft Store stub: it
rem prints one line, exits, and runs nothing -- so it is tried last, and only
rem after proving it can execute. Blender ships a real Python, so that is the
rem first choice and means this works with nothing installed.
setlocal enabledelayedexpansion
set "SCRIPT=%~dp0install.py"
set "PY="

rem 1. explicit override, for a Blender in a place this script won't guess
if defined BLENDER_PYTHON if exist "%BLENDER_PYTHON%" set "PY=%BLENDER_PYTHON%"

rem 2. a portable Blender unzipped onto the Desktop
if not defined PY for /d %%D in ("%USERPROFILE%\Desktop\blender-*") do (
  for /d %%V in ("%%D\*") do (
    if not defined PY if exist "%%V\python\bin\python.exe" set "PY=%%V\python\bin\python.exe"
  )
)

rem 3. an installed Blender
if not defined PY for /d %%D in ("%ProgramFiles%\Blender Foundation\Blender*") do (
  for /d %%V in ("%%D\*") do (
    if not defined PY if exist "%%V\python\bin\python.exe" set "PY=%%V\python\bin\python.exe"
  )
)

rem 4. a real Python on PATH
if not defined PY (
  python -c "pass" >nul 2>&1 && set "PY=python"
)

if not defined PY (
  echo Could not find a Python interpreter.
  echo.
  echo Point this at Blender's own, which always exists:
  echo     set BLENDER_PYTHON=C:\path\to\blender\4.5\python\bin\python.exe
  exit /b 1
)

echo Using %PY%
echo.
"%PY%" "%SCRIPT%" %*
set "CODE=%ERRORLEVEL%"

rem pause only when double-clicked, so the result is readable
echo %cmdcmdline% | find /i "%~f0" >nul && pause
exit /b %CODE%
