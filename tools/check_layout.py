#!/usr/bin/env python3
"""Check that a modified build keeps the original ROM layout where it must:
every label below LIMIT (default: the first intentionally moved string at
0x0106C6) must sit at the same address as in the matching build.  Low ROM
is layout-sensitive (the game reads garbage through null / short pointers).
usage: check_layout.py build/dune2.elf build/mod/dune2.elf [limit]"""
import sys, subprocess

def syms(elf):
    out = {}
    for l in subprocess.run(['m68k-linux-gnu-nm', elf], capture_output=True, text=True).stdout.split('\n'):
        p = l.split()
        if len(p) == 3 and p[1] in 'tT':
            out[p[2]] = int(p[0], 16)
    return out

a, b = syms(sys.argv[1]), syms(sys.argv[2])
limit = int(sys.argv[3], 16) if len(sys.argv) > 3 else 0x0106C6
# labels inside routines replaced by C (NONMATCHING) are simply absent
bad = [(n, a[n], b[n]) for n in a if a[n] < limit and n in b and b[n] != a[n] and not n.startswith('.L')]
gone = [n for n in a if a[n] < limit and n not in b]
for n, x, y in sorted(bad, key=lambda t: t[1])[:20]:
    print('moved: %-24s %06X -> %06X' % (n, x, y))
print('%d labels below %06X: %d moved, %d inside C-replaced routines' % (
    sum(1 for n in a if a[n] < limit), limit, len(bad), len(gone)))
sys.exit(1 if bad else 0)
