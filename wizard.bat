@echo off
rem Building wizard: a shapefile of footprints in, a folder of FBX models out.
rem
rem   wizard.bat --shp C:\data\buildings.shp --out C:\data\models
rem   wizard.bat --shp ... --out ... --limit 5 --dry-run
rem   wizard.bat --shp ... --out ... --full --points
rem
rem Blender is found the same way install.bat finds it. The .blend must be one
rem that contains Buildify's node group -- that is where the modifier lives.
setlocal enabledelayedexpansion
set "SCRIPT=%~dp0building_wizard.py"
set "BLENDER=%BLENDER_EXE%"
set "SCENE=%BUILDIFY_BLEND%"

if not defined BLENDER for /d %%D in ("%USERPROFILE%\Desktop\blender-*") do (
  if not defined BLENDER if exist "%%D\blender.exe" set "BLENDER=%%D\blender.exe"
)
if not defined BLENDER for /d %%D in ("%ProgramFiles%\Blender Foundation\Blender*") do (
  if not defined BLENDER if exist "%%D\blender.exe" set "BLENDER=%%D\blender.exe"
)
if not defined BLENDER (
  echo Could not find blender.exe.
  echo     set BLENDER_EXE=C:\path\to\blender.exe
  exit /b 1
)

if not defined SCENE set "SCENE=%USERPROFILE%\Downloads\buildify_1.0.blend"
if not exist "%SCENE%" (
  echo Could not find the Buildify .blend at "%SCENE%".
  echo     set BUILDIFY_BLEND=C:\path\to\buildify_1.0.blend
  exit /b 1
)

echo Blender : %BLENDER%
echo Scene   : %SCENE%
echo.
"%BLENDER%" -b "%SCENE%" --python "%SCRIPT%" -- %*
set "CODE=%ERRORLEVEL%"

echo %cmdcmdline% | find /i "%~f0" >nul && pause
exit /b %CODE%
