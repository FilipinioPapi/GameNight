# CI only (GitHub's Windows machine): tests Game Night the way Jayden uses it, before any release.
#  1. Installs an old test build (the "e2e" build, version 0.0.1).
#  2. Plays a test game with the bundled player: it must start, run at real speed, and the log must be written.
#  3. Updates the old build to the new installer through the app's own updater (signed list, download,
#     install, restart) and checks the new version is installed and running.
# Any failure stops the build, so nothing untested reaches the NAS.
param([string]$OldSetup, [string]$NewSetup, [string]$NewVersion, [string]$Tools)
$ErrorActionPreference = 'Stop'
function Fail($m) { Write-Host "::error::$m"; exit 1 }
function Step($m) { Write-Host "`n=== $m ===" }

$cache = Join-Path $env:LOCALAPPDATA 'xyz.jjsnas.gamenight'
$config = Join-Path $env:APPDATA 'xyz.jjsnas.gamenight'

Step "Install the old test build"
$p = Start-Process -FilePath $OldSetup -ArgumentList '/S' -PassThru -Wait
if ($p.ExitCode -ne 0) { Fail "old installer exit code $($p.ExitCode)" }
$installDir = Join-Path $env:LOCALAPPDATA 'Game Night'
$exe = Get-ChildItem $installDir -Filter *.exe | Where-Object { $_.Name -notlike 'uninstall*' } | Select-Object -First 1
if (-not $exe) { Fail "Game Night isn't in $installDir after installing" }
$exe = $exe.FullName
Write-Host "installed $exe, version $((Get-Item $exe).VersionInfo.ProductVersion)"
if (-not (Test-Path (Join-Path $installDir 'player\retroarch.exe'))) { Fail "the game player wasn't installed" }

Step "Play a test game"
$root = Join-Path $env:RUNNER_TEMP 'gn\Game Night'
New-Item -ItemType Directory (Join-Path $root 'nes') -Force | Out-Null
python (Join-Path $Tools 'make_test_rom.py') (Join-Path $root 'nes\test.nes')
$size = (Get-Item (Join-Path $root 'nes\test.nes')).Length
Set-Content (Join-Path $root 'library.json') "{`"1`":{`"console`":`"nes`",`"file`":`"test.nes`",`"size`":$size}}"
$env:GAMENIGHT_E2E = 'play'
$env:GAMENIGHT_E2E_ROOT = $root
$runs = 0; $result = $null; $seconds = 0
while ($runs -lt 4) {
  $runs++
  Remove-Item (Join-Path $root 'e2e-result.json') -ErrorAction SilentlyContinue
  $t = [Diagnostics.Stopwatch]::StartNew()
  $app = Start-Process -FilePath $exe -PassThru
  if (-not $app.WaitForExit(180000)) { $app.Kill(); Fail "the game didn't finish within 3 minutes" }
  $seconds = [math]::Round($t.Elapsed.TotalSeconds, 1)
  $resultFile = Join-Path $root 'e2e-result.json'
  if (-not (Test-Path $resultFile)) { Fail "no result from the game test (app exit code $($app.ExitCode))" }
  $result = Get-Content $resultFile -Raw | ConvertFrom-Json
  Write-Host "run ${runs}: $seconds s, sound way $($result.sound_way), no sound: $($result.silent), ok: $($result.ok)"
  if ($result.error) { Fail "the game didn't start: $($result.error)" }
  $log = Join-Path $cache 'player\logs\retroarch.log'
  if (Test-Path $log) {
    Get-Content $log | Select-String -Pattern 'audio|Audio|Content|Core|Video|error|ERROR' | Select-Object -First 40 | ForEach-Object { Write-Host "  | $_" }
  } else { Fail "RetroArch wrote no log" }
  $pads = Join-Path $cache 'player\logs\controllers.txt'
  if (Test-Path $pads) { Write-Host "controllers:"; Get-Content $pads | ForEach-Object { Write-Host "  | $_" } } else { Fail "no controllers note was written" }
  $cfgFile = Join-Path $config 'player\retroarch.cfg'
  if (-not (Select-String -Path $cfgFile -Pattern 'input_max_users = "4"' -Quiet)) { Fail "the player settings are missing the controller lines" }
  if (-not $result.silent) { break }
}
if (-not $result.ok) { Fail "RetroArch exited with an error" }
# 600 frames is 10 seconds at real speed. Much faster means the game is racing (Jayden's "sped up" bug).
if ($seconds -lt 8) { Fail "600 frames took only $seconds s: the game runs too fast" }
Write-Host "the game ran at real speed ($seconds s for 600 frames)"
Remove-Item Env:GAMENIGHT_E2E, Env:GAMENIGHT_E2E_ROOT

Step "Drive the menus with a pretend Xbox controller"
# Settings as if the first-time setup was done, so the app opens on the main menu.
New-Item -ItemType Directory $config -Force | Out-Null
@{ settings = @{ firstRunDone = $true; romsFolder = $root; mappings = @{}; presets = @{}; consoles = @{}; steamTipSeen = $true } } |
  ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8 (Join-Path $config 'settings.json')
$shots = Join-Path $env:RUNNER_TEMP 'screens'
python (Join-Path $Tools 'pad_test.py') $exe $root $shots
if ($LASTEXITCODE -ne 0) { Fail "the pretend controller couldn't drive the menus (screenshots are in the 'screens' download)" }

Step "Update to $NewVersion through the app's own updater"
$site = Join-Path $env:RUNNER_TEMP 'updates'
$key = (python (Join-Path $Tools 'make_update.py') $NewSetup $NewVersion $site).Trim()
$server = Start-Process python -ArgumentList '-m', 'http.server', '8765', '--bind', '127.0.0.1', '--directory', $site -PassThru -WindowStyle Hidden
Start-Sleep 2
$env:GAMENIGHT_E2E = 'update'
$env:GAMENIGHT_UPDATE_URL = 'http://127.0.0.1:8765/'
$env:GAMENIGHT_UPDATE_KEY = $key
$old = Start-Process -FilePath $exe -PassThru
$ok = $false
for ($i = 0; $i -lt 180; $i++) {
  Start-Sleep 1
  $ver = (Get-Item $exe -ErrorAction SilentlyContinue).VersionInfo.ProductVersion
  $running = Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $exe -and $_.Id -ne $old.Id }
  if ($ver -like "$NewVersion*" -and $running) { $ok = $true; break }
}
$updLog = Join-Path $cache 'update\update.log'
if (Test-Path $updLog) { Get-Content $updLog | ForEach-Object { Write-Host "  | $_" } } else { Write-Host "  (no update.log)" }
Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $exe } | Stop-Process -Force
Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
if (-not $ok) { Fail "after 3 minutes Game Night was on version '$ver' and running: $([bool]$running) (wanted $NewVersion, running)" }
Write-Host "updated from 0.0.1 to $NewVersion and reopened by itself"
