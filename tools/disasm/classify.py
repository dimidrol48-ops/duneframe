#!/usr/bin/env python3
"""Sort functions into compiler-generated C (candidates for decompilation)
and hand-written assembly.

Compiled code of this game (16-bit int compiler): prologue saves d3-d7/a2-a6
with movem.l or link a6, arguments are read from the stack ((4+n,sp) or
(8+n,a6)), calls push arguments and the caller pops them, results in d0/a0.
Hand-written code takes arguments in registers, uses movep/exg/usp/SR,
self-modifying tricks, bsr.s helpers, jmp (pc,dN) tables, etc.

usage: classify.py [--list c|asm]"""
import sys, os, pickle, bisect
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from names import NAMES

ASM_ONLY = ('movep', 'exg', 'rte', 'rtr', 'trap', 'stop', 'reset', 'tas', 'abcd', 'sbcd', 'nbcd',
            'addx', 'subx', 'negx', 'roxl', 'roxr', 'chk')
SCRATCH = {'d0', 'd1', 'd2', 'a0', 'a1'}


def load():
    A, labels = pickle.load(open(os.path.join(HERE, '..', '..', 'build', 'analysis.pkl'), 'rb'))
    return A, labels


def body(A, a, funcs):
    i = bisect.bisect_right(funcs, a)
    end = funcs[i] if i < len(funcs) else a + 0x10000
    out, b = [], a
    while b < end and b in A.code:
        out.append(A.code[b])
        b += A.code[b].length
    return out


def reg_of(o):
    return o.reg if o.kind in ('dn', 'an') else None


def base_reg(o):
    return o.reg if o.kind in ('ind', 'postinc', 'predec', 'disp', 'index') else None


def classify(A, a, funcs):
    ins = body(A, a, funcs)
    if not ins:
        return 'empty', []
    why = []
    m0 = ins[0].mnem
    prologue = m0.startswith('movem.l') and ins[0].ops[1].kind == 'predec' or m0.startswith('link')
    stack_args = any(o.kind == 'disp' and o.reg in ('a6', 'sp') and o.disp > 0
                     for i in ins for o in i.ops)
    # registers read before written at entry (register arguments)
    written = set()
    reg_args = set()
    for i in ins[:12]:
        srcs = i.ops[:-1] if len(i.ops) > 1 else i.ops
        for o in srcs:
            r = reg_of(o)
            if r and r in SCRATCH and r not in written:
                reg_args.add(r)
            r = base_reg(o)
            if r in SCRATCH and r not in written:
                reg_args.add(r)
        if len(i.ops) > 1:
            d = i.ops[-1]
            r = base_reg(d)
            if r in SCRATCH and r not in written:
                reg_args.add(r)
            r = reg_of(d)
            if r:
                written.add(r)
        if i.mnem.startswith(('jsr', 'bsr', 'rts', 'jmp', 'bra')):
            break
    asm_ops = sorted({i.mnem.split('.')[0] for i in ins if i.mnem.split('.')[0] in ASM_ONLY})
    sr = any(o.kind in ('sr', 'ccr', 'usp') for i in ins for o in i.ops)
    pcjump = any(i.mnem.startswith('jmp') and i.ops and i.ops[0].kind == 'pcindex' for i in ins)
    if asm_ops:
        why.append('uses ' + ','.join(asm_ops))
    if sr:
        why.append('touches SR/CCR/USP')
    if reg_args:
        why.append('register args ' + ','.join(sorted(reg_args)))
    if pcjump:
        why.append('jmp (pc,dn) table')
    if not prologue and not stack_args and not why:
        why.append('no C prologue / stack args')
    kind = 'c' if not why or (prologue and stack_args and not asm_ops and not sr and not reg_args) else 'asm'
    return kind, why, len(ins)


def main():
    A, _ = load()
    funcs = sorted(a for a in A.funcs if a in A.code)
    res = {}
    for a in funcs:
        r = classify(A, a, funcs)
        if r[0] == 'empty':
            continue
        res[a] = r
    c = [a for a in res if res[a][0] == 'c']
    s = [a for a in res if res[a][0] == 'asm']
    print('functions %d: compiled C %d (%d insns), hand asm %d (%d insns)' % (
        len(res), len(c), sum(res[a][2] for a in c), len(s), sum(res[a][2] for a in s)))
    if '--list' in sys.argv:
        want = sys.argv[sys.argv.index('--list') + 1]
        for a in (c if want == 'c' else s):
            print('%06X %-28s %4d %s' % (a, NAMES.get(a, 'sub_%06X' % a), res[a][2], '; '.join(res[a][1])))


if __name__ == '__main__':
    main()
