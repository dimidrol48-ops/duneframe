#!/usr/bin/env python3
"""pcdiff.py scenario start frames : log every instruction (pc, cycle) on base
and shifted ROM from frame `start` for `frames` frames; report the first
point where the (mapped) PC sequence or the cycle timing diverges."""
import sys, os, json, numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, 'emu'))
from harness import Emu
from scenario import SCENARIOS
name, start, nfr = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
INS = sorted(json.load(open('build/shift/inserted.json')))
def back(b):
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
        if f == start:
            for e in es: e.pclog(True)
        for e in es: e.run(1)
        f += 1
        if f >= start + nfr: break
    if f >= start + nfr: break
(pa, ca), (pb, cb) = es[0].pclog(), es[1].pclog()
pbm = np.array([back(int(x)) if x < 0x400000 else int(x) for x in pb])
m = min(len(pa), len(pbm))
dp = np.nonzero(pa[:m] != pbm[:m])[0]
first_pc = int(dp[0]) if len(dp) else None
dc = (ca[:m].astype(np.int64) - cb[:m].astype(np.int64))
chg = np.nonzero(np.diff(dc))[0]
print('logged', len(pa), len(pb), 'first pc divergence at index', first_pc)
lim = first_pc if first_pc is not None else m
chg = chg[chg < lim]
if len(chg):
    i = int(chg[0]) + 1
    print('first cycle-offset change at index', i, 'delta before', dc[i - 1], 'after', dc[i])
    for k in range(max(0, i - 6), i + 4):
        print('   %7d pc %06X  cyc %d / %d' % (k, pa[k], ca[k], cb[k]))
if first_pc is not None:
    for k in range(max(0, first_pc - 6), first_pc + 3):
        print('   %7d base %06X shift %06X(%06X)' % (k, pa[k], pb[k], pbm[k]))
