#!/usr/bin/env python3
"""vdpdiff.py scenario : compare VDP control-port writes between base and
shifted ROM frame by frame; report the first difference that is not a DMA
source register (0x95/0x96/0x97) change, with the writing PCs."""
import sys, os
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, 'emu'))
from harness import Emu
from scenario import SCENARIOS
es = [Emu('baserom.gen'), Emu('build/shift/rom.gen')]
for e in es: e.watch(0xC00004, 0xC00008)
f = 0
for btns, n in SCENARIOS[sys.argv[1]]():
    for e in es: e.set_buttons(*btns)
    for _ in range(n):
        for e in es: e.run(1)
        f += 1
        la, lb = es[0].watch_log(), es[1].watch_log()
        for k, (x, y) in enumerate(zip(la, lb)):
            if x[2] != y[2] and not ((x[2] & 0xFF00) in (0x9500, 0x9600, 0x9700) and (x[2] & 0xFF00) == (y[2] & 0xFF00)):
                print('frame', f, 'write#', k)
                print('  base ', [(hex(p), hex(v)) for p, a, v in la[max(0, k - 4):k + 2]])
                print('  shift', [(hex(p), hex(v)) for p, a, v in lb[max(0, k - 4):k + 2]])
                sys.exit(1)
        if len(la) != len(lb):
            print('frame', f, 'different number of VDP writes', len(la), len(lb)); sys.exit(1)
        for e in es: e.watch(0xC00004, 0xC00008)
print('no VDP command difference in', f, 'frames')
