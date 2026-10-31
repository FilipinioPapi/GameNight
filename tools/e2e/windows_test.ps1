# CI only (GitHub's Windows machine): tests Game Night the way Jayden uses it, before any release.
#  1. Installs an old test build (the "e2e" build, version 0.0.1).
#  2. Plays a test game with the bundled player: it must start, run at real speed, and the log must be written.
#  3. Updates the old build to the new installer through the app's own update box (signed list, download,
#     install, restart) and checks every step was shown and the new version came back in front.
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
python (Join-Path $Tools 'pad_test.py') menus $exe $root $shots
if ($LASTEXITCODE -ne 0) { Fail "the pretend controller couldn't drive the menus (screenshots are in the 'screens' download)" }

Step "Play the test game with the pretend Xbox controller"
python (Join-Path $Tools 'pad_test.py') game $exe $root $shots
if ($LASTEXITCODE -ne 0) { Fail "the game didn't get the pretend controller on Player 1 (screenshots are in the 'screens' download)" }

Step "Update to $NewVersion through the app's own update box"
# The update is served at about home-internet speed (3 MB/s), and the old build presses Update in its own
# update box (GAMENIGHT_E2E=update-ui), so this goes through the same screen and steps Jayden sees.
# Screenshots are taken every second and kept with the build ("screens" download, "update" folder).
$site = Join-Path $env:RUNNER_TEMP 'updates'
$key = (python (Join-Path $Tools 'make_update.py') $NewSetup $NewVersion $site).Trim()
$server = Start-Process python -ArgumentList (Join-Path $Tools 'slow_server.py'), $site, '8765', '3000000' -PassThru -WindowStyle Hidden
Start-Sleep 2
$updShots = Join-Path $env:RUNNER_TEMP 'screens\update'
New-Item -ItemType Directory $updShots -Force | Out-Null
$camera = Start-Job -ArgumentList $updShots -ScriptBlock {
  param($dir)
  Add-Type -AssemblyName System.Windows.Forms, System.Drawing
  for ($n = 0; $n -lt 150; $n++) {
    try {
      $b = [System.Windows.Forms.SystemInformation]::VirtualScreen
      $bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
      $g = [System.Drawing.Graphics]::FromImage($bmp)
      $g.CopyFromScreen($b.Left, $b.Top, 0, 0, $bmp.Size)
      $bmp.Save((Join-Path $dir ('{0:000}-{1:HHmmss}.png' -f $n, (Get-Date).ToUniversalTime())), [System.Drawing.Imaging.ImageFormat]::Png)
      $g.Dispose(); $bmp.Dispose()
    } catch {}
    Start-Sleep -Milliseconds 1000
  }
}
Add-Type @"
using System; using System.Text; using System.Runtime.InteropServices; using System.Collections.Generic;
public static class Win {
  delegate bool EnumProc(IntPtr h, IntPtr p);
  [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc f, IntPtr p);
  [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] static extern bool IsIconic(IntPtr h);
  [DllImport("user32.dll")] static extern IntPtr GetWindow(IntPtr h, uint cmd);
  [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  public static List<string> Of(uint want) {
    var r = new List<string>(); var fg = GetForegroundWindow();
    EnumWindows((h, p) => {
      uint pid; GetWindowThreadProcessId(h, out pid);
      if (pid == want && GetWindow(h, 4) == IntPtr.Zero) {
        var t = new StringBuilder(256); GetWindowText(h, t, 256);
        r.Add(String.Format("'{0}' visible={1} minimised={2} in-front={3}", t, IsWindowVisible(h), IsIconic(h), h == fg));
      }
      return true;
    }, IntPtr.Zero);
    return r;
  }
}
"@
$env:GAMENIGHT_E2E = 'update-ui'
$env:GAMENIGHT_UPDATE_URL = 'http://127.0.0.1:8765/'
$env:GAMENIGHT_UPDATE_KEY = $key
$updLog = Join-Path $cache 'update\update.log'
Remove-Item $updLog -ErrorAction SilentlyContinue
$t = [Diagnostics.Stopwatch]::StartNew()
$old = Start-Process -FilePath $exe -PassThru
$closedAt = $null; $new = $null
for ($i = 0; $i -lt 360; $i++) {
  Start-Sleep -Milliseconds 500
  if (-not $closedAt -and $old.HasExited) { $closedAt = $t.Elapsed.TotalSeconds; Write-Host "old Game Night closed after $([math]::Round($closedAt,1)) s" }
  $new = Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $exe -and $_.Id -ne $old.Id } | Select-Object -First 1
  if ($new) { Write-Host "new Game Night started after $([math]::Round($t.Elapsed.TotalSeconds,1)) s (pid $($new.Id))"; break }
}
$ver = (Get-Item $exe -ErrorAction SilentlyContinue).VersionInfo.ProductVersion
$windows = @(); $alive = $false
if ($new) {
  # Give it time to show its window, then look at what a person would see.
  Start-Sleep 10
  $alive = -not $new.HasExited
  $windows = [Win]::Of([uint32]$new.Id)
  Write-Host "10 s later: still running: $alive. Its windows:"
  $windows | ForEach-Object { Write-Host "  | $_" }
}
Start-Sleep 2
# Read the log now, while the new Game Night is still open, so the checks below only count steps that
# happened before anyone closed it.
$log = if (Test-Path $updLog) { Get-Content $updLog } else { @() }
Stop-Job $camera -ErrorAction SilentlyContinue; Remove-Job $camera -Force -ErrorAction SilentlyContinue
Write-Host "update log:"
if (Test-Path $updLog) { Get-Content $updLog | ForEach-Object { Write-Host "  | $_" } } else { Write-Host "  (no update.log)" }
Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $exe } | Stop-Process -Force
Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue

# What has to be true, measured:
function At($text) { $l = $log | Select-String -SimpleMatch $text | Select-Object -First 1; if ($l) { [datetime]::ParseExact($l.Line.Substring(0, 23), 'yyyy-MM-dd HH:mm:ss.fff', $null) } }
$closing = At 'Game Night closes now'; $back = At "Game Night $NewVersion opened"
if ($closing -and $back) { Write-Host "time between the old window closing and the new one opening: $([math]::Round(($back - $closing).TotalSeconds, 1)) s" }
$problems = @()
foreach ($want in 'screen shows downloading 100%', 'screen shows checking 100%', 'screen shows installing', 'helper: installer finished with code 0', 'helper: the installer opens Game Night again', 'back after the update', 'screen shows updated') {
  if (-not ($log | Select-String -SimpleMatch $want)) { $problems += "the update log never says '$want'" }
}
if (-not ($ver -like "$NewVersion*")) { $problems += "installed version is '$ver', wanted $NewVersion" }
if (-not $new) { $problems += "Game Night didn't start again" }
elseif (-not $alive) { $problems += "the reopened Game Night quit within 10 s" }
elseif (-not ($windows | Where-Object { $_ -match "^'Game Night' visible=True minimised=False in-front=True" })) { $problems += "the reopened Game Night isn't the window in front" }
if ($problems) { Fail ("update test: " + ($problems -join '; ')) }
Write-Host "updated from 0.0.1 to ${NewVersion}: the box showed 100%, checked and installing; the installer ran; Game Night came back in front and said it updated"
