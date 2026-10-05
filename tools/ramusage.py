#!/usr/bin/env python3
"""Which work-RAM bytes does the game ever change?  Runs scenarios, samples
RAM every few frames and ORs 'differs from the value at boot'.  Combined
with static references this finds free RAM for new code.
usage: ramusage.py ROM out.npy [scenario ...]"""
import sys, os
import numpy as np
from multiprocessing import Pool
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'emu'))
from harness import Emu
from scenario import SCENARIOS


def one(args):
    rom, name = args
    e = Emu(rom)
    e.run(1)
    base = np.frombuffer(e.ram(), np.uint8).copy()
    used = np.zeros(0x10000, bool)
    for btns, n in SCENARIOS[name]():
        e.set_buttons(*btns)
        while n > 0:
            k = min(n, 7)
            e.run(k); n -= k
            r = np.frombuffer(e.ram(), np.uint8)
            used |= r != base
    e.close()
    return used


if __name__ == '__main__':
    rom, out = sys.argv[1], sys.argv[2]
    names = sys.argv[3:] or list(SCENARIOS)
    used = np.zeros(0x10000, bool)
    with Pool(4) as p:
        for u in p.imap_unordered(one, [(rom, n) for n in names]):
            used |= u
    np.save(out, used)
    # print free runs >= 64 bytes
    a = 0
    while a < 0x10000:
        if not used[a]:
            s = a
            while a < 0x10000 and not used[a]:
                a += 1
            if a - s >= 64:
                print('free %04X-%04X (%d)' % (s, a, a - s))
        else:
            a += 1
