#!/usr/bin/env python3
"""Run a scenario on base and shifted ROM; at the first divergent frame (or
given frame) print RAM word differences that are not explained by the shift."""
import sys, os
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, 'emu'))
from harness import Emu
from scenario import SCENARIOS
pad, scen = int(sys.argv[1], 0), SCENARIOS[sys.argv[2]]()
stop = int(sys.argv[3]) if len(sys.argv) > 3 else None
es = [Emu('baserom.gen'), Emu('build/shift/rom.gen')]
f = 0; done = False
hist = []
for btns, n in scen:
    for e in es: e.set_buttons(*btns)
    for _ in range(n):
        for e in es: e.run(1)
        f += 1
        if (stop and f >= stop) or (not stop and es[0].frame_hash() != es[1].frame_hash()):
            done = True; break
    if done: break
print('frame', f)
a, b = es[0].ram(), es[1].ram()
hi = pad >> 16
for i in range(0, 0xFF00, 2):
    x = int.from_bytes(a[i:i+2], 'big'); y = int.from_bytes(b[i:i+2], 'big')
    if x == y: continue
    d = (y - x) & 0xFFFF
    if d == hi and 0 < x < 0x40: continue                  # pointer high word
    if (x & 0xFF00) == 0x9700 and d == (pad >> 17): continue  # DMA source high reg
    print('%06X %04X %04X  (+%04X)' % (0xFF0000 + i, x, y, d))
