#!/usr/bin/env python3
"""readdiff.py scenario frame : log all CPU data reads in `frame` on base and
shifted ROM; report the first read whose value differs (ROM addresses mapped
back through the shift)."""
import sys, os, json
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, 'emu'))
from harness import Emu
from scenario import SCENARIOS
name, frame = sys.argv[1], int(sys.argv[2])
INS = sorted(json.load(open('build/shift/inserted.json')))
def back(b):
    if b >= 0x400000: return b
    off = 0
    for at, p in INS:
        if b < at + off: return b - off
        if b < at + off + p: return -1
        off += p
    return b - off
es = [Emu('baserom.gen'), Emu('build/shift/rom.gen')]
f = 0
for btns, n in SCENARIOS[name]():
    for e in es: e.set_buttons(*btns)
    for _ in range(n):
        if f == frame:
            for e in es: e.rwatch(0xFFFFFFFE)
        for e in es: e.run(1)
        f += 1
        if f > frame: break
    if f > frame: break
la, lb = es[0].rwatch_log(), es[1].rwatch_log()
print('reads', len(la), len(lb))
romA = open('baserom.gen', 'rb').read(); romB = open('build/shift/rom.gen', 'rb').read()
def fwd(a):
    off = 0
    for at, p in INS:
        if a >= at: off += p
    return a + off
def relocated(a):
    return a < len(romA) and romA[a:a + 4] != romB[fwd(a):fwd(a) + 4]
shown = 0
for k, ((pa, aa, va), (pb, ab, vb)) in enumerate(zip(la, lb)):
    if back(pb) != pa or back(ab) != aa:
        print('#%d ADDRESS/PC differs: base pc %06X addr %06X | shifted pc %06X(%06X) addr %06X(%06X)' % (k, pa, aa, pb, back(pb), ab, back(ab)))
        break
    if va == vb:
        continue
    if aa < 0x400000 and relocated(aa):
        ok = (back(vb & 0xFFFFFF) == (va & 0xFFFFFF) and (va >> 24) == (vb >> 24) and va > 0xFFFF)
        if not ok and shown < 20:
            print('#%d reloc-read not a full pointer: pc %06X addr %06X val %X -> %X' % (k, pa, aa, va, vb)); shown += 1
        continue
    if aa >= 0xFF0000:
        ok = back(vb & 0xFFFFFF) == (va & 0xFFFFFF) or back(((vb >> 16) << 16) & 0xFFFFFF) == ((va >> 16) << 16) & 0xFFFFFF
        if not ok and shown < 20:
            print('#%d RAM value differs: pc %06X addr %06X val %X -> %X' % (k, pa, aa, va, vb)); shown += 1
        continue
    print('#%d ROM value differs (not relocated!): pc %06X addr %06X val %X -> %X' % (k, pa, aa, va, vb))
    break
