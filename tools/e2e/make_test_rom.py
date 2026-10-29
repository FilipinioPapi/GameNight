#!/usr/bin/env python3
"""CI only: write a tiny NES test cartridge (it just loops and beeps), so no real game is needed.

    python make_test_rom.py <out.nes>
"""
import sys

prg = bytearray([0xEA] * 16384)  # NOP everywhere, mapped at $C000
code = bytes([
    0xA9, 0x01, 0x8D, 0x15, 0x40,  # LDA #1, STA $4015   (square 1 on)
    0xA9, 0xBF, 0x8D, 0x00, 0x40,  # LDA #$BF, STA $4000 (loud, constant volume)
    0xA9, 0xFD, 0x8D, 0x02, 0x40,  # LDA #$FD, STA $4002 (about 440 Hz)
    0xA9, 0x00, 0x8D, 0x03, 0x40,  # LDA #0, STA $4003
    0x4C, 0x14, 0xC0,              # JMP $C014 (loop forever)
])
prg[0:len(code)] = code
prg[0x3FFA:0x4000] = bytes([0x00, 0xC0, 0x00, 0xC0, 0x00, 0xC0])  # NMI, RESET, IRQ -> $C000
header = b"NES\x1a" + bytes([1, 1, 0, 0]) + bytes(8)
with open(sys.argv[1], "wb") as f:
    f.write(header + prg + bytes(8192))
