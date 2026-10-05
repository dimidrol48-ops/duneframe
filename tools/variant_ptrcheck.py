#!/usr/bin/env python3
"""Use a variant ROM (same source, different layout) as ground truth for the
base's data-pointer detection: a real pointer is relocated in the variant, a
false positive keeps its value although its 'target' moved.
usage: variant_ptrcheck.py variant.gen"""
import sys, os, pickle
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'disasm'))
import numpy as np
os.environ.setdefault('VARIANT_ROM', sys.argv[1])
from variant import AddressMap

def main():
    rom = open(os.path.join(HERE, '..', 'baserom.gen'), 'rb').read()
    var = open(sys.argv[1], 'rb').read()
    A, labels = pickle.load(open(os.path.join(HERE, '..', 'build', 'analysis.pkl'), 'rb'))
    amap = AddressMap(rom, var)
    amap.refine(A, rom, var)
    false_pos, ok, unknown = [], 0, 0
    for p, (kind, t, base) in sorted(A.dptr.items()):
        if kind not in ('L', 'A'):
            continue
        vp = int(amap.b2v[p]); vt = int(amap.b2v[t]) if t <= amap.n else -1
        if vp < 0 or vt < 0 or vt == t:
            unknown += 1; continue          # target did not move: no evidence
        bv = int.from_bytes(rom[p:p + 4], 'big')
        vv = int.from_bytes(var[vp:vp + 4], 'big')
        if vv == bv:
            false_pos.append((p, t))
        elif (vv & 0xFFFFFF) == vt:
            ok += 1
        else:
            unknown += 1
    print('confirmed %d, false positives %d, no evidence %d' % (ok, len(false_pos), unknown))
    for p, t in false_pos:
        print('  %06X -> %06X' % (p, t))
    # missed pointers: data (not code, not a known pointer) whose value moved
    # exactly like the address it names
    covered = set()
    for p, (kind, t, base) in A.dptr.items():
        covered.update(range(p, p + {'L': 4, 'A': 4, 'W': 2, 'R': 2, 'R8': 1}[kind]))
    missed = []
    for p in range(0x200, amap.n - 1, 2):
        if A.owner[p] >= 0 or p in covered:
            continue
        vp = int(amap.b2v[p])
        if vp < 0:
            continue
        for size in (4, 2):
            if any(q in covered or A.owner[q] >= 0 for q in range(p, p + size)):
                continue
            bv = int.from_bytes(rom[p:p + size], 'big')
            vv = int.from_bytes(var[vp:vp + size], 'big')
            t = bv & 0xFFFFFF
            if bv == vv or not (0x200 <= t < amap.n):
                continue
            vt = int(amap.b2v[t])
            if vt >= 0 and vt != t and (vv & 0xFFFFFF) == vt and (vv & 0xFF000000) == (bv & 0xFF000000):
                missed.append((p, size, t))
                break
    print('missed pointers: %d' % len(missed))
    for p, size, t in missed:
        print('  %06X %s -> %06X' % (p, 'L' if size == 4 else 'W', t))
    check_imms(A, rom, var, amap)

def check_imms(A, rom, var, amap):
    """Immediates / absolute operands: a value that moved like its target is
    a pointer, one that stayed while its target moved is not."""
    import config
    from names import NAMES
    from emit import Emitter
    A.cfg = config
    E = Emitter(A, NAMES, config)
    missed, false = [], []
    for a, ins in A.code.items():
        va = int(amap.b2v[a])
        if va < 0 or int(amap.b2v[a + ins.length - 1]) != va + ins.length - 1:
            continue
        if var[va:va + 2] != rom[a:a + 2]:
            continue                      # instruction itself changed
        for idx, o in enumerate(ins.ops):
            if o.kind != 'imm' or o.extlen != 4:
                continue
            bv = int.from_bytes(rom[a + o.ext:a + o.ext + 4], 'big')
            vv = int.from_bytes(var[va + o.ext:va + o.ext + 4], 'big')
            t = bv & 0xFFFFFF
            if not (0x200 <= t < amap.n):
                continue
            vt = int(amap.b2v[t])
            if vt < 0 or vt == t:
                continue
            is_ptr = E.imm_is_ptr(ins, o, idx)
            if vv == vt and not is_ptr:
                missed.append((a, t))
            elif vv == bv and is_ptr:
                false.append((a, t))
    print('immediates: missed %d, false %d' % (len(missed), len(false)))
    for a, t in missed:
        print('  IMM_PTR   %06X #%06X' % (a, t))
    for a, t in false:
        print('  IMM_NOPTR %06X #%06X' % (a, t))


if __name__ == '__main__':
    main()
