#!/usr/bin/env python3
"""CI only: write a tiny NES test cartridge (it beeps, and keeps both controllers' buttons in RAM at $10 and $11), so no real game is needed.

    python make_test_rom.py <out.nes>
"""
import sys

prg = bytearray([0xEA] * 16384)  # NOP everywhere, mapped at $C000
code = bytes([
    0xA9, 0x01, 0x8D, 0x15, 0x40,  # LDA #1, STA $4015   (square 1 on)
    0xA9, 0xBF, 0x8D, 0x00, 0x40,  # LDA #$BF, STA $4000 (loud, constant volume)
    0xA9, 0xFD, 0x8D, 0x02, 0x40,  # LDA #$FD, STA $4002 (about 440 Hz)
    0xA9, 0x00, 0x8D, 0x03, 0x40,  # LDA #0, STA $4003
    # $C014, forever: read both controllers into RAM, so the controller test can ask the game what it sees.
    0xA9, 0x01, 0x8D, 0x16, 0x40,  # LDA #1, STA $4016   (latch the buttons)
    0xA9, 0x00, 0x8D, 0x16, 0x40,  # LDA #0, STA $4016
    0xA2, 0x08,                    # LDX #8
    0xAD, 0x16, 0x40, 0x4A,        # LDA $4016, LSR A    (player 1's next button into carry)
    0x26, 0x10, 0xCA, 0xD0, 0xF7,  # ROL $10, DEX, BNE   ($10 = player 1: A B Select Start Up Down Left Right)
    0xA2, 0x08,                    # LDX #8
    0xAD, 0x17, 0x40, 0x4A,        # LDA $4017, LSR A
    0x26, 0x11, 0xCA, 0xD0, 0xF7,  # ROL $11, DEX, BNE   ($11 = player 2)
    0x4C, 0x14, 0xC0,              # JMP $C014
])
prg[0:len(code)] = code
prg[0x3FFA:0x4000] = bytes([0x00, 0xC0, 0x00, 0xC0, 0x00, 0xC0])  # NMI, RESET, IRQ -> $C000
header = b"NES\x1a" + bytes([1, 1, 0, 0]) + bytes(8)
with open(sys.argv[1], "wb") as f:
    f.write(header + prg + bytes(8192))
