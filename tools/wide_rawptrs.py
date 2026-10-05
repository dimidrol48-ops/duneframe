#!/usr/bin/env python3
"""List raw .byte data inside .if WIDE blocks that contains 32-bit values
pointing into the WIDE ROM at a label (such pointers are not relocated when
the code moves, e.g. in the NONMATCHING/MODS builds)."""
import re, glob, subprocess, sys, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
elf = os.path.join(ROOT, 'build/wide/dune2.elf')
syms = {}
for l in subprocess.run(['m68k-linux-gnu-nm', elf], capture_output=True, text=True).stdout.split('\n'):
    p = l.split()
    if len(p) == 3 and p[1] in 'tT':
        syms.setdefault(int(p[0], 16), p[2])
rom_end = os.path.getsize(os.path.join(ROOT, 'variants/wide.gen'))
hits = 0
for f in sorted(glob.glob(os.path.join(ROOT, 'src/*.s'))):
    L = open(f).read().split('\n')
    stack = []
    block = []      # (line no, bytes) of the current WIDE-side .byte run
    def flush():
        global hits
        data = b''.join(b for _, b in block)
        offs = []
        n = 0
        for _, b in block:
            offs.append(n); n += len(b)
        for i in range(0, len(data) - 3):
            v = int.from_bytes(data[i:i+4], 'big')
            if 0x200 <= v < rom_end and v in syms and not (v < 0x10000 and data[i:i+2] == b'\0\0' and False):
                ln = block[max(k for k, o in enumerate(offs) if o <= i)][0]
                print('%s:%d  +%d  0x%06X  %s' % (os.path.basename(f), ln, i, v, syms[v]))
                hits += 1
        block.clear()
    for no, line in enumerate(L, 1):
        s = line.split('|')[0].strip()
        if s.startswith('.if'):
            stack.append(['WIDE' in s and '== 0' not in s, False])
        elif s == '.else':
            flush(); stack[-1][1] = True
        elif s == '.endif':
            flush(); stack.pop()
        elif s.startswith('.byte') and stack and stack[-1][0] and not stack[-1][1]:
            vals = [int(x, 0) for x in s[5:].split(',')]
            block.append((no, bytes(vals)))
        elif block:
            flush()
print(hits, 'candidate pointers')
