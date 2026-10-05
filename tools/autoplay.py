#!/usr/bin/env python3
"""Turn an input scenario into autoplay.bin for an AUTOPLAY=1 build.

usage: autoplay.py SCENARIO OUT.bin [--offset N]
       autoplay.py --log inputs.json OUT.bin     (a tools/mousebot.py run)

Scenario steps are (buttons, frames) as in tools/emu/scenario.py; a button
name may also be ('MOUSE', dx, dy, buttons).  --offset shifts the script by
N frames.  The default, -10, lines the script up with harness runs: the
game's VBlank counter starts 10 frames after power-on, so the harness's
frame n input belongs to VBlank n-10."""
import sys, os, struct
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'emu'))
from scenario import SCENARIOS

HELD = {'UP': 0, 'DOWN': 1, 'LEFT': 2, 'RIGHT': 3, 'B': 4, 'C': 5, 'A': 6, 'START': 7}
EXT = {'Z': 0, 'Y': 1, 'X': 2, 'MODE': 3}


def encode(steps, offset=-10):
    recs = []
    if offset > 0:
        recs.append((offset, 0, 0, 0, 0, 0))
    skip = -offset if offset < 0 else 0
    for btns, n in steps:
        if btns == 'RESTART':
            recs.append(('MARK',))
            continue
        if skip:
            k = min(skip, n); skip -= k; n -= k
            if not n:
                continue
        held = ext = dx = dy = mb = 0
        for b in btns:
            if isinstance(b, tuple):
                _, dx, dy, mb = b
            elif b in HELD:
                held |= 1 << HELD[b]
            else:
                ext |= 1 << EXT[b]
        while n > 0:
            k = min(n, 0xFFFF)
            recs.append((k, held, ext, dx & 0xFF, dy & 0xFF, mb))
            n -= k
    # merge equal neighbours
    out = []
    for r in recs:
        if r == ('MARK',):
            out.append((1, 0, 0, 0, 0, 0, 1))
            continue
        r = r + (0,)
        if out and len(out[-1]) == 7 and out[-1][6] == 0 and out[-1][1:] == r[1:] and out[-1][0] + r[0] <= 0xFFFF:
            out[-1] = (out[-1][0] + r[0],) + r[1:]
        else:
            out.append(r)
    return b''.join(struct.pack('>HBBBBBB', *r) for r in out)


if __name__ == '__main__':
    args = sys.argv[1:]
    off = -10
    if '--offset' in args:
        i = args.index('--offset'); off = int(args[i + 1]); del args[i:i + 2]
    if args[0] == '--log':
        # one step per VBlank: the game reads the pad after the frame's
        # VBlank, and runs with VBlank off while loading (frames without a
        # count), so key the script on the counter the bot recorded
        import json
        # the counter restarts with the game (missions begin with a restart):
        # one segment per restart, joined by RESTART marks
        log = json.load(open(args[1]))
        segs, byvb, prev = [], {}, -1
        for p, dx, dy, mb, vb in log:
            if vb < prev:
                segs.append(byvb); byvb = {}
            prev = vb
            byvb[vb] = ((tuple(p) + ((('MOUSE', dx, dy, mb),) if (dx or dy or mb) else ())), 1)
        segs.append(byvb)
        steps = []
        for k, sg in enumerate(segs):
            if k:
                steps.append(('RESTART', 0))
            steps += [sg.get(v, ((), 1)) for v in range(max(sg) + 1)]
        off = 0
        args = args[1:]
    else:
        steps = SCENARIOS[args[0]]()
    data = encode(steps, off)
    open(args[1], 'wb').write(data)
    print('%s: %d records' % (args[1], len(data) // 8))
