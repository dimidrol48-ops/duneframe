#!/usr/bin/env python3
"""Find unsymbolized pointers: run original and shifted ROM for N frames with
tracing, map the shifted ROM's accesses back to original addresses and list
accesses that the original never made (grouped into ranges, with reader PC)."""
import sys, os, numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'emu'))
from harness import Emu
from scenario import SCENARIOS

def run(rom, scen, frames):
    e = Emu(rom)
    f = 0
    for btns, n in scen:
        e.set_buttons(*btns)
        k = min(n, frames - f)
        e.run(k); f += k
        if f >= frames: break
    ex, rd, who, rx = e.trace()
    r = (ex.copy(), rd.copy(), who.copy())
    e.close()
    return r

def main():
    ref, shifted, P, pad, frames = sys.argv[1], sys.argv[2], int(sys.argv[3], 0), int(sys.argv[4]), int(sys.argv[5])
    scen = SCENARIOS[sys.argv[6] if len(sys.argv) > 6 else 'boot']()
    exa, rda, whoa = run(ref, scen, frames)
    exb, rdb, whob = run(shifted, scen, frames)
    n = len(open(ref, 'rb').read())
    # back-map shifted: addr b -> a = b if b < P else b - pad  (padding itself -> -1)
    def back(b):
        if b < P: return b
        if b < P + pad: return -1
        return b - pad
    bad = []
    for kind, A, B in (('exec', exa, exb), ('read', rda, rdb)):
        idx = np.nonzero(B[:n + pad])[0]
        for b in idx:
            a = back(int(b))
            if a < 0 or not A[a]:
                bad.append((kind, a, int(b)))
    print('%d unexpected accesses' % len(bad))
    # group
    groups = []
    for kind, a, b in sorted(bad, key=lambda x: (x[0], x[2])):
        if groups and groups[-1][0] == kind and b <= groups[-1][2] + 16:
            groups[-1][2] = b
        else:
            groups.append([kind, b, b])
    for kind, s, e in groups[:60]:
        pc = whob[s >> 1] if kind == 'read' else 0
        print('%s shifted %06X-%06X (orig-equivalent %06X) reader pc %06X' % (kind, s, e, back(s), pc))

main()
