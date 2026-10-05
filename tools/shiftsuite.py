#!/usr/bin/env python3
"""Run the relocation (shift) test over all scenarios in parallel.
usage: shiftsuite.py [--at A,B --pad X,Y] [scenario-prefix]
Builds one shifted ROM, then compares base vs shifted for every scenario."""
import sys, os, subprocess
from multiprocessing import Pool
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, 'emu')); sys.path.insert(0, HERE)
import shifttest
from scenario import SCENARIOS

def one(name):
    first, n, audio_ok = shifttest.compare(os.path.join(ROOT, 'baserom.gen'), os.path.join(ROOT, 'build', 'shift', 'rom.gen'), name)
    return name, first, n, audio_ok

if __name__ == '__main__':
    ats, pads, prefix = '0x10000,0x24000', '64,131008', ''
    args = sys.argv[1:]
    if '--at' in args: ats = args[args.index('--at') + 1]
    if '--pad' in args: pads = args[args.index('--pad') + 1]
    rest = [a for i, a in enumerate(args) if a not in ('--at', '--pad') and (i == 0 or args[i - 1] not in ('--at', '--pad'))]
    if rest: prefix = rest[0]
    at = [int(x, 0) for x in ats.split(',')]; pd = [int(x, 0) for x in pads.split(',')]
    shifttest.build_shifted(at, pd, os.path.join(ROOT, 'build', 'shift'), [True] * len(at))
    import json; json.dump(shifttest.INSERTED, open(os.path.join(ROOT, 'build', 'shift', 'inserted.json'), 'w'))
    names = [n for n in SCENARIOS if n.startswith(prefix)]
    fails = 0
    with Pool(4) as p:
        for name, first, n, audio_ok in p.imap_unordered(one, names):
            ok = first is None and audio_ok
            fails += not ok
            print('%-18s %s' % (name, 'PASS' if ok else 'FAIL at frame %s%s' % (None if first is None else first * 10, '' if audio_ok else ' (audio differs)')), flush=True)
    print('%d/%d passed' % (len(names) - fails, len(names)))
    sys.exit(1 if fails else 0)
