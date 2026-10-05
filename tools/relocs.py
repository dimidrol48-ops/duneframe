#!/usr/bin/env python3
"""List every relocated value between base ROM and a shifted build
(bytes that differ after undoing the shift), with trace read flags."""
import sys, pickle, numpy as np
sys.path.insert(0, 'tools/disasm')
a = open(sys.argv[1], 'rb').read(); b = open(sys.argv[2], 'rb').read()
P, pad = int(sys.argv[3], 0), int(sys.argv[4])
tr = np.load('traces/merged.npz'); rd = tr['rd']
A, L = pickle.load(open('build/analysis.pkl', 'rb'))
bb = b[:P] + b[P + pad:]
diffs = [i for i in range(len(a)) if a[i] != bb[i]]
grp = []
for i in diffs:
    if grp and i <= grp[-1][1] + 3: grp[-1][1] = i
    else: grp.append([i, i])
from collections import Counter
cls = Counter()
for s, e in grp:
    s2 = s & ~1
    owner = A.owner[s2]
    where = 'code@%06X' % owner if owner >= 0 else 'data'
    r = rd[s2]
    k = 'code' if owner >= 0 else ('L' if r & 0x8c else 'W' if r & 3 else 'dma' if r & 0x60 else 'none' if r == 0 else 'x')
    cls[k] += 1
    if len(sys.argv) > 5 and k in sys.argv[5].split(','):
        print('%06X-%06X %s rd=%02x  %s -> %s' % (s, e, where, r, a[s2 - 2:e + 3].hex(), bb[s2 - 2:e + 3].hex()))
print(cls)
