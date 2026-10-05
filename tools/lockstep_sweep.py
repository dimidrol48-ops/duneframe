#!/usr/bin/env python3
"""Equal-timing lockstep of ROM_A vs ROM_B over every scenario.
usage: lockstep_sweep.py ROM_A ROM_B ELF_B [scenario...] [-- extra lockstep.py options]"""
import sys, os, subprocess
from multiprocessing import Pool
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, 'emu'))
from scenario import SCENARIOS


def one(a):
    ra, rb, elf, sc, extra = a
    r = subprocess.run([sys.executable, os.path.join(HERE, 'lockstep.py'), ra, rb, sc, '--every', '10',
                        '--equal-timing', elf] + extra, capture_output=True, text=True)
    out = r.stdout.strip().split('\n')
    return sc, out[1] if len(out) > 1 else (r.stdout + r.stderr)[-300:], r.stdout


if __name__ == '__main__':
    argv = sys.argv[1:]
    extra = argv[argv.index('--') + 1:] if '--' in argv else []
    argv = argv[:argv.index('--')] if '--' in argv else argv
    ra, rb, elf = argv[:3]
    names = argv[3:] or list(SCENARIOS)
    bad = 0
    with Pool(min(4, os.cpu_count())) as p:
        for sc, line, full in p.imap_unordered(one, [(ra, rb, elf, n, extra) for n in names]):
            print('%-20s %s' % (sc, line), flush=True)
            if 'no lasting difference' not in line:
                bad += 1
                print(full)
    print('%d/%d scenarios differ' % (bad, len(names)))
    sys.exit(1 if bad else 0)
