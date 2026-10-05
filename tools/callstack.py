#!/usr/bin/env python3
"""Rebuild call stacks from an emulator PC log using the disassembly.
calls_to(pcs, targets) -> list of (target, [caller return addresses ...])."""
import sys, os, pickle
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'disasm'))
from where import func_of

_A = None
def analysis():
    global _A
    if _A is None:
        _A, _ = pickle.load(open(os.path.join(HERE, '..', 'build', 'analysis.pkl'), 'rb'))
    return _A

def calls_to(pcs, targets):
    A = analysis()
    stack, out = [], []
    prev = None
    for pc in pcs:
        pc = int(pc)
        if prev is not None:
            ins = A.code.get(prev)
            if ins is not None:
                m = ins.mnem
                if m.startswith(('jsr', 'bsr')) and pc != prev + ins.length:
                    stack.append(prev)
                elif m.startswith('rts') and stack:
                    stack.pop()
        if pc in targets:
            out.append((pc, list(stack)))
        prev = pc
    return out

def fmt_stack(stack):
    A = analysis()
    return ' <- '.join('%s(%06X)' % (func_of(A, s)[1], s) for s in reversed(stack))
