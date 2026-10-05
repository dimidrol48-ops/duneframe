#!/usr/bin/env python3
"""Which function contains each address?  usage: where.py ADDR ..."""
import sys, os, pickle, bisect
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from names import NAMES

def load():
    A, _labels = pickle.load(open(os.path.join(HERE, "..", "..", "build", "analysis.pkl"), "rb"))
    return A

def func_of(A, pc):
    f = sorted(A.funcs)
    i = bisect.bisect_right(f, pc) - 1
    a = f[i]
    return a, NAMES.get(a, 'sub_%06X' % a)

if __name__ == '__main__':
    A = load()
    for s in sys.argv[1:]:
        pc = int(s, 16)
        a, n = func_of(A, pc)
        print('%06X  %s+0x%X' % (pc, n, pc - a))
