#!/usr/bin/env python3
"""Find the first frame where RAM differs between base and shifted ROM in a
way not explained by the shift (pointer words / tagged pointers / DMA regs)."""
import sys, os
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, 'emu'))
from harness import Emu
from scenario import SCENARIOS
pad, name = int(sys.argv[1], 0), sys.argv[2]
step = int(sys.argv[3]) if len(sys.argv) > 3 else 5
hi = pad >> 16
EXTRA = set(int(x, 0) & 0xFFFF for x in sys.argv[4].split(',')) if len(sys.argv) > 4 else set()
def unexplained(a, b):
    out = []
    for i in range(0, 0xFD00, 2):   # skip stack area
        x = int.from_bytes(a[i:i+2], 'big'); y = int.from_bytes(b[i:i+2], 'big')
        if x == y: continue
        d = (y - x) & 0xFFFF
        if d == hi and 0x02 <= (x & 0xFF) < 0x40: continue   # (tagged) pointer high word
        if (x & 0xFF00) == 0x9700 and d == (pad >> 17): continue
        if d in EXTRA: continue
        out.append('%06X %04X %04X' % (0xFF0000 + i, x, y))
    return out
es = [Emu('baserom.gen'), Emu('build/shift/rom.gen')]
f = 0
for btns, n in SCENARIOS[name]():
    for e in es: e.set_buttons(*btns)
    for _ in range(n):
        for e in es: e.run(1)
        f += 1
        if f % step == 0:
            u = unexplained(es[0].ram(), es[1].ram())
            if u:
                print('frame', f, u[:24]); sys.exit(1)
print('no unexplained RAM difference in', f, 'frames')
