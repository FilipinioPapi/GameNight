# CI only (GitHub's Windows machine, never anyone's PC): adds pretend Xbox controllers for the tests.
# Same steps as the "Add a pretend Xbox controller" step in .github/workflows/app.yml: the ViGEmBus driver
# and the vgamepad Python package (both from vgamepad 0.2.0), plus Microsoft's Xbox 360 pad driver, which
# Windows Server lacks. Every download is checked against its fixed fingerprint.
$ErrorActionPreference = 'Stop'
$tgz = Join-Path $env:RUNNER_TEMP 'vgamepad-0.2.0.tar.gz'
Invoke-WebRequest https://files.pythonhosted.org/packages/06/a5/990701a89ea8d7528a269c2be1ba71d888de38a762a1b0f8d8eae4c2be62/vgamepad-0.2.0.tar.gz -OutFile $tgz
$sha = (Get-FileHash $tgz -Algorithm SHA256).Hash.ToLower()
if ($sha -ne '6ac247e6441e194a0277b46f6f9abc02d7995de5ed8dc495b67eddd214364a88') { throw "vgamepad download doesn't match its fingerprint ($sha)" }
tar -xzf $tgz -C $env:RUNNER_TEMP
$msi = Join-Path $env:RUNNER_TEMP 'vgamepad-0.2.0\vgamepad\win\vigem\install\x64\ViGEmBusSetup_x64.msi'
$log = Join-Path $env:RUNNER_TEMP 'vigem-install.log'
$p = Start-Process msiexec -ArgumentList '/i', "`"$msi`"", '/qn', '/norestart', '/l*v', "`"$log`"" -Wait -PassThru
Write-Host "ViGEmBus installer exit code $($p.ExitCode)"
if ($p.ExitCode -ne 0 -and $p.ExitCode -ne 3010) { Get-Content $log -Tail 60; throw "ViGEmBus didn't install" }
$env:VGAMEPAD_SKIP_VIGEMBUS_INSTALL = 'true'
pip install --no-deps $tgz
# Windows Server (this CI machine) has no Xbox 360 pad driver, so a pretend Xbox pad can't start
# (measured 2026-10-29: no xusb22 files, VIGEM_ERROR_TARGET_NOT_PLUGGED_IN, PlayStation pad fine).
# Add Microsoft's own one from the Microsoft Update Catalog ("XBOX 360 Controller For Windows",
# 2009-08-12), checked against its fixed fingerprint.
$cab = Join-Path $env:RUNNER_TEMP 'xusb21.cab'
Invoke-WebRequest https://catalog.s.download.windowsupdate.com/msdownload/update/driver/drvs/2013/01/20289581_7385d6be1b053a35955a910f11436729a1d4cb56.cab -OutFile $cab
$sha = (Get-FileHash $cab -Algorithm SHA256).Hash.ToLower()
if ($sha -ne '49bd427e53f5c63a1a03b791cf6deeefe3a2ac5700dc4db5e39fad98f3070fa6') { throw "Xbox 360 driver download doesn't match its fingerprint ($sha)" }
$drv = Join-Path $env:RUNNER_TEMP 'xusb21'
New-Item -ItemType Directory $drv -Force | Out-Null
expand.exe $cab -F:* $drv | Out-Null
Get-ChildItem $drv -Recurse | ForEach-Object { Write-Host "  $($_.FullName)" }
pnputil /add-driver (Join-Path $drv 'xusb21.inf') /install
Write-Host "pnputil exit code $LASTEXITCODE"
python -c "import vgamepad; p = vgamepad.VX360Gamepad(); print('pretend Xbox pad (045e:028e) plugged in, index', p.get_index())"
$xboxOk = $LASTEXITCODE -eq 0
python -c "import vgamepad; p = vgamepad.VX360Gamepad(vid=0x045E, pid=0x02FF); print('pretend Xbox pad with 045e:02ff plugged in, index', p.get_index())"
Write-Host "--- devices the bus made:"
pnputil /enum-devices /connected | Select-String -Context 0,6 -Pattern 'ViGEm|Xbox|XUSB|USB\\VID_045E|Gamepad' | ForEach-Object { Write-Host $_ }
if (-not $xboxOk) { throw "the pretend Xbox pad couldn't be plugged in" }
exit 0
