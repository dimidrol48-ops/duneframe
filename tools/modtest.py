"""Helpers for testing the MODS features in the emulator."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'emu'))
from harness import Emu

G_ADDR = None

def sym(name, elf='build/mod/dune2.elf'):
    import subprocess
    for l in subprocess.run(['m68k-linux-gnu-nm', elf], capture_output=True, text=True).stdout.split('\n'):
        p = l.split()
        if len(p) == 3 and p[2] == name:
            return int(p[0], 16)
    raise KeyError(name)

def load(rom='build/mod/dune2.gen', state='build/states/mod_mission1.st'):
    e = Emu(rom, mouse=True)
    e.run(1)
    e.load_state(open(state, 'rb').read())
    return e

def w16(r, a): return int.from_bytes(r[a & 0xFFFF:(a & 0xFFFF) + 2], 'big')
def w32(r, a): return int.from_bytes(r[a & 0xFFFF:(a & 0xFFFF) + 4], 'big')

def group(e):
    g = sym('G')
    r = e.ram()
    n = r[g & 0xFFFF]
    units = [w32(r, g + 4 + 4 * i) for i in range(n)]
    return n, units, w32(r, 0xFFC25C)

def set_cursor(e, x, y):
    e.poke(0xFFBF12, x.to_bytes(2, 'big')); e.poke(0xFFBF14, y.to_bytes(2, 'big'))
    e.run(2)

def drag(e, x0, y0, x1, y1, steps=20):
    set_cursor(e, x0, y0)
    e.mouse(0, 0, 1); e.run(2)
    dx, dy = (x1 - x0) / steps, (y1 - y0) / steps
    ax = ay = 0.0
    for i in range(steps):
        ax += dx; ay += dy
        mx, my = int(round(ax)), int(round(ay)); ax -= mx; ay -= my
        e.mouse(mx, my, 1); e.run(1)
    e.mouse(0, 0, 0); e.run(3)

def click(e, x, y, frames=30):
    set_cursor(e, x, y)
    e.mouse(0, 0, 1); e.run(2); e.mouse(0, 0, 0); e.run(frames)
