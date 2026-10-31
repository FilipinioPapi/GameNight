#!/usr/bin/env python3
"""CI only: write a tiny NES test cartridge for the two-player online (netplay) test.

    python make_netplay_rom.py <out.nes>

Once per frame (in the NES's start-of-frame interrupt) it reads both controllers and keeps, in its RAM:
    $00-$02  frame number (counts up from 0, low byte first)
    $03      a running "fingerprint" of every frame so far: it mixes in both players' buttons and the
             frame number, so one wrong button on one frame changes it from then on
    $04      where the next entry goes in the button-change list (0-255, wraps around)
    $08-$09  how many button changes there have been in total
    $10      player 1's buttons, $11 player 2's (A=$80 B=$40 Select=$20 Start=$10 Up=$08 Down=$04 Left=$02 Right=$01)
    $0300-$03FF  the fingerprint for each of the last 256 frames (frame number's low byte is the place)
    $0400-$07FF  the last 256 button changes, 4 bytes each: frame low byte, frame high byte, player 1, player 2

Two copies playing together online must have exactly the same numbers for the same frame.
`fingerprint()` below is the same sum in Python, so the test can check the game's arithmetic too.
"""
import sys

RESET = 0xC000


def fingerprint(previous, frame, p1, p2):
    """The game's per-frame fingerprint: rotate left, mix in player 1, add player 2, add the frame's low byte."""
    h = ((previous << 1) & 0xFF) | (previous >> 7)
    h ^= p1
    h = (h + p2) & 0xFF
    return (h + (frame & 0xFF)) & 0xFF


class Asm:
    """Just enough of a 6502 assembler for this cartridge: bytes, labels and branches."""

    def __init__(self, origin):
        self.origin, self.code, self.labels, self.fixups = origin, bytearray(), {}, []

    def here(self):
        return self.origin + len(self.code)

    def label(self, name):
        self.labels[name] = self.here()

    def b(self, *data):
        self.code += bytes(data)

    def abs(self, opcode, address):
        self.b(opcode, address & 0xFF, address >> 8)

    def branch(self, opcode, target):
        self.b(opcode, 0)
        self.fixups.append((len(self.code) - 1, target))

    def jmp(self, target):
        self.b(0x4C, 0, 0)
        self.fixups.append((len(self.code) - 2, ("abs", target)))

    def done(self):
        for at, target in self.fixups:
            if isinstance(target, tuple):
                address = self.labels[target[1]]
                self.code[at:at + 2] = bytes([address & 0xFF, address >> 8])
            else:
                offset = self.labels[target] - (self.origin + at + 1)
                assert -128 <= offset <= 127, f"branch to {target} too far"
                self.code[at] = offset & 0xFF
        return bytes(self.code)


