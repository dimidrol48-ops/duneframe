#!/usr/bin/env python3
"""Build a pool of emulator save states spread over the scenarios
(build/states/pool/*.st).  snaptest.py replays short windows from them to
catch real calls of a function.
usage: states.py [every_frames]"""
import sys, os
from multiprocessing import Pool
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, 'tools', 'emu'))
from harness import Emu
from scenario import SCENARIOS

OUT = os.path.join(ROOT, 'build', 'states', 'pool')
PICK = ['boot', 'menus', 'mission1', 'ordos', 'long', 'pw_late', 'pw_dunerunner', 'pw_sonicblast',
        'pw_totalchaos', 'pw_kingmentat', 'pw_deathruler', 'pw_fremenrush']


def one(args):
    name, every = args
    e = Emu(os.path.join(ROOT, 'baserom.gen'))
    f = 0
    n = 0
    for btns, k in SCENARIOS[name]():
        e.set_buttons(*btns)
        for _ in range(k):
            e.run(1)
            f += 1
            if f % every == 0:
                open(os.path.join(OUT, '%s_%06d.st' % (name, f)), 'wb').write(e.save_state())
                n += 1
    e.close()
    return name, n


if __name__ == '__main__':
    every = int(sys.argv[1]) if len(sys.argv) > 1 else 1500
    os.makedirs(OUT, exist_ok=True)
    with Pool(4) as p:
        for name, n in p.imap_unordered(one, [(s, every) for s in PICK if s in SCENARIOS]):
            print(name, n)
