# CI only: sets the runner's screen to a normal PC size (default 1920x1080), so the app is seen as on a real
# monitor. GitHub's Windows machine starts at 1024x768, smaller than Game Night's smallest window.
param([int]$Width = 1920, [int]$Height = 1080)
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class GnScreen {
  [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Ansi)]
  public struct DEVMODE {
    [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string dmDeviceName;
    public short dmSpecVersion, dmDriverVersion, dmSize, dmDriverExtra; public int dmFields;
    public int dmPositionX, dmPositionY, dmDisplayOrientation, dmDisplayFixedOutput;
    public short dmColor, dmDuplex, dmYResolution, dmTTOption, dmCollate;
    [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string dmFormName;
    public short dmLogPixels; public int dmBitsPerPel, dmPelsWidth, dmPelsHeight, dmDisplayFlags, dmDisplayFrequency;
    public int dmICMMethod, dmICMIntent, dmMediaType, dmDitherType, dmReserved1, dmReserved2, dmPanningWidth, dmPanningHeight;
  }
  [DllImport("user32.dll")] public static extern bool EnumDisplaySettings(string d, int m, ref DEVMODE dm);
  [DllImport("user32.dll")] public static extern int ChangeDisplaySettings(ref DEVMODE dm, int flags);
  public static int Set(int w, int h) {
    DEVMODE dm = new DEVMODE(); dm.dmSize = (short)Marshal.SizeOf(typeof(DEVMODE));
    EnumDisplaySettings(null, -1, ref dm);
    dm.dmPelsWidth = w; dm.dmPelsHeight = h; dm.dmFields = 0x80000 | 0x100000;
    return ChangeDisplaySettings(ref dm, 0);
  }
}
"@
$r = [GnScreen]::Set($Width, $Height)
Add-Type -AssemblyName System.Windows.Forms
$b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
Write-Host "screen size change result $r (0 = done); screen is now $($b.Width)x$($b.Height)"
