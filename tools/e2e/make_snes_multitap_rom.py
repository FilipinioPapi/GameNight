#!/usr/bin/env python3
"""CI only: write a tiny SNES test cartridge for the 4-player online (Couch Play) test.

    python make_snes_multitap_rom.py <out.sfc>

The cartridge reads controller 1 and a multitap (4 more controllers) on port 2 once per frame, in the SNES's
start-of-frame interrupt, the way 4-player SNES games do (nesdev/SNESdev wiki "Multitap": read port 2 with
I/O bit 7 high for pads 2 and 3, then with it low for pads 4 and 5). It runs in the 65816's 6502-compatible
start-up mode the whole time, so its code is plain 6502 and can be checked on a 6502 simulator
(check_snes_multitap_rom.py). It keeps, in its RAM (WRAM, bank $7E, also seen at $0000-$1FFF):
    $00-$02  frame number (counts up from 0, low byte first)
    $03      a running "fingerprint" of every frame so far (all five pads and the frame number mixed in,
             so one wrong button on one frame changes it from then on)
    $04      where the next entry goes in the button-change list (0-127, wraps around)
    $08-$09  how many button changes there have been in total
    $10-$19  pads 1-5, two bytes each, in the order the SNES sends them:
             first byte  B=$80 Y=$40 Select=$20 Start=$10 Up=$08 Down=$04 Left=$02 Right=$01
             second byte A=$80 X=$40 L=$20 R=$10
    $40-$5F  a 32-byte marker the test uses to find this RAM inside the emulator's memory (worked out
             by the code at start-up, so it never appears in the cartridge itself)
    $0300-$03FF  the fingerprint for each of the last 256 frames (frame number's low byte is the place)
    $0800-$0FFF  the last 128 button changes, 16 bytes each: frame low byte, frame high byte, pads 1-5
                 (10 bytes), 4 zero bytes
The screen shows one colour that changes every frame, so a screenshot shows whether the game is live.

Copies of the game playing together online must have exactly the same numbers for the same frame.
`fingerprint()` below is the same sum in Python, so the test can check the game's arithmetic too.
"""
import sys

ORG = 0x8000  # LoROM: the 32 KB cartridge is seen at $8000-$FFFF in bank 0
PADS = 5
MARKER = bytes(i ^ 0xA5 for i in range(16)) + bytes((0x5A - i) & 0xFF for i in range(16))
MARKER_AT = 0x40
CHANGES_AT = 0x0800
CHANGE_SIZE = 16
CHANGE_SLOTS = 128


