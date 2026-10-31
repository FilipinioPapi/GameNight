#!/usr/bin/env python3
"""Checks the netplay test cartridge's own code on a 6502 simulator (py65), before it goes near CI.

    pip install py65==1.2.0 && python check_netplay_rom.py

Runs the start-up code, then 1,000 frames with made-up button presses for both players, and checks
the RAM after every frame against make_netplay_rom.py's description: frame number, buttons,
fingerprint (against the Python version of the sum), the 256-frame fingerprint list and the
button-change list (including wrapping around after 256 changes).
"""
import random
import sys
from pathlib import Path

from py65.devices.mpu6502 import MPU
from py65.memory import ObservableMemory

sys.path.insert(0, str(Path(__file__).parent))
import make_netplay_rom as cart  # noqa: E402

image = cart.rom()
prg = image[16:16 + 16384]
mem = ObservableMemory()
for i, v in enumerate(prg):
    mem[0x8000 + i] = v
    mem[0xC000 + i] = v

pads = {"p1": 0, "p2": 0}
shift = {0x4016: 0, 0x4017: 0}
vblank = {"on": True}


def write_4016(address, value):
    if value & 1:
        shift[0x4016], shift[0x4017] = pads["p1"], pads["p2"]


def read_pad(address):
    v = (shift[address] >> 7) & 1  # A first
    shift[address] = (shift[address] << 1) & 0xFF
    return v


def read_2002(address):
    return 0x80 if vblank["on"] else 0


mem.subscribe_to_write([0x4016], write_4016)
mem.subscribe_to_read([0x4016, 0x4017], read_pad)
mem.subscribe_to_read([0x2002], read_2002)

cpu = MPU(memory=mem)
cpu.pc = mem[0xFFFC] | mem[0xFFFD] << 8
forever = None
for _ in range(100000):
    cpu.step()
    if mem[0x2000] == 0x80:
        forever = cpu.pc
        break
assert forever is not None, "start-up never turned the frame interrupt on"
for _ in range(10):
    cpu.step()
assert all(mem[a] == 0 for a in range(0x800) if a < 0x1F0), "RAM wasn't cleared"


def frame():
    """Fire the start-of-frame interrupt and run it until it returns."""
    sp = cpu.sp
    cpu.stPush(cpu.pc >> 8)
    cpu.stPush(cpu.pc & 0xFF)
    cpu.stPush(cpu.p)
    cpu.p |= cpu.INTERRUPT
    cpu.pc = mem[0xFFFA] | mem[0xFFFB] << 8
    for _ in range(5000):
        cpu.step()
        if cpu.sp == sp and mem[cpu.pc] != 0x40 and cpu.pc == forever:
            return
    raise AssertionError("frame code never returned")


rng = random.Random(7)
h, changes, prev, log = 0, 0, (0, 0), []
history = {}
for f in range(1, 1001):
    if rng.random() < 0.4:
        pads["p1"] = rng.randrange(256)
    if rng.random() < 0.4:
        pads["p2"] = rng.randrange(256)
    frame()
    p = (pads["p1"], pads["p2"])
    h = cart.fingerprint(h, f, *p)
    history[f] = h
    if p != prev:
        log.append((f & 0xFF, f >> 8, *p))
        changes += 1
        prev = p
    got_frame = mem[0] | mem[1] << 8 | mem[2] << 16
    assert got_frame == f, f"frame {f}: game says {got_frame}"
    assert (mem[0x10], mem[0x11]) == p, f"frame {f}: buttons {mem[0x10]:02x} {mem[0x11]:02x}, wanted {p}"
    assert mem[0x03] == h, f"frame {f}: fingerprint {mem[0x03]:02x}, wanted {h:02x}"
    assert mem[0x0300 + (f & 0xFF)] == h, f"frame {f}: fingerprint list is wrong"
    assert mem[0x08] | mem[0x09] << 8 == changes, f"frame {f}: change count"
    assert mem[0x04] == changes & 0xFF

for k in range(max(0, f - 255), f + 1):
    assert mem[0x0300 + (k & 0xFF)] == history[k], f"fingerprint list wrong for frame {k}"
assert changes > 256, "test should wrap the change list"
for i, entry in enumerate(log[-256:]):
    n = changes - min(256, changes) + i
    at = 0x0400 + (n & 0xFF) * 4
    assert tuple(mem[at:at + 4]) == entry, f"change {n}: list has {mem[at:at + 4]}, wanted {entry}"
print(f"ok: 1000 frames, {changes} button changes; frame number, buttons, fingerprint and both lists all match")
