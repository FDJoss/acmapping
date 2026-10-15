# Called by install_track.bat for each built track before it is copied into Assetto Corsa.
# Exit codes: 0 = ready to install, 2 = no .kn5 yet, 4 = the .kn5 is older than the last build.
# If ksEditor saved the .kn5 over the FBX (it keeps the folder and name it opened), the file is moved to where
# it belongs first; the previous .kn5 is kept next to the track folder, and the next build brings the FBX back.
param([string]$Root, [string]$Track, [string]$Id)

$fbx = Join-Path $Root "fbx\$Id.fbx"
$kn5 = Join-Path $Track "$Id.kn5"
$ui = Join-Path $Track 'ui\ui_track.json'      # written by every build

function Get-Magic([string]$Path) {
    $bytes = New-Object byte[] 6
    $fs = [IO.File]::OpenRead($Path)
    try { [void]$fs.Read($bytes, 0, 6) } finally { $fs.Close() }
    [Text.Encoding]::ASCII.GetString($bytes)
}

if ((Test-Path $fbx) -and (Get-Magic $fbx) -eq 'sc6969') {            # .kn5 files start with "sc6969"
    if (Test-Path $kn5) { Move-Item $kn5 (Join-Path $Root "${Id}_old.kn5") -Force }
    Move-Item $fbx $kn5
    Write-Host "  ksEditor saved $Id.kn5 over fbx\$Id.fbx. Moved it into the track folder."
    Write-Host "  The previous .kn5 is kept as output\$Id\${Id}_old.kn5. Build again to get the FBX back."
}
if (-not (Test-Path $kn5)) { exit 2 }
if ((Test-Path $ui) -and (Get-Item $ui).LastWriteTime -gt (Get-Item $kn5).LastWriteTime.AddSeconds(5)) { exit 4 }
exit 0
