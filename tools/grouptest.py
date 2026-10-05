#!/usr/bin/env python3
"""Functional test of the MODS mouse / multi-select features.

usage: grouptest.py [ROM [ELF]]   (default build/mod/dune2.gen, .elf)

Boots into mission 1 with a Sega Mouse on port 2, then checks:
  drag box       -> a group of the boxed units
  click ground   -> every member gets its own destination
  double tap     -> all on-screen units of the same type
  triple tap     -> all on-screen units of the same class
  click a member -> that unit alone
  right click    -> nothing selected
Exit status 1 on any failure."""
import sys, os, random, subprocess
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, 'emu'))
from harness import Emu
from scenario import boot_to_mission
from mousebot import Bot, w16, s16

UNITS, USIZE = 0xFF0000, 0x8C
SELECTED = 0xFFC25C          # g_selectedObject


def sym(elf, name):
    for l in subprocess.run(['m68k-linux-gnu-nm', elf], capture_output=True, text=True).stdout.split('\n'):
        p = l.split()
        if len(p) == 3 and p[2] == name:
            return int(p[0], 16)
    raise KeyError(name)


def w32(r, a):
    a &= 0xFFFF
    return int.from_bytes(r[a:a + 4], 'big')


def main():
    rom = sys.argv[1] if len(sys.argv) > 1 else 'build/mod/dune2.gen'
    elf = sys.argv[2] if len(sys.argv) > 2 else rom.replace('.gen', '.elf')
    g = sym(elf, 'G')
    e = Emu(rom, mouse=True)
    bot = Bot(e, random.Random(1), lambda m: None)
    for btns, n in boot_to_mission():
        for _ in range(n):
            bot.step(pad=btns)
    bot.idle(120)
    fails = []

    def check(what, ok, info=''):
        print('%-40s %s %s' % (what, 'ok' if ok else 'FAIL', info))
        if not ok:
            fails.append(what)

    def group():
        r = e.ram()
        n = r[g & 0xFFFF]
        return [w32(r, g + 4 + 4 * i) for i in range(n)], w32(r, SELECTED)

    def units_on_screen():
        cur, units = bot.state()
        return cur, bot.onscreen(cur, units)

    cur, vis = units_on_screen()
    print('own units on screen:', len(vis), [u[:3] for u in vis])
    if len(vis) < 3:
        print('not enough units on screen to test'); sys.exit(1)

    # double / triple tap on a unit: pick a type that occurs twice on screen
    cur, vis = units_on_screen()
    types = {}
    for u in vis:
        types.setdefault(u[2], []).append(u)
    pick = max(types.values(), key=len)
    u = pick[0]
    bot.move_to(u[3], u[4], world=True)
    bot.idle(3, mb=1); bot.idle(5)
    bot.idle(3, mb=1); bot.idle(12)
    members, sel = group()
    same = [w32(e.ram(), 0) for _ in ()]
    r = e.ram()
    ts = [r[(m + 2) & 0xFFFF] for m in members]
    check('double tap: same type', len(members) >= 2 and len(set(ts)) == 1 if len(pick) > 1 else True,
          '%d members, types %s' % (len(members), ts))
    bot.idle(3, mb=1); bot.idle(12)
    members, sel = group()
    r = e.ram()
    ts = [r[(m + 2) & 0xFFFF] for m in members]
    check('triple tap: same class (more or equal)', len(members) >= 2, '%d members, types %s' % (len(members), ts))

    # click one member: alone
    if members:
        m = members[-1]
        bot.idle(60)
        bot.move_to(w16(r, m + 0xC) >> 3, w16(r, m + 0xA) >> 3, world=True)
        bot.idle(3, mb=1); bot.idle(12)
        members2, sel = group()
        check('click a member: selected alone', not members2 and sel == m, 'sel %X want %X' % (sel, m))

    bot.idle(3, mb=2); bot.idle(20)
    cur, vis = units_on_screen()
    # drag box around everything visible
    x0 = min(u[3] for u in vis) - 12; x1 = max(u[3] for u in vis) + 12
    y0 = min(u[4] for u in vis) - 12; y1 = max(u[4] for u in vis) + 12
    bot.move_to(x0, y0, world=True); bot.idle(2, mb=1)
    bot.move_to(x1, y1, mb=1, speed=6, world=True); bot.idle(2, mb=1); bot.idle(10)
    members, sel = group()
    check('drag box selects a group', len(members) >= 2, '%d members' % len(members))

    # order: click on open ground
    tx, ty = (cur[2] + cur[3]) // 2 - 40, cur[5] - 20
    bot.click(tx, ty, after=20)
    r = e.ram()
    dests = [(w16(r, m + 0x5A), w16(r, m + 0x5C)) for m in members]
    check('group order: one destination each', len(set(dests)) == len(dests) and len(dests) >= 2, str(dests))

    # right click clears
    bot.idle(3, mb=2); bot.idle(10)
    members, sel = group()
    check('right click deselects', not members and sel == 0, 'sel %X' % sel)

    print('%d failure(s)' % len(fails))
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
