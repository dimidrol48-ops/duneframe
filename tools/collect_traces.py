#!/usr/bin/env python3
"""Collect execution / data-read traces from the base ROM by running the
input scenarios (plus extra random play) and OR-merging the trace buffers.
usage: collect_traces.py baserom.gen out.npz [extra_monkey_frames]"""
import sys, os, numpy as np
from multiprocessing import Pool
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'emu'))
from harness import Emu
import scenario

def job(args):
    rom, name, seed, frames = args
    e = Emu(rom)
    if name == 'monkey':
        scen = scenario.boot_to_mission(seed % 5) + scenario.monkey(frames, seed)
    else:
        scen = scenario.SCENARIOS[name]()
    for btns, n in scen:
        e.set_buttons(*btns); e.run(n)
    ex, rd, who, rx = e.trace()
    r = (ex.copy(), rd.copy(), who.copy(), e.rclass().copy(), e.rclass_ram().copy())
    e.close()
    return r

if __name__ == '__main__':
    rom, out = sys.argv[1], sys.argv[2]
    extra = int(sys.argv[3]) if len(sys.argv) > 3 else 60000
    jobs = [(rom, n, 0, 0) for n in scenario.SCENARIOS] + [(rom, 'monkey', s, extra) for s in range(10, 18)]
    ex = np.zeros(0x400000, np.uint8); rd = np.zeros(0x400000, np.uint8); who = np.zeros(0x200000, np.uint32); rc = np.zeros(0x400000, np.uint8); rr = np.zeros(0x400000, np.uint8)
    with Pool(4) as p:
        for e_, r_, w_, c_, cr_ in p.imap_unordered(job, jobs):
            ex |= e_; rd |= r_; rc |= c_; rr |= cr_
            who = np.where(who == 0, w_, who)
    np.savez_compressed(out, ex=ex, rd=rd, who=who, rc=rc, rr=rr)
    print('exec', int(ex.sum()), 'read bytes', int((rd != 0).sum()))
