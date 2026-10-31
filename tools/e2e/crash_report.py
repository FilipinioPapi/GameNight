#!/usr/bin/env python3
"""CI only: reports where RetroArch crashed, from the small crash dumps Windows saved (Windows Error Reporting
"LocalDumps", switched on for retroarch.exe by the workflow on GitHub's test machine only).

    python crash_report.py <dump folder>

For each dump: the error code, the module (DLL) and offset where it happened, and, if Microsoft's debugger
(cdb) is on the machine, the call stack. The dumps themselves are not uploaded.
"""
import shutil
import subprocess
import sys
from pathlib import Path

folder = Path(sys.argv[1])
dumps = sorted(folder.glob("*.dmp")) if folder.exists() else []
print(f"{len(dumps)} RetroArch crash dump(s) in {folder}")
cdb = shutil.which("cdb") or next((str(p) for p in (
    Path(r"C:\Program Files (x86)\Windows Kits\10\Debuggers\x64\cdb.exe"),
    Path(r"C:\Program Files\Windows Kits\10\Debuggers\x64\cdb.exe")) if p.exists()), None)
print(f"debugger: {cdb or 'not found'}")
for d in dumps[:6]:
    print(f"\n==== {d.name} ({d.stat().st_size} bytes)")
    try:
        from minidump.minidumpfile import MinidumpFile
        mf = MinidumpFile.parse(str(d))
        rec = mf.exception.exception_records[0].ExceptionRecord
        addr = rec.ExceptionAddress
        where = "unknown module"
        for m in mf.modules.modules:
            if m.baseaddress <= addr < m.baseaddress + m.size:
                where = f"{Path(m.name).name} + {addr - m.baseaddress:#x}"
        code = getattr(rec, "ExceptionCode_raw", None)
        print(f"error code {code:#x} ({rec.ExceptionCode}) at {addr:#x} = {where}" if isinstance(code, int)
              else f"error code {rec.ExceptionCode} at {addr:#x} = {where}")
    except Exception as e:  # noqa: BLE001
        print(f"couldn't read the dump with the minidump package: {type(e).__name__}: {e}")
    if cdb:
        r = subprocess.run([cdb, "-z", str(d), "-c", ".ecxr;kn 25;q"], capture_output=True, text=True, timeout=180)
        lines = r.stdout.splitlines()
        start = next((i for i, l in enumerate(lines) if ".ecxr" in l), 0)
        print("\n".join(lines[start:start + 45]))
