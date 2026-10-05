#!/usr/bin/env python3
"""histdiff.py scenario start end : per-frame PC execution histograms of base
vs shifted ROM (mapped back); report first frame whose histograms differ and
the PCs with different counts."""
import sys, os, json, numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, 'emu'))
from harness import Emu
from scenario import SCENARIOS
name, start, end = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
INS = sorted(json.load(open('build/shift/inserted.json')))
n = len(open('baserom.gen', 'rb').read())
# mapping orig pc -> shifted pc
def fwd(a):
    off = 0
    for at, p in INS:
        if a >= at: off += p
    return a + off
orig = np.arange(0, n, 2)
shifted = np.array([fwd(int(a)) for a in orig])
es = [Emu('baserom.gen'), Emu('build/shift/rom.gen')]
f = 0
for btns, k in SCENARIOS[name]():
    for e in es: e.set_buttons(*btns)
    for _ in range(k):
        f += 1
        if f >= start:
            for e in es: e.hist(True)
        for e in es: e.run(1)
        if f >= start:
            ha = es[0].hist()[:n // 2].astype(np.int64)
            hb = es[1].hist()[(shifted >> 1)].astype(np.int64)
            d = np.nonzero(ha != hb)[0]
            if len(d):
                print('frame', f, 'total insns', ha.sum(), hb.sum())
                for i in d[:int(os.environ.get("HN", 25))]:
                    print('  pc %06X base %d shifted %d' % (orig[i], ha[i], hb[i]))
                sys.exit(1)
        if f >= end:
            print('no histogram difference up to', f); sys.exit(0)
