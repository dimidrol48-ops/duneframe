#!/usr/bin/env python3
"""Function summary report used while naming things.
usage: report.py [start end]  -> build/funcs.txt"""
import sys, os, pickle, re, bisect
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import config
from emit import Emitter

A, labels = pickle.load(open(os.path.join(ROOT, 'build', 'analysis.pkl'), 'rb'))
E = Emitter(A, getattr(config, 'NAMES', {}), config)
rom = A.rom
funcs = sorted(f for f in A.funcs if f in A.code)
lo = int(sys.argv[1], 16) if len(sys.argv) > 1 else 0
hi = int(sys.argv[2], 16) if len(sys.argv) > 2 else 1 << 30
callers = {}
for a, i in A.code.items():
    if i.flow == 'call':
        for t in i.targets:
            callers.setdefault(t, set()).add(a)


def fstart(a):
    k = bisect.bisect_right(funcs, a) - 1
    return funcs[k] if k >= 0 else None


def cstr(a):
    if a >= len(rom): return None
    j = a
    while j < len(rom) and 32 <= rom[j] < 127 and j - a < 60: j += 1
    if j - a >= 3 and (j >= len(rom) or rom[j] == 0):
        return rom[a:j].decode()
    return None


out = []
for k, f in enumerate(funcs):
    if not (lo <= f < hi):
        continue
    end = funcs[k + 1] if k + 1 < len(funcs) else f + 2
    insns = []
    a = f
    while a < end and a in A.code:
        insns.append(A.code[a]); a += A.code[a].length
    calls, strs, ram, io, data = [], [], set(), set(), set()
    for i in insns:
        if i.flow == 'call' and i.targets:
            calls.append(E.default_name(i.targets[0]))
        for o in i.ops:
            t = None
            if o.kind in ('absw', 'absl', 'pcdisp', 'pcindex'):
                t = o.target
            elif o.kind == 'imm' and o.size == 'l':
                t = o.value & 0xFFFFFF
            if t is None: continue
            if t >= 0xFF0000: ram.add(E.ram_names.get(t, 'ram_%04X' % (t & 0xFFFF)))
            elif t >= 0xA00000: io.add('%06X' % t)
            elif t < len(rom) and o.kind != 'imm':
                s = cstr(t)
                if s: strs.append(s)
                elif t not in A.code: data.add('%06X' % t)
    ncall = len(callers.get(f, ()))
    out.append('== %s %06X len %d  callers %d%s' % (E.default_name(f), f, a - f, ncall,
               ' (from %s)' % ','.join(sorted(set(E.default_name(fstart(c)) for c in callers.get(f, ())))[:6]) if ncall else ''))
    if calls: out.append('   calls: ' + ', '.join(sorted(set(calls))[:14]))
    if strs: out.append('   strings: ' + ' | '.join(strs[:6]))
    if ram: out.append('   ram: ' + ' '.join(sorted(ram)[:16]))
    if io: out.append('   io: ' + ' '.join(sorted(io)))
    if data: out.append('   data: ' + ' '.join(sorted(data)[:8]))
open(os.path.join(ROOT, 'build', 'funcs.txt'), 'w').write('\n'.join(out) + '\n')
print(len(funcs), 'functions;', len(out), 'lines')
