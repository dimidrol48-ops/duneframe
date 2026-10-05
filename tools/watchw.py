#!/usr/bin/env python3
"""watchw.py scenario frame lo hi : log writes to [lo,hi) on base and shifted ROM up to frame."""
import sys, os
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, 'emu'))
from harness import Emu
from scenario import SCENARIOS
name, frame, lo, hi = sys.argv[1], int(sys.argv[2]), int(sys.argv[3], 0), int(sys.argv[4], 0)
start = int(sys.argv[5]) if len(sys.argv) > 5 else 0
es = [Emu('baserom.gen'), Emu('build/shift/rom.gen')]
f = 0
for btns, n in SCENARIOS[name]():
    k = min(n, frame - f)
    for e in es:
        e.set_buttons(*btns)
    for _ in range(k):
        if f == start:
            for e in es: e.watch(lo, hi)
        for e in es: e.run(1)
        f += 1
    if f >= frame: break
for e, nm in zip(es, ('base', 'shift')):
    log = e.watch_log()
    print(nm, len(log), [(hex(p), hex(a), hex(v)) for p, a, v in log[-10:]])
