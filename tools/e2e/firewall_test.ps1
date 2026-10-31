# CI only: proves the installer's firewall rule (app/src-tauri/windows/hooks.nsh) does its job. A Windows container
# on this machine plays "another PC on the same Wi-Fi" (traffic inside one PC skips the firewall, so the PC can't
# test itself). RetroArch hosts a game the way Couch Play does (--host), then:
#   1. someone clicked "Allow" on Windows' firewall question (an allow rule): the other PC CAN reach it;
#   2. with Game Night's block rule added (the installer's exact command): the other PC can NOT reach it;
#   3. Game Night on the same PC still reaches it (game port and RetroArch's remote-control port).
param([string]$Player, [string]$Work, [string]$Out)
$ErrorActionPreference = 'Stop'
$failures = @()
function Step($m) { Write-Host "`n=== $m ===" }
function Bad($m) { Write-Host "::error::$m"; $script:failures += $m }
New-Item -ItemType Directory $Work, $Out -Force | Out-Null
$exe = Join-Path $Player 'retroarch.exe'
$rule = 'Game Night: keep RetroArch off the network'
$allow = 'Test: someone clicked Allow for RetroArch'
$results = [ordered]@{}

Step "The other PC (a Windows container)"
$image = 'mcr.microsoft.com/windows/nanoserver:ltsc2022'
docker pull -q $image | Out-Null
$hostIp = (docker network inspect nat | ConvertFrom-Json)[0].IPAM.Config[0].Gateway
Write-Host "this PC as the container sees it: $hostIp"
docker run --rm $image curl.exe --version 2>&1 | Select-Object -First 1 | ForEach-Object { Write-Host "  | $_" }
function From-OtherPC($port) {
  $o = (docker run --rm $image curl.exe -s -v -m 5 "telnet://${hostIp}:$port" 2>&1) -join "`n"
  $reached = $o -match 'Connected to|Established connection'  # curl's wording changed between versions
  Write-Host "  other PC -> ${hostIp}:$port reached: $reached"
  ($o -split "`n" | Select-Object -First 4) | ForEach-Object { Write-Host "    | $_" }
  return $reached
}

Step "RetroArch hosts a game (like Couch Play)"
$rom = Join-Path $Work 'test.nes'
python (Join-Path $PSScriptRoot 'make_test_rom.py') $rom
$cfg = Join-Path $Work 'retroarch.cfg'
@(
  'config_save_on_exit = "false"', 'video_driver = "d3d11"', 'video_fullscreen = "false"', 'audio_enable = "false"',
  'network_cmd_enable = "true"', 'network_cmd_port = "55600"', 'netplay_nat_traversal = "false"',
  'netplay_public_announce = "false"', 'menu_driver = "rgui"', "log_dir = `"$($Work -replace '\\','/')`"", 'log_to_file = "true"'
) | Set-Content -Encoding ascii $cfg
$ra = Start-Process -FilePath $exe -ArgumentList @('-c', "`"$cfg`"", '-L', "`"$(Join-Path $Player 'cores\fceumm_libretro.dll')`"", '--host', '--port', '55700', "`"$rom`"") -WorkingDirectory $Player -PassThru
Start-Sleep 8
netstat -ano -p TCP | Select-String ':55700 ' | ForEach-Object { Write-Host "  | $_" }
netstat -ano -p UDP | Select-String ':55600 ' | ForEach-Object { Write-Host "  | $_" }

function From-ThisPC {
  $tcp = (Test-NetConnection 127.0.0.1 -Port 55700 -WarningAction SilentlyContinue).TcpTestSucceeded
  $u = New-Object System.Net.Sockets.UdpClient; $u.Client.ReceiveTimeout = 3000
  $answer = $null
  try {
    $b = [Text.Encoding]::ASCII.GetBytes("VERSION`n"); [void]$u.Send($b, $b.Length, '127.0.0.1', 55600)
    $ep = New-Object System.Net.IPEndPoint([Net.IPAddress]::Any, 0); $answer = [Text.Encoding]::ASCII.GetString($u.Receive([ref]$ep)).Trim()
  } catch { $answer = "none" } finally { $u.Close() }
  Write-Host "  this PC -> game port: $tcp; remote-control port answers: $answer"
  return @{ game_port = $tcp; command_port = $answer }
}

Step "No rules (a fresh PC: Windows blocks unasked-for incoming by default)"
$results.no_rules = @{ other_pc = (From-OtherPC 55700) }

Step "Someone clicked Allow (an allow rule for RetroArch)"
New-NetFirewallRule -DisplayName $allow -Direction Inbound -Action Allow -Program $exe -Profile Any | Out-Null
$results.allowed = @{ other_pc = (From-OtherPC 55700); this_pc = From-ThisPC }
if (-not $results.allowed.other_pc) { Bad "the other PC couldn't reach RetroArch even with an allow rule, so this test can't show the block works" }

Step "Game Night's block rule added (the installer's command)"
& "$env:SystemRoot\System32\netsh.exe" advfirewall firewall add rule "name=$rule" dir=in action=block "program=$exe" enable=yes profile=any
Get-NetFirewallRule -DisplayName $rule | ForEach-Object { Write-Host "  | $($_.DisplayName): $($_.Direction) $($_.Action) $($_.Enabled) $(($_ | Get-NetFirewallApplicationFilter).Program)" }
$results.blocked = @{ other_pc = (From-OtherPC 55700); this_pc = From-ThisPC }
if ($results.blocked.other_pc) { Bad "the other PC still reached RetroArch with Game Night's block rule" }
if (-not $results.blocked.this_pc.game_port) { Bad "the block rule stopped this PC reaching RetroArch's game port" }
if ($results.blocked.this_pc.command_port -notmatch '^\d') { Bad "the block rule stopped this PC reaching RetroArch's remote-control port" }

Step "Clean up"
Stop-Process -Id $ra.Id -Force -ErrorAction SilentlyContinue
Remove-NetFirewallRule -DisplayName $allow -ErrorAction SilentlyContinue
Remove-NetFirewallRule -DisplayName $rule -ErrorAction SilentlyContinue
$results.failures = $failures
$results | ConvertTo-Json -Depth 5 | Tee-Object (Join-Path $Out 'firewall-results.json')
if ($failures) { exit 1 }
Write-Host "`nthe block rule keeps other PCs out, even after an Allow, and Game Night still reaches RetroArch on this PC"
