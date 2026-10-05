#!/usr/bin/env python3
"""regdiff.py scenario frame [i0 i1] : log registers for instructions i0..i1 of
`frame` on base and shifted ROM; report the first instruction after which a
data register differs in a way that is not a pointer shift."""
import sys, os, json, numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, 'emu'))
from harness import Emu
from scenario import SCENARIOS
name, frame = sys.argv[1], int(sys.argv[2])
i0 = int(sys.argv[3]) if len(sys.argv) > 3 else 0
i1 = int(sys.argv[4]) if len(sys.argv) > 4 else (1 << 18)
INS = sorted(json.load(open('build/shift/inserted.json')))
def back(b):
    b &= 0xFFFFFF
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
            for e in es: e.reglog(i0, i1); e.pclog(True)
        for e in es: e.run(1)
        f += 1
        if f > frame: break
    if f > frame: break
ra, rb = es[0].reglog(), es[1].reglog()
names = ['pc'] + ['d%d' % i for i in range(8)] + ['a%d' % i for i in range(8)]
def explained(x, y):
    if x == y: return True
    if back(y) == (x & 0xFFFFFF) and (x >> 24) == (y >> 24): return True
    if back((y * 2) & 0xFFFFFF) == ((x * 2) & 0xFFFFFF): return True     # DMA word address
    return False
IGNORE = [(0xA06, 0xAF0), (0xD80, 0xE88)]   # VDP DMA helpers: build VDP registers from pointer bits
def ignored(pc):
    return any(a <= pc < b for a, b in IGNORE)
for k in range(min(len(ra), len(rb))):
    if back(int(rb[k, 0])) != int(ra[k, 0]):
        print('pc diverges at #%d: base %06X shifted %06X' % (i0 + k, ra[k, 0], rb[k, 0])); break
    bad = [names[j] for j in range(1, 17) if not explained(int(ra[k, j]), int(rb[k, j]))]
    if bad and not ignored(int(ra[k, 0])):
        print('#%d before pc %06X registers differ: %s' % (i0 + k, ra[k, 0], ', '.join('%s %08X/%08X' % (nm, ra[k, names.index(nm)], rb[k, names.index(nm)]) for nm in bad)))
        for j in range(max(0, k - 5), k + 1):
            print('   #%d pc %06X' % (i0 + j, ra[j, 0]))
        break
