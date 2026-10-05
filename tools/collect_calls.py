#!/usr/bin/env python3
"""Run all scenarios watching calls to given PCs; save unique register sets.
usage: collect_calls.py out.json pc1,pc2,..."""
import sys, os, json
from multiprocessing import Pool
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'emu'))
from harness import Emu
import scenario

PCS = [int(x, 0) for x in sys.argv[2].split(',')]

def job(name):
    e = Emu('baserom.gen')
    e.callwatch(PCS)
    seen = set()
    for btns, n in scenario.SCENARIOS[name]():
        e.set_buttons(*btns)
        for _ in range(n):
            e.run(1)
        log = e.callwatch_log()
        for row in log:
            seen.add(tuple(int(x) for x in row))
        e.callwatch(PCS)
    e.close()
    return seen

if __name__ == '__main__':
    allc = set()
    with Pool(4) as p:
        for s in p.imap_unordered(job, list(scenario.SCENARIOS)):
            allc |= s
    json.dump(sorted(allc), open(sys.argv[1], 'w'))
    print(len(allc), 'unique calls')