def fingerprint(previous, frame, pad_bytes):
    """The game's per-frame fingerprint: for each of the 10 pad bytes rotate left and mix it in, then add
    the frame number's low byte."""
    h = previous
    for b in pad_bytes:
        h = (((h << 1) & 0xFF) | (h >> 7)) ^ b
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
    a = Asm(ORG)
    # --- start up: screen off, interrupts off, clear 4 KB of RAM, write the marker, then screen and
    # once-a-frame interrupt on
    a.label("reset")
    a.b(0x78, 0xD8)                       # SEI, CLD
    a.b(0xA2, 0xFF, 0x9A)                 # LDX #$FF, TXS
    a.b(0xA9, 0x80)                       # LDA #$80
    a.abs(0x8D, 0x2100)                   # STA $2100 (screen off while setting up)
    a.b(0xA9, 0x00)                       # LDA #0
    for reg in (0x4200, 0x420B, 0x420C, 0x212C, 0x212D):
        a.abs(0x8D, reg)                  # no interrupt yet, no DMA, no backgrounds (just the backdrop colour)
    a.b(0xAA)                             # TAX
    a.label("clear")
    for page in range(16):
        a.abs(0x9D, page * 0x100)         # STA $page00,X
    a.b(0xE8)                             # INX
    a.branch(0xD0, "clear")               # BNE clear
    a.b(0xA2, 0x00)                       # LDX #0
    a.label("marker")
    a.b(0x8A, 0x49, 0xA5)                 # TXA, EOR #$A5
    a.b(0x95, MARKER_AT)                  # STA $40,X
    a.b(0x8A, 0x49, 0xFF, 0x18, 0x69, 0x5B)  # TXA, EOR #$FF, CLC, ADC #$5B  (= $5A - X)
    a.b(0x95, MARKER_AT + 16)             # STA $50,X
    a.b(0xE8, 0xE0, 16)                   # INX, CPX #16
    a.branch(0xD0, "marker")
    a.b(0xA9, 0xFF)
    a.abs(0x8D, 0x4201)                   # I/O bits high
    a.b(0xA9, 0x0F)
    a.abs(0x8D, 0x2100)                   # screen on, full brightness
    a.b(0xA9, 0x80)
    a.abs(0x8D, 0x4200)                   # interrupt at the start of every frame (no automatic pad reading)
    a.label("forever")
    a.jmp("forever")

    # --- once a frame
    a.label("nmi")
    a.b(0x48, 0x8A, 0x48, 0x98, 0x48)     # PHA, TXA, PHA, TYA, PHA
    a.abs(0xAD, 0x4210)                   # LDA $4210 (acknowledge the interrupt)
    a.b(0xE6, 0x00)                       # INC $00
    a.branch(0xD0, "counted")
    a.b(0xE6, 0x01)                       # INC $01
    a.branch(0xD0, "counted")
    a.b(0xE6, 0x02)                       # INC $02
    a.label("counted")
    # backdrop colour from the frame number, so the picture changes every frame
    a.b(0xA9, 0x00)
    a.abs(0x8D, 0x2121)                   # colour 0
    a.b(0xA5, 0x00)
    a.abs(0x8D, 0x2122)                   # low byte
    a.b(0xA5, 0x00, 0x4A)                 # LDA $00, LSR A
    a.abs(0x8D, 0x2122)                   # high byte
    # read the pads: latch, then 16 reads with I/O bit 7 high (pad 1 on $4016; pads 2 and 3 on $4017),
    # then 16 more with it low (pads 4 and 5 on $4017)
    a.b(0xA9, 0xFF)
    a.abs(0x8D, 0x4201)
    a.b(0xA9, 0x01)
    a.abs(0x8D, 0x4016)
    a.b(0xA9, 0x00)
    a.abs(0x8D, 0x4016)
    a.b(0xA2, 16)                         # LDX #16
    a.label("read1")
    a.abs(0xAD, 0x4016)                   # LDA $4016
    a.b(0x4A, 0x26, 0x31, 0x26, 0x30)     # LSR A, ROL $31, ROL $30   (pad 1)
    a.abs(0xAD, 0x4017)                   # LDA $4017
    a.b(0x4A, 0x26, 0x33, 0x26, 0x32)     # pad 2
    a.b(0x4A, 0x26, 0x35, 0x26, 0x34)     # pad 3
    a.b(0xCA)                             # DEX
    a.branch(0xD0, "read1")
    a.b(0xA9, 0x7F)
    a.abs(0x8D, 0x4201)                   # I/O bit 7 low
    # latch again before reading pads 4 and 5: RetroArch 1.22.2's snes9x doesn't restart the pads 4/5 count
    # on the first latch (CI run 41179703825: pad 4 always read as all buttons held), a second latch with the
    # I/O bit low does (and real multitaps are fine with it)
    a.b(0xA9, 0x01)
    a.abs(0x8D, 0x4016)
    a.b(0xA9, 0x00)
    a.abs(0x8D, 0x4016)
    a.b(0xA2, 16)
    a.label("read2")
    a.abs(0xAD, 0x4017)
    a.b(0x4A, 0x26, 0x37, 0x26, 0x36)     # pad 4
    a.b(0x4A, 0x26, 0x39, 0x26, 0x38)     # pad 5
    a.b(0xCA)
    a.branch(0xD0, "read2")
    a.b(0xA9, 0xFF)
    a.abs(0x8D, 0x4201)                   # I/O bits high again
    a.b(0xA2, 2 * PADS - 1)               # LDX #9
    a.label("copy")
    a.b(0xB5, 0x30, 0x95, 0x10)           # LDA $30,X ; STA $10,X
    a.b(0xCA)
    a.branch(0x10, "copy")                # BPL copy
    # fingerprint
    a.b(0xA5, 0x03, 0xA2, 0x00)           # LDA $03, LDX #0
    a.label("mix")
    a.b(0x0A, 0x69, 0x00)                 # ASL A, ADC #0   (rotate left)
    a.b(0x55, 0x10)                       # EOR $10,X
    a.b(0xE8, 0xE0, 2 * PADS)             # INX, CPX #10
    a.branch(0xD0, "mix")
    a.b(0x18, 0x65, 0x00)                 # CLC, ADC $00
    a.b(0x85, 0x03)                       # STA $03
    a.b(0xA6, 0x00)                       # LDX $00
    a.abs(0x9D, 0x0300)                   # STA $0300,X
    # button change? note it in the list
    a.b(0xA2, 0x00)
    a.label("compare")
    a.b(0xB5, 0x10, 0xD5, 0x20)           # LDA $10,X ; CMP $20,X
    a.branch(0xD0, "changed")
    a.b(0xE8, 0xE0, 2 * PADS)
    a.branch(0xD0, "compare")
    a.jmp("finished")
    a.label("changed")
    a.b(0xA5, 0x04, 0x0A, 0x0A, 0x0A, 0x0A, 0x85, 0x06)   # entry address low = place * 16
    a.b(0xA5, 0x04, 0x4A, 0x4A, 0x4A, 0x4A)               # high = $08 + place / 16
    a.b(0x18, 0x69, CHANGES_AT >> 8, 0x85, 0x07)
    a.b(0xA0, 0x00)                       # LDY #0
    a.b(0xA5, 0x00, 0x91, 0x06, 0xC8)     # LDA $00, STA ($06),Y, INY
    a.b(0xA5, 0x01, 0x91, 0x06, 0xC8)     # LDA $01, STA ($06),Y, INY
    a.b(0xA2, 0x00)
    a.label("note")
    a.b(0xB5, 0x10, 0x95, 0x20)           # LDA $10,X ; STA $20,X (remember these buttons)
    a.b(0x91, 0x06, 0xC8, 0xE8)           # STA ($06),Y, INY, INX
    a.b(0xE0, 2 * PADS)
    a.branch(0xD0, "note")
    a.b(0xA5, 0x04, 0x18, 0x69, 0x01, 0x29, CHANGE_SLOTS - 1, 0x85, 0x04)  # next place (wraps at 128)
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
    image = bytearray([0xEA] * 0x8000)  # 32 KB, seen at $8000-$FFFF
    image[0:len(code)] = code
    header = 0x7FC0
    image[header:header + 21] = b"GAME NIGHT 4P TEST   "
    image[header + 0x15] = 0x20   # LoROM, normal speed
    image[header + 0x16] = 0x00   # ROM only
    image[header + 0x17] = 0x05   # 32 KB
    image[header + 0x18] = 0x00   # no save RAM
    image[header + 0x19] = 0x01   # North America (60 frames a second)
    image[header + 0x1A] = 0x00
    image[header + 0x1B] = 0x00
    vectors = {  # both the 65816's own and its 6502-compatible start-up ones
        0x7FE4: "irq", 0x7FE6: "irq", 0x7FE8: "irq", 0x7FEA: "nmi", 0x7FEE: "irq",
        0x7FF4: "irq", 0x7FF8: "irq", 0x7FFA: "nmi", 0x7FFC: "reset", 0x7FFE: "irq",
    }
    for at, name in vectors.items():
        image[at:at + 2] = bytes([labels[name] & 0xFF, labels[name] >> 8])
    image[header + 0x1C:header + 0x20] = bytes([0xFF, 0xFF, 0x00, 0x00])
    total = sum(image) & 0xFFFF
    image[header + 0x1C:header + 0x20] = bytes([~total & 0xFF, (~total >> 8) & 0xFF, total & 0xFF, total >> 8])
    return bytes(image)


if __name__ == "__main__":
    with open(sys.argv[1], "wb") as f:
        f.write(rom())