def build():
    a = Asm(RESET)
    # --- start up: quiet PPU, clear all 2 KB of RAM, then turn on the once-a-frame interrupt
    a.label("reset")
    a.b(0x78, 0xD8)                       # SEI, CLD
    a.b(0xA2, 0xFF, 0x9A)                 # LDX #$FF, TXS
    a.b(0xA9, 0x00)                       # LDA #0
    a.abs(0x8D, 0x2000)                   # STA $2000 (no interrupt yet)
    a.abs(0x8D, 0x2001)                   # STA $2001 (screen off)
    a.label("wait1")
    a.abs(0x2C, 0x2002)                   # BIT $2002
    a.branch(0x10, "wait1")               # BPL wait1
    a.b(0xA9, 0x00, 0xAA)                 # LDA #0, TAX
    a.label("clear")
    for page in range(8):
        a.abs(0x9D, page * 0x100)         # STA $page00,X
    a.b(0xE8)                             # INX
    a.branch(0xD0, "clear")               # BNE clear
    a.label("wait2")
    a.abs(0x2C, 0x2002)
    a.branch(0x10, "wait2")
    a.b(0xA9, 0x80)                       # LDA #$80
    a.abs(0x8D, 0x2000)                   # STA $2000 (interrupt at the start of every frame)
    a.label("forever")
    a.jmp("forever")

    # --- once a frame
    a.label("nmi")
    a.b(0x48, 0x8A, 0x48, 0x98, 0x48)     # PHA, TXA, PHA, TYA, PHA
    a.b(0xE6, 0x00)                       # INC $00
    a.branch(0xD0, "counted")
    a.b(0xE6, 0x01)                       # INC $01
    a.branch(0xD0, "counted")
    a.b(0xE6, 0x02)                       # INC $02
    a.label("counted")
    a.b(0xA9, 0x01)
    a.abs(0x8D, 0x4016)                   # latch the buttons
    a.b(0xA9, 0x00)
    a.abs(0x8D, 0x4016)
    for port, temp in ((0x4016, 0x12), (0x4017, 0x13)):
        a.b(0xA2, 0x08)                   # LDX #8
        loop = f"read{port:x}"
        a.label(loop)
        a.abs(0xAD, port)                 # LDA $4016/7
        a.b(0x4A)                         # LSR A
        a.b(0x26, temp)                   # ROL temp
        a.b(0xCA)                         # DEX
        a.branch(0xD0, loop)              # BNE
    a.b(0xA5, 0x12, 0x85, 0x10)           # player 1 -> $10
    a.b(0xA5, 0x13, 0x85, 0x11)           # player 2 -> $11
    # fingerprint
    a.b(0xA5, 0x03)                       # LDA $03
    a.b(0x0A, 0x69, 0x00)                 # ASL A, ADC #0   (rotate left)
    a.b(0x45, 0x10)                       # EOR $10
    a.b(0x18, 0x65, 0x11)                 # CLC, ADC $11
    a.b(0x18, 0x65, 0x00)                 # CLC, ADC $00
    a.b(0x85, 0x03)                       # STA $03
    a.b(0xA6, 0x00)                       # LDX $00
    a.abs(0x9D, 0x0300)                   # STA $0300,X
    # button change? note it in the list
    a.b(0xA5, 0x10, 0xC5, 0x14)           # LDA $10, CMP $14
    a.branch(0xD0, "changed")
    a.b(0xA5, 0x11, 0xC5, 0x15)           # LDA $11, CMP $15
    a.branch(0xF0, "finished")            # BEQ finished
    a.label("changed")
    a.b(0xA5, 0x10, 0x85, 0x14)           # remember these buttons
    a.b(0xA5, 0x11, 0x85, 0x15)
    a.b(0xA5, 0x04, 0x0A, 0x0A, 0x85, 0x06)               # entry address low = place * 4
    a.b(0xA5, 0x04, 0x4A, 0x4A, 0x4A, 0x4A, 0x4A, 0x4A)  # high = $04 + place / 64
    a.b(0x18, 0x69, 0x04, 0x85, 0x07)
    a.b(0xA0, 0x00)                       # LDY #0
    for zp in (0x00, 0x01, 0x10, 0x11):
        a.b(0xA5, zp, 0x91, 0x06)         # LDA zp, STA ($06),Y
        if zp != 0x11:
            a.b(0xC8)                     # INY
    a.b(0xE6, 0x04)                       # next place
    a.b(0xE6, 0x08)                       # total changes
    a.branch(0xD0, "finished")
    a.b(0xE6, 0x09)
    a.label("finished")
    a.b(0x68, 0xA8, 0x68, 0xAA, 0x68, 0x40)  # PLA, TAY, PLA, TAX, PLA, RTI
    a.label("irq")
    a.b(0x40)                             # RTI
    code = a.done()
    return code, a.labels


def rom():
    code, labels = build()
    prg = bytearray([0xEA] * 16384)  # mapped at $C000 (and $8000)
    prg[0:len(code)] = code
    vectors = [labels["nmi"], labels["reset"], labels["irq"]]
    prg[0x3FFA:0x4000] = b"".join(bytes([v & 0xFF, v >> 8]) for v in vectors)
    header = b"NES\x1a" + bytes([1, 1, 0, 0]) + bytes(8)
    return header + bytes(prg) + bytes(8192)


if __name__ == "__main__":
    with open(sys.argv[1], "wb") as f:
        f.write(rom())
