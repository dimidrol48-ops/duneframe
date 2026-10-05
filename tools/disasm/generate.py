#!/usr/bin/env python3
"""Regenerate the assembly sources from the base ROM + traces.

usage: generate.py baserom.gen traces.npz outdir
then:  variant.py baserom.gen traces.npz variants/wide.gen WIDE outdir
       (folds the 480x464 build in as .if WIDE blocks)

This is the one-shot "disassembly" step.  Its output (src/) is the source of
truth afterwards; config.py records the manual knowledge used here.
"""
import os, sys, pickle, time
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyze import Analysis
from emit import Emitter
import config
if os.environ.get('DIS_NOT_PTRS'):
    config.NOT_PTRS = list(config.NOT_PTRS) + [int(x, 16) for x in open(os.environ['DIS_NOT_PTRS']).read().split()]


def choose_splits(A, E):
    """File boundaries: header, code split into probable compilation units
    (GCC emitted each unit's read-only data right after its functions, so a
    data island followed by a new function marks a unit boundary), then the
    data regions."""
    splits = {0: 'header', 0x200: 'code_000200'}
    a = 0x200
    code_end = 0x1FA82
    while a < code_end:
        if A.owner[a] < 0:
            s = a
            while a < code_end and A.owner[a] < 0:
                a += 1
            prev = A.code.get(int(A.owner[s - 2])) if s >= 2 and A.owner[s - 2] >= 0 else None
            if a - s >= 16 and a in A.funcs and prev is not None and prev.flow in ('jump', 'ret', 'stop') \
                    and s not in A.jtables:
                splits[a] = 'code_%06X' % a
        else:
            a += 1
    for start, name in getattr(config, 'FILE_SPLITS', {}).items():
        splits[start] = name
    # never split inside an asset blob: move the boundary to the blob's end
    mp = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'assets', 'manifest.json')
    if os.path.exists(mp):
        import json
        for m in json.load(open(mp)):
            for st in [x for x in splits if m['start'] < x < m['end']]:
                name = splits.pop(st)
                if m['end'] not in splits:
                    splits[m['end']] = name.split('_')[0] + '_%06X' % m['end']
    return sorted(splits.items())


def main():
    rom = open(sys.argv[1], 'rb').read()
    tr = np.load(sys.argv[2])
    out = sys.argv[3]
    t = time.time()
    A = Analysis(rom, tr['ex'], tr['rd'], config, tr['who'] if 'who' in tr else None, tr['rc'] if 'rc' in tr else None, tr['rr'] if 'rr' in tr else None)
    A.discover()
    for _ in range(3):
        A.speculative_pointers(); A.table_pass(False)
        A.fill_gaps(); A.table_pass(False)
    A.find_data_pointers()
    A.pcrel_ptr_tables()
    print('reader classes:', A.reader_stats)
    print('analysis: %d insns, %d dptrs (%.1fs)' % (len(A.code), len(A.dptr), time.time() - t))
    for n in A.notes[:50]:
        print('  note:', n)
    E = Emitter(A, getattr(config, 'NAMES', {}), config)
    bad = E.validate()
    print('validate: %d instructions need raw encoding' % len(bad))
    E.check_cfuncs()
    splits = choose_splits(A, E)
    files = E.emit_all(out, splits)
    open(os.path.join(out, 'files.txt'), 'w').write('\n'.join(files) + '\n')
    A.cfg = None
    os.makedirs(os.path.join(out, '..', 'build'), exist_ok=True)
    pickle.dump((A, E.labels), open(os.path.join(out, '..', 'build', 'analysis.pkl'), 'wb'))
    print('emitted %d files, %d labels' % (len(files), len(E.labels)))


if __name__ == '__main__':
    main()
