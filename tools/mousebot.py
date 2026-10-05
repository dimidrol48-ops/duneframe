#!/usr/bin/env python3
"""A mouse-and-pad bot for the MODS build: plays a mission the way a person
with a Sega Mouse would (drag boxes around own units, group orders, double /
triple taps, edge scrolling, right clicks, pad presses) and records what it
did, so a run can be replayed (tools/autoplay.py --log) and compared.

usage: mousebot.py ROM OUTDIR [--start SCENARIO] [--frames N] [--seed S]
                   [--oc PERCENT] [--shots EVERY]

Writes OUTDIR/inputs.json (one entry per frame: [pad buttons, dx, dy, mouse
buttons, the game's VBlank counter after the frame]), OUTDIR/shot_<frame>.png and OUTDIR/log.txt (actions, VDP state
changes, anomalies)."""
import sys, os, json, random
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, 'emu'))
from harness import Emu
from scenario import SCENARIOS
import numpy as np

UNITS, USIZE, NUNITS = 0xFF0000, 0x8C, 128
CURSOR = 0xFFBF12
SCROLL_X, SCROLL_Y = 0xFFE3BE, 0xFFE3C0
HOUSE = 0xFFC274


def w16(r, a):
    a &= 0xFFFF
    return int.from_bytes(r[a:a + 2], 'big')


def s16(v):
    return v - 0x10000 if v & 0x8000 else v


