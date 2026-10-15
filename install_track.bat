@echo off
setlocal
rem Copies every built track that already has its .kn5 into Assetto Corsa's content\tracks folder.
rem Files already in the game's copy (like a recorded ai\fast_lane.ai) are kept.

set "AC=D:\SteamLibrary\steamapps\common\assettocorsa"
if not exist "%AC%\content\tracks" (
  echo Assetto Corsa was not found at %AC%
  echo Edit install_track.bat and fix the AC= line.
  pause
  exit /b 1
)

for /d %%T in ("%~dp0output\*") do (
  for /d %%F in ("%%T\track\*") do (
    if exist "%%F\%%~nxF.kn5" (
      echo Installing %%~nxF into %AC%\content\tracks\%%~nxF
      robocopy "%%F" "%AC%\content\tracks\%%~nxF" /E /NFL /NDL /NJH /NJS /NP >nul
    ) else (
      echo Skipping %%~nxF: there is no %%~nxF.kn5 yet. Save it from ksEditor first.
    )
  )
)
echo.
echo Done. Start Content Manager and pick the track under Drive.
pause
