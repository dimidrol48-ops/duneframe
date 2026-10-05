#!/usr/bin/env python3
"""Align a variant ROM (another build of the same source) against the base
disassembly.  Every base function becomes a byte pattern with its
layout-dependent operands masked (branches, absolute addresses, PC-relative
displacements, 32-bit immediates); patterns are searched in the variant in
address order with a running offset.

usage: variant_align.py variant.gen [out.json]
Writes the function mapping and prints unmatched base functions and variant
gaps (the real differences)."""
import sys, os, re, json, pickle, bisect
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, 'disasm'))
from names import NAMES

MASK_KINDS = {'branch', 'pcdisp', 'pcindex', 'absw', 'absl'}


def load():
    A, labels = pickle.load(open(os.path.join(ROOT, 'build', 'analysis.pkl'), 'rb'))
    return A, labels


def func_ranges(A):
    f = sorted(a for a in A.funcs if a in A.code)
    out = []
    for i, a in enumerate(f):
        end = f[i + 1] if i + 1 < len(f) else a + 2
        b = a
        while b < end and b in A.code:
            b += A.code[b].length
        out.append((a, b))
    return out


def pattern(A, rom, s, e):
    """Regex bytes for [s,e) and the number of fixed bytes."""
    parts, fixed = [], 0
    a = s
    while a < e:
        ins = A.code[a]
        raw = bytearray(rom[a:a + ins.length])
        mask = [False] * ins.length
        for o in ins.ops:
            if o.ext is None or not o.extlen:
                continue
            if o.kind in MASK_KINDS or (o.kind == 'imm' and o.extlen == 4):
                for k in range(o.ext, o.ext + o.extlen):
                    mask[k] = True
        # short branches keep their displacement in the opcode word
        if ins.mnem.startswith(('bra.s', 'bsr.s')) or (ins.mnem.startswith('b') and ins.mnem.endswith('.s')):
            mask[1] = True
        if ins.mnem.startswith('db'):
            mask[2] = mask[3] = True
        for k in range(ins.length):
            if mask[k]:
                parts.append(b'.')
            else:
                parts.append(re.escape(bytes([raw[k]])))
                fixed += 1
        a += ins.length
    return re.compile(b''.join(parts), re.S), fixed


def align(variant):
    A, labels = load()
    rom = open(os.path.join(ROOT, 'baserom.gen'), 'rb').read()
    var = open(variant, 'rb').read()
    funcs = func_ranges(A)
    delta = 0
    mapping, unmatched = {}, []
    for s, e in funcs:
        if e - s < 8:
            continue
        rx, fixed = pattern(A, rom, s, e)
        if fixed < 6:
            continue
        guess = s + delta
        m = rx.match(var, guess) if 0 <= guess < len(var) else None
        if not m:
            lo, hi = max(0, guess - 0x4000), min(len(var), guess + 0x40000)
            best = None
            for mm in rx.finditer(var, lo, hi):
                d = abs(mm.start() - guess)
                if best is None or d < best[0]:
                    best = (d, mm)
                if mm.start() > guess and best and best[0] < mm.start() - guess:
                    break
            m = best[1] if best else None
        if m:
            mapping[s] = m.start()
            delta = m.start() - s
        else:
            unmatched.append((s, e))
    return A, rom, var, funcs, mapping, unmatched


def main():
    variant = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else None
    A, rom, var, funcs, mapping, unmatched = align(variant)
    print('functions: %d matched, %d unmatched' % (len(mapping), len(unmatched)))
    for s, e in unmatched:
        print('  base %06X-%06X %s' % (s, e, NAMES.get(s, 'sub_%06X' % s)))
    # delta segments
    segs, last = [], None
    for s in sorted(mapping):
        d = mapping[s] - s
        if d != last:
            segs.append((s, d)); last = d
    print('offset segments:')
    for s, d in segs:
        print('  from base %06X: %+#x' % (s, d))
    if out:
        json.dump({'%06X' % k: v for k, v in mapping.items()}, open(out, 'w'), indent=0)


if __name__ == '__main__':
    main()
