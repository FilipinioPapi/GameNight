#!/usr/bin/env python3
"""Checks the 4-player SNES test cartridge's own code on a 6502 simulator (py65), before it goes near CI.

    pip install py65==1.2.0 && python check_snes_multitap_rom.py

The cartridge runs in the SNES CPU's 6502-compatible mode, so a 6502 simulator runs it exactly. The SNES
controller ports are simulated the way snes9x does them (snes9x controls.cpp: a latch write to $4016 resets
the read counters; $4017 bit 0 and 1 are multitap pads 2 and 3 while $4201 bit 7 is high, pads 4 and 5 while
it is low, each pair with its own counter). Runs the start-up code, then 1,000 frames with made-up presses
on all five pads, and checks the RAM after every frame against make_snes_multitap_rom.py's description.
"""
import random
import sys
from pathlib import Path

from py65.devices.mpu6502 import MPU
from py65.memory import ObservableMemory

sys.path.insert(0, str(Path(__file__).parent))
import make_snes_multitap_rom as cart  # noqa: E402

image = cart.rom()
assert len(image) == 0x8000
mem = ObservableMemory()
for i, v in enumerate(image):
    mem[0x8000 + i] = v

pads = [0] * 5
port = {"idx0": 0, "idx1_high": 0, "idx1_low": 0, "iobit": 0x80, "latched": False}
writes = {}


def bit(value, r):
    return 1 if r >= 16 else (value >> (15 - r)) & 1


def write_4016(address, value):
    if value & 1:
        port["idx0"] = port["idx1_high"] = port["idx1_low"] = 0


def write_4201(address, value):
    port["iobit"] = value & 0x80


def read_4016(address):
    r = port["idx0"]
    port["idx0"] += 1
    return bit(pads[0], r)


def read_4017(address):
    if port["iobit"]:
        r = port["idx1_high"]
        port["idx1_high"] += 1
        return bit(pads[1], r) | bit(pads[2], r) << 1
    r = port["idx1_low"]
    port["idx1_low"] += 1
    return bit(pads[3], r) | bit(pads[4], r) << 1


def note_write(address, value):
    writes.setdefault(address, []).append(value)


mem.subscribe_to_write([0x4016], write_4016)
mem.subscribe_to_write([0x4201], write_4201)
mem.subscribe_to_write([0x2100, 0x2121, 0x2122, 0x4200], note_write)
mem.subscribe_to_read([0x4016], read_4016)
mem.subscribe_to_read([0x4017], read_4017)
mem.subscribe_to_read([0x4210], lambda a: 0x80)

cpu = MPU(memory=mem)
for a in range(0x2000):
    mem[a] = 0x77  # junk, so the RAM clear is checked
cpu.pc = mem[0xFFFC] | mem[0xFFFD] << 8
forever = None
for _ in range(200000):
    cpu.step()
    if writes.get(0x4200, [None])[-1] == 0x80:
        forever = cpu.pc
        break
assert forever is not None, "start-up never turned the frame interrupt on"
for _ in range(10):
    cpu.step()
assert writes[0x2100][-1] == 0x0F, "start-up didn't turn the screen on"
assert bytes(mem[cart.MARKER_AT:cart.MARKER_AT + 32]) == cart.MARKER, "marker is wrong"
assert cart.MARKER not in image, "the marker must not be in the cartridge itself (the test would find the wrong copy)"
assert all(mem[a] == 0 for a in range(0x1000) if not (cart.MARKER_AT <= a < cart.MARKER_AT + 32) and a < 0x1F0), "RAM wasn't cleared"


def frame():
    """Fire the start-of-frame interrupt (6502-compatible mode: push PC and P, vector at $FFFA) and run it."""
    sp = cpu.sp
    cpu.stPush(cpu.pc >> 8)
    cpu.stPush(cpu.pc & 0xFF)
    cpu.stPush(cpu.p)
    cpu.p |= cpu.INTERRUPT
    cpu.pc = mem[0xFFFA] | mem[0xFFFB] << 8
    for _ in range(20000):
        cpu.step()
        if cpu.sp == sp and cpu.pc == forever:
            return
    raise AssertionError("frame code never returned")


def as_bytes(values):
    out = []
    for v in values:
        out += [v >> 8, v & 0xFF]
    return out


rng = random.Random(7)
h, changes, prev, log = 0, 0, None, []
history = {}
for f in range(1, 1001):
    for i in range(5):
        if rng.random() < 0.3:
            pads[i] = rng.randrange(0x10000) & 0xFFF0  # real pads send 0 in the last 4 bits
    writes.pop(0x2122, None)
    frame()
    pb = as_bytes(pads)
    h = cart.fingerprint(h, f, pb)
    history[f] = h
    if prev is None and pb == [0] * 10:
        prev = pb
    if pb != prev:
        log.append(bytes([f & 0xFF, (f >> 8) & 0xFF, *pb, 0, 0, 0, 0]))
        changes += 1
        prev = pb
    got_frame = mem[0] | mem[1] << 8 | mem[2] << 16
    assert got_frame == f, f"frame {f}: game says {got_frame}"
    assert list(mem[0x10:0x1A]) == pb, f"frame {f}: pads {bytes(mem[0x10:0x1A]).hex()}, wanted {bytes(pb).hex()}"
    assert mem[0x03] == h, f"frame {f}: fingerprint {mem[0x03]:02x}, wanted {h:02x}"
    assert mem[0x0300 + (f & 0xFF)] == h, f"frame {f}: fingerprint list is wrong"
    assert mem[0x08] | mem[0x09] << 8 == changes, f"frame {f}: change count {mem[0x08] | mem[0x09] << 8}, wanted {changes}"
    assert mem[0x04] == changes % cart.CHANGE_SLOTS
    assert writes.get(0x2122) == [f & 0xFF, (f & 0xFF) >> 1], f"frame {f}: colour writes {writes.get(0x2122)}"

for k in range(max(1, f - 255), f + 1):
    assert mem[0x0300 + (k & 0xFF)] == history[k], f"fingerprint list wrong for frame {k}"
assert changes > cart.CHANGE_SLOTS, "test should wrap the change list"
for i, entry in enumerate(log[-cart.CHANGE_SLOTS:]):
    n = changes - min(cart.CHANGE_SLOTS, changes) + i
    at = cart.CHANGES_AT + (n % cart.CHANGE_SLOTS) * cart.CHANGE_SIZE
    got = bytes(mem[at:at + cart.CHANGE_SIZE])
    assert got == entry, f"change {n}: list has {got.hex()}, wanted {entry.hex()}"
print(f"ok: 1000 frames, {changes} button changes on 5 pads; frame number, pads, fingerprint, both lists and the marker all match")