class Bot:
    def __init__(self, emu, rng, log):
        self.e, self.rng, self.log = emu, rng, log
        self.inputs = []
        self.frame = 0

    # ---- input with recording
    def step(self, pad=(), dx=0, dy=0, mb=0):
        self.e.set_buttons(*pad)
        self.e.mouse(dx, dy, mb)
        self.e.run(1)
        r = self.e.ram()
        # the game's VBlank counter: AUTOPLAY scripts are keyed on it
        self.inputs.append([list(pad), dx, dy, mb, w16(r, 0xFFE006)])
        self.frame += 1

    def idle(self, n, mb=0):
        for _ in range(n):
            self.step(mb=mb)

    # ---- game state
    def state(self):
        r = self.e.ram()
        cur = (s16(w16(r, CURSOR)), s16(w16(r, CURSOR + 2)),
               s16(w16(r, CURSOR + 8)), s16(w16(r, CURSOR + 12)), s16(w16(r, CURSOR + 10)), s16(w16(r, CURSOR + 14)))
        # cur = (x, y, xmin, xmax, ymin, ymax)
        sx, sy = s16(w16(r, SCROLL_X)), s16(w16(r, SCROLL_Y))
        house = w16(r, HOUSE)
        units = []
        for i in range(NUNITS):
            b = (UNITS + i * USIZE) & 0xFFFF
            if not r[b + 5] & 2 or r[b + 8] != house:
                continue
            t = r[b + 2]
            if not 2 <= t <= 17:
                continue
            px, py = w16(r, UNITS + i * USIZE + 0xC) >> 3, w16(r, UNITS + i * USIZE + 0xA) >> 3
            units.append((px - sx, py - sy, t, px, py))   # screen position, type, world position
        return cur, units

    def onscreen(self, cur, units):
        x0, x1, y0, y1 = cur[2], cur[3], cur[4], cur[5]
        return [u for u in units if x0 <= u[0] <= x1 and y0 <= u[1] <= y1]

    # ---- mouse moves (the cursor position is the centre of its bracket)
    def scroll(self):
        r = self.e.ram()
        return s16(w16(r, SCROLL_X)), s16(w16(r, SCROLL_Y))

    def move_to(self, x, y, mb=0, speed=None, world=False):
        """Move the cursor to screen (x, y), or to world (x, y): the view
        scrolls when the cursor nears an edge, so aim again every frame."""
        speed = speed or self.rng.choice([4, 8, 12])
        for _ in range(160):
            cur, _ = self.state()
            tx, ty = x, y
            if world:
                sx, sy = self.scroll()
                tx, ty = x - sx, y - sy
            dx, dy = tx - cur[0], ty - cur[1]
            if abs(dx) <= 1 and abs(dy) <= 1:
                return
            self.step(dx=max(-speed, min(speed, dx)), dy=max(-speed, min(speed, dy)), mb=mb)

    def click(self, x, y, button=1, hold=3, after=6):
        self.move_to(x, y)
        self.idle(hold, mb=button)
        self.idle(after)

    # ---- actions
    def a_box(self):
        cur, units = self.state()
        vis = self.onscreen(cur, units)
        if not vis:
            return self.a_scroll()
        a = self.rng.choice(vis)
        near = [u for u in vis if abs(u[0] - a[0]) < 90 and abs(u[1] - a[1]) < 70]
        x0 = min(u[3] for u in near) - 14; x1 = max(u[3] for u in near) + 14
        y0 = min(u[4] for u in near) - 14; y1 = max(u[4] for u in near) + 14
        self.log('box %d units (%d,%d)-(%d,%d) world' % (len(near), x0, y0, x1, y1))
        self.move_to(x0, y0, world=True)
        self.idle(2, mb=1)
        self.move_to(x1, y1, mb=1, speed=6, world=True)
        self.idle(2, mb=1)
        self.idle(8)
        if self.rng.random() < 0.8:
            self.a_order()

    def a_order(self):
        cur, _ = self.state()
        if cur[2] > cur[3] or cur[4] > cur[5]:
            return self.idle(30)
        x = self.rng.randint(cur[2], cur[3])
        y = self.rng.randint(cur[4], cur[5])
        self.log('order at (%d,%d)' % (x, y))
        self.click(x, y, after=self.rng.choice([10, 30, 90]))

    def a_tap(self, n):
        cur, units = self.state()
        vis = self.onscreen(cur, units)
        if not vis:
            return self.a_scroll()
        u = self.rng.choice(vis)
        self.log('%d-tap on unit type %d at (%d,%d)' % (n, u[2], u[0], u[1]))
        self.move_to(u[3], u[4], world=True)
        for _ in range(n):
            self.idle(3, mb=1); self.idle(4)
        self.idle(10)
        if self.rng.random() < 0.7:
            self.a_order()

    def a_scroll(self):
        cur, _ = self.state()
        edge = self.rng.choice(['l', 'r', 'u', 'd'])
        x = {'l': cur[2], 'r': cur[3]}.get(edge, (cur[2] + cur[3]) // 2)
        y = {'u': cur[4], 'd': cur[5]}.get(edge, (cur[4] + cur[5]) // 2)
        self.log('scroll %s' % edge)
        self.move_to(x, y)
        # push against the edge
        d = {'l': (-6, 0), 'r': (6, 0), 'u': (0, -6), 'd': (0, 6)}[edge]
        for _ in range(self.rng.choice([30, 60, 120])):
            self.step(dx=d[0], dy=d[1])

    def a_home(self):
        """scroll towards the nearest own unit when none is on screen"""
        cur, units = self.state()
        if not units or self.onscreen(cur, units):
            return self.a_box()
        cx, cy = (cur[2] + cur[3]) // 2, (cur[4] + cur[5]) // 2
        u = min(units, key=lambda u: abs(u[0] - cx) + abs(u[1] - cy))
        dx, dy = u[0] - cx, u[1] - cy
        edge = ('r' if dx > 0 else 'l') if abs(dx) > abs(dy) else ('d' if dy > 0 else 'u')
        x = {'l': cur[2], 'r': cur[3]}.get(edge, cx)
        y = {'u': cur[4], 'd': cur[5]}.get(edge, cy)
        self.log('home %s' % edge)
        self.move_to(x, y)
        d = {'l': (-6, 0), 'r': (6, 0), 'u': (0, -6), 'd': (0, 6)}[edge]
        for _ in range(min(240, max(abs(dx), abs(dy)) // 2 + 10)):
            self.step(dx=d[0], dy=d[1])

    def a_right(self):
        self.log('right click')
        self.idle(3, mb=2); self.idle(8)

    def a_pad(self):
        b = self.rng.choice(['A', 'B', 'C', 'C', 'X', 'Z', 'UP', 'DOWN', 'LEFT', 'RIGHT'])
        self.log('pad %s' % b)
        for _ in range(4):
            self.step(pad=(b,))
        self.idle(self.rng.choice([4, 20, 60]))

    def a_wander(self):
        cur, _ = self.state()
        if cur[2] > cur[3] or cur[4] > cur[5]:
            return self.idle(30)
        x = self.rng.randint(cur[2], cur[3] + 32)
        y = self.rng.randint(cur[4], cur[5] + 32)
        self.move_to(x, y)

    def act(self):
        cur, units = self.state()
        if units and not self.onscreen(cur, units) and self.rng.random() < 0.8:
            return self.a_home()
        acts = [(self.a_box, 6), (self.a_order, 3), (lambda: self.a_tap(2), 2), (lambda: self.a_tap(3), 2),
                (lambda: self.a_tap(1), 2), (self.a_scroll, 3), (self.a_right, 1), (self.a_pad, 2),
                (self.a_wander, 2), (lambda: self.idle(self.rng.choice([30, 120, 300])), 2)]
        f = self.rng.choices([a for a, _ in acts], [w for _, w in acts])[0]
        f()


def crashed(emu):
    a = np.asarray(emu.rgb()).reshape(-1, 3)
    return ((a[:, 2] > 120) & (a[:, 0] < 30) & (a[:, 1] < 30)).mean() > 0.5


def main():
    args = sys.argv[1:]
    def opt(k, d):
        if k in args:
            i = args.index(k); v = args[i + 1]; del args[i:i + 2]; return v
        return d
    start = opt('--start', 'boot_mission1')
    frames = int(opt('--frames', '18000'))
    seed = int(opt('--seed', '1'))
    oc = opt('--oc', '100')
    every = int(opt('--shots', '1800'))
    rom, out = args[0], args[1]
    os.makedirs(out, exist_ok=True)
    logf = open(os.path.join(out, 'log.txt'), 'w')
    e = Emu(rom, options={'genesis_plus_gx_overclock': oc}, mouse=True)
    bot = Bot(e, random.Random(seed), lambda m: logf.write('%6d %s\n' % (bot.frame, m)))
    # boot into the mission with the pad
    from scenario import boot_to_mission, enter_password
    if start.startswith('pw:'):
        steps = enter_password(start[3:].upper())
    elif start in SCENARIOS:
        steps = SCENARIOS[start]()
    else:
        steps = boot_to_mission()
    for btns, n in steps:
        for _ in range(n):
            bot.step(pad=btns)
    bot.log('--- bot starts')
    vdp_prev = None
    next_shot = bot.frame
    end = bot.frame + frames
    while bot.frame < end:
        bot.act()
        if bot.frame >= next_shot:
            e.screenshot(os.path.join(out, 'shot_%06d.png' % bot.frame))
            next_shot += every
        regs = e.vdp()[3]
        sig = (regs[2], regs[3], regs[4], regs[5], regs[0xD], regs[0x10])
        if sig != vdp_prev:
            bot.log('VDP planeA=%04X win=%04X planeB=%04X sat=%04X hscroll=%04X size=%02X'
                    % (sig[0] << 10, sig[1] << 10, sig[2] << 13, sig[3] << 9, sig[4] << 10, sig[5]))
            vdp_prev = sig
        if crashed(e):
            bot.log('CRASH')
            e.screenshot(os.path.join(out, 'crash.png'))
            break
    e.screenshot(os.path.join(out, 'shot_%06d.png' % bot.frame))
    json.dump(bot.inputs, open(os.path.join(out, 'inputs.json'), 'w'))
    logf.close()
    print('%s: %d frames' % (out, bot.frame))


if __name__ == '__main__':
    main()
