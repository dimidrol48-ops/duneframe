#!/usr/bin/env python3
"""Screenshots of the screens touched by the MODS=1 build, for base and mod ROM.
usage: modshots.py [rom ...]  (default: baserom.gen build/mod/dune2.gen) -> build/shots/"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'emu'))
from harness import Emu
from scenario import boot_to_mission

def seq(emu, s):
    for btns, n in s:
        emu.set_buttons(*btns); emu.run(n)

def menu_shown(e):
    # the pause menu is drawn over a dimmed, mostly dark screen
    import numpy as np
    return np.asarray(e.rgb()).mean() < 50

def shots(rom, tag, out='build/shots'):
    os.makedirs(out, exist_ok=True)
    e = Emu(rom)
    title = [((), 700), (('START',), 4), ((), 120), (('START',), 4), ((), 120), (('START',), 4), ((), 120)]
    seq(e, title); e.screenshot('%s/%s_title.png' % (out, tag))
    seq(e, [(('DOWN',), 4), ((), 30), (('C',), 4), ((), 120)]); e.screenshot('%s/%s_options.png' % (out, tag))
    e.close()
    e = Emu(rom)
    seq(e, boot_to_mission()); e.screenshot('%s/%s_ingame.png' % (out, tag))
    # C builds run with different timing: retry until the pause menu shows up
    for _ in range(8):
        before = e.frame_hash()
        seq(e, [((), 30), (('START',), 8), ((), 60)])
        if menu_shown(e):
            break
    e.screenshot('%s/%s_pause.png' % (out, tag))
    e.close()

if __name__ == '__main__':
    roms = sys.argv[1:] or ['baserom.gen', 'build/mod/dune2.gen']
    for r in roms:
        shots(r, 'mod' if 'mod' in r else 'base')
