@echo off
setlocal
rem Drag a .layout.json file (saved by designer\track-designer.html) onto this file to build the track.
rem Extra options can follow the layout path: --flip-spawns  --no-terrain

set "BLENDER="
for /d %%D in ("%ProgramFiles%\Blender Foundation\Blender *") do if exist "%%D\blender.exe" set "BLENDER=%%D\blender.exe"
if not defined BLENDER (
  echo Could not find Blender under "%ProgramFiles%\Blender Foundation".
  echo Edit build_track.bat and set BLENDER to the full path of blender.exe.
  pause
  exit /b 1
)
if "%~1"=="" (
  echo Drag a .layout.json file onto build_track.bat to build it.
  pause
  exit /b 1
)

echo Using %BLENDER%
echo.
"%BLENDER%" --background --factory-startup --python "%~dp0builder\build_track.py" -- --layout "%~1" --out "%~dp0output" %2 %3
echo.
pause
