#!/usr/bin/env python3
"""Compare a ROM against the base ROM over input scenarios (frame hashes + audio).
usage: compare_rom.py rom [scenario-prefix]"""
import sys, os
from multiprocessing import Pool
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, 'emu'))
import shifttest
from scenario import SCENARIOS
ROM = os.path.abspath(sys.argv[1])
def one(name):
    return (name,) + shifttest.compare(os.path.join(ROOT, 'baserom.gen'), ROM, name)
if __name__ == '__main__':
    pre = sys.argv[2] if len(sys.argv) > 2 else ''
    names = [n for n in SCENARIOS if n.startswith(pre)]
    ok = 0
    with Pool(4) as p:
        for name, first, n, audio in p.imap_unordered(one, names):
            good = first is None and audio
            ok += good
            print('%-18s %s' % (name, 'identical' if good else 'differs at frame %s%s' % (None if first is None else first * 10, '' if audio else ', audio differs')), flush=True)
    print('%d/%d identical' % (ok, len(names)))
