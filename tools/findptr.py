#!/usr/bin/env python3
"""Shift-test debugging helper: find first divergence for a scenario between
base ROM and build/shift/rom.gen, list unexpected accesses, and look up where
the stray target values are stored (data longs / tagged longs / immediates)."""
import sys, os, struct, pickle, subprocess, numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path[:0] = [os.path.join(HERE, 'emu'), os.path.join(HERE, 'disasm')]
from harness import Emu
from scenario import SCENARIOS

import json
INS = sorted(json.load(open('build/shift/inserted.json')))
scen_name = sys.argv[1]
FULL = len(sys.argv) > 2 and sys.argv[2] == 'full'
pad = sum(p for _, p in INS)
ref, sh = 'baserom.gen', 'build/shift/rom.gen'
scen = SCENARIOS[scen_name]()
es = [Emu(ref), Emu(sh)]
f = 0; first = None
for btns, n in scen:
    for e in es: e.set_buttons(*btns)
    for _ in range(n):
        for e in es: e.run(1)
        f += 1
        if not FULL and es[0].frame_hash() != es[1].frame_hash():
            first = f; break
    if first: break
print('first divergent frame', first)
(exa, rda, whoa, _), (exb, rdb, whob, _) = [e.trace() for e in es]
rom = open(ref, 'rb').read(); n = len(rom)
def back(b):
    off = 0
    for at, p in INS:
        if b < at + off:
            return b - off
        if b < at + off + p:
            return -1
        off += p
    return b - off
bad = []
for kind, A_, B_ in (('exec', exa, exb), ('read', rda, rdb)):
    for b in np.nonzero(B_[:n + pad])[0]:
        a = back(int(b))
        if a < 0 or not A_[a]:
            bad.append((kind, int(b)))
groups = []
for kind, b in sorted(bad):
    if groups and groups[-1][0] == kind and b <= groups[-1][2] + 16: groups[-1][2] = b
    else: groups.append([kind, b, b])
A, L = pickle.load(open('build/analysis.pkl', 'rb'))
for kind, s, e in groups[:20]:
    pc = whob[s >> 1] if kind == 'read' else 0
    opc = back(int(pc)) if pc else 0
    print('%s at %06X-%06X  reader pc(shifted) %06X (orig %06X)' % (kind, s, e, pc, opc))
    # stray address s was the ORIGINAL address of something; look for it stored somewhere
    for v in range(s - 16, s + 1, 2):
        for i in range(0, n - 3, 2):
            w = struct.unpack_from('>I', rom, i)[0]
            if (w & 0xFFFFFF) == v and (w == v or (w >> 24)):
                own = A.owner[i]
                print('   value %06X stored at %06X %s' % (v, i, ('in insn @%06X' % own) if own >= 0 else ('data dptr=%s rd=%02x' % (A.dptr.get(i), A.rd[i]))))
