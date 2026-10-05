#!/usr/bin/env python3
"""Run every scenario on a ROM and report ones that hit the exception
screen (the rebuild's crash handler draws a dark blue register dump).
usage: crashsweep.py ROM [scenario ...]"""
import sys, os
import numpy as np
from multiprocessing import Pool
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'emu'))
from harness import Emu
from scenario import SCENARIOS


def crashed(emu):
    a = np.asarray(emu.rgb()).reshape(-1, 3)
    return ((a[:, 2] > 120) & (a[:, 0] < 30) & (a[:, 1] < 30)).mean() > 0.5


def one(args):
    rom, name = args
    e = Emu(rom)
    f = 0
    for btns, n in SCENARIOS[name]():
        e.set_buttons(*btns)
        while n > 0:
            k = min(60, n)
            e.run(k); f += k; n -= k
            if crashed(e):
                e.close()
                return name, 'CRASH near frame %d' % f
    e.close()
    return name, 'ok (%d frames)' % f


if __name__ == '__main__':
    rom = sys.argv[1]
    names = sys.argv[2:] or list(SCENARIOS)
    bad = 0
    with Pool(min(8, os.cpu_count())) as p:
        for name, res in p.imap(one, [(rom, n) for n in names]):
            print('%-24s %s' % (name, res))
            bad += 'CRASH' in res
    sys.exit(1 if bad else 0)
