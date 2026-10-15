@echo off
setlocal
rem Copies every built track that has an up-to-date .kn5 into Assetto Corsa's content\tracks folder.
rem Files already in the game's copy (like a recorded ai\fast_lane.ai) are kept.

set "AC=D:\SteamLibrary\steamapps\common\assettocorsa"
set "HERE=%~dp0"
if not exist "%AC%\content\tracks" (
  echo Assetto Corsa was not found at %AC%
  echo Edit install_track.bat and fix the AC= line.
  pause
  exit /b 1
)

for /d %%T in ("%HERE%output\*") do (
  for /d %%F in ("%%T\track\*") do call :install "%%T" "%%F" "%%~nxF"
)
echo.
echo Done. Start Content Manager and pick the track under Drive.
pause
exit /b 0

:install
set "ROOT=%~1"
set "TRK=%~2"
set "ID=%~3"
powershell -NoProfile -ExecutionPolicy Bypass -File "%HERE%builder\check_kn5.ps1" -Root "%ROOT%" -Track "%TRK%" -Id "%ID%"
set "RC=%errorlevel%"
if "%RC%"=="2" goto :nokn5
if "%RC%"=="4" goto :stale
echo Installing %ID% into %AC%\content\tracks\%ID%
robocopy "%TRK%" "%AC%\content\tracks\%ID%" /E /NFL /NDL /NJH /NJS /NP >nul
exit /b 0

:nokn5
echo Skipping %ID%: there is no %ID%.kn5 yet. Save it from ksEditor first, as
echo     output\%ID%\track\%ID%\%ID%.kn5
exit /b 0

:stale
echo Skipping %ID%: %ID%.kn5 is older than your last build, so the game would still get the old track.
echo     Open output\%ID%\fbx\%ID%.fbx in ksEditor and save the .kn5 again, replacing
echo     output\%ID%\track\%ID%\%ID%.kn5
exit /b 0
