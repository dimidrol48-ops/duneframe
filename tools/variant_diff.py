#!/usr/bin/env python3
"""Instruction-level diff of the regions where a variant ROM differs from
the base (regions between functions matched by variant_align).
usage: variant_diff.py variant.gen"""
import sys, os, difflib
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, 'disasm'))
from variant_align import align, func_ranges
from m68k import Decoder as Disasm, Instr, Op
from names import NAMES


def gaps(funcs, mapping, var_len):
    """Base/variant ranges between consecutive matched functions whose
    contents differ."""
    ends = dict(funcs)
    ms = sorted(mapping)
    out = []
    for a, b in zip(ms, ms[1:]):
        be, bn = ends[a], b                     # base gap [be, bn)
        ve, vn = mapping[a] + (ends[a] - a), mapping[b]
        out.append((be, bn, ve, vn))
    return out


def norm(ins):
    ops = []
    for o in ins.ops:
        if o.kind in ('branch', 'pcdisp', 'pcindex', 'absw', 'absl'):
            ops.append(o.kind)
        elif o.kind == 'imm' and o.extlen == 4:
            ops.append('imm32')
        else:
            ops.append('%s:%s:%s:%s' % (o.kind, o.reg, o.disp, o.value))
    return ins.mnem + ' ' + ','.join(ops)


def linear(data, s, e, base=0):
    d = Disasm(data)
    out, a = [], s
    while a < e:
        try:
            ins = d.decode(a)
            if a + ins.length > e:
                raise ValueError
        except Exception:
            ins = Instr(a); ins.mnem = '.word'; ins.length = 2
            ins.ops = [Op('imm', value=int.from_bytes(data[a:a + 2], 'big'))]
        out.append(ins)
        a += ins.length
    return out


def main():
    A, rom, var, funcs, mapping, unmatched = align(sys.argv[1])
    total = 0
    for be, bn, ve, vn in gaps(funcs, mapping, len(var)):
        if bn - be == vn - ve and rom[be:bn] == var[ve:vn]:
            continue
        # compare using base instructions where known
        bi = linear(rom, be, bn); vi = linear(var, ve, vn)
        bt = [norm(i) for i in bi]; vt = [norm(i) for i in vi]
        if bt == vt:
            continue
        sm = difflib.SequenceMatcher(None, bt, vt, autojunk=False)
        ops = [op for op in sm.get_opcodes() if op[0] != 'equal']
        nb = sum(i2 - i1 for _, i1, i2, _, _ in ops); nv = sum(j2 - j1 for _, _, _, j1, j2 in ops)
        total += 1
        print('== base %06X-%06X (%d insns) / variant %06X-%06X (%d insns): %d hunks, -%d +%d' % (
            be, bn, len(bi), ve, vn, len(vi), len(ops), nb, nv))
        for tag, i1, i2, j1, j2 in ops:
            print('  %s base %06X:' % (tag, bi[i1].addr if i1 < len(bi) else bn))
            for i in bi[i1:i2]:
                print('     - %06X %s %s' % (i.addr, i.mnem, rom[i.addr:i.addr + i.length].hex()))
            for i in vi[j1:j2]:
                print('     + %06X %s %s' % (i.addr, i.mnem, var[i.addr:i.addr + i.length].hex()))
    print(total, 'regions differ')


if __name__ == '__main__':
    main()
