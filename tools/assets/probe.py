#!/usr/bin/env python3
"""Probe how graphics are used at runtime (for asset extraction).

Runs all input scenarios, logging calls to the VDP DMA routine (sub_000A06),
the word-copy routine (loc_000F80) and the palette loader (sub_00124C).
For every tile block DMA'd from ROM to VRAM, the VDP state is inspected a few
frames later: nametable / sprite entries that reference those tiles tell which
palette line (and therefore which 16 colours) the graphics are shown with.

output: assets/probe.json (palette / DMA metadata, no ROM content)
"""
import sys, os, json
from collections import defaultdict, Counter
from multiprocessing import Pool
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, 'tools', 'emu'))
from harness import Emu
import scenario

PC_DMA, PC_COPY, PC_PAL = 0xA06, 0xF80, 0x124C
DELAY = 15


def cram_to_md(c):
    """GPGX internal 9-bit BBBGGGRRR -> Mega Drive colour word 0000BBB0GGG0RRR0."""
    c = int(c)
    return (((c >> 6) & 7) << 9) | (((c >> 3) & 7) << 5) | ((c & 7) << 1)


def tile_refs(vram, regs):
    """Yield (tile_index, palette_line) for all nametable and sprite entries."""
    def nt(addr, w, h):
        for i in range(w * h):
            e = (vram[addr + 2 * i] << 8) | vram[addr + 2 * i + 1]
            yield e & 0x7FF, (e >> 13) & 3
    h40 = regs[12] & 1
    sizes = {0: 32, 1: 64, 3: 128}
    pw = sizes.get(regs[16] & 3, 32)
    ph = sizes.get((regs[16] >> 4) & 3, 32)
    a = (regs[2] & 0x38) << 10
    b = (regs[4] & 7) << 13
    yield from nt(a, pw, ph)
    yield from nt(b, pw, ph)
    win = (regs[3] & (0x3C if h40 else 0x3E)) << 10
    yield from nt(win, 64 if h40 else 32, 32)
    sat = (regs[5] & (0x7E if h40 else 0x7F)) << 9
    link, n = 0, 0
    while n < 80:
        o = sat + link * 8
        size = vram[o + 2]
        attr = (vram[o + 4] << 8) | vram[o + 5]
        w = ((size >> 2) & 3) + 1
        h = (size & 3) + 1
        for t in range(w * h):
            yield ((attr & 0x7FF) + t) & 0x7FF, (attr >> 13) & 3
        link = vram[o + 3] & 0x7F
        n += 1
        if link == 0:
            break


def placements(vram, regs):
    """Yield (plane, x, y, tile) for plane A and B nametable entries."""
    sizes = {0: 32, 1: 64, 3: 128}
    pw = sizes.get(regs[16] & 3, 32)
    ph = sizes.get((regs[16] >> 4) & 3, 32)
    for plane, addr in ((0, (regs[2] & 0x38) << 10), (1, (regs[4] & 7) << 13)):
        for y in range(ph):
            for x in range(pw):
                o = addr + 2 * (y * pw + x)
                if o + 1 >= 0x10000:
                    continue
                e = (vram[o] << 8) | vram[o + 1]
                yield plane, x, y, e & 0x7FF


def job(name):
    e = Emu(os.path.join(ROOT, 'baserom.gen'))
    e.callwatch([PC_DMA, PC_COPY, PC_PAL])
    pending = []           # (due_frame, src, len, first_tile, ntiles)
    votes = defaultdict(Counter)
    colors = defaultdict(Counter)
    layout = defaultdict(Counter)
    dmas, copies, pals = set(), set(), set()
    f = 0
    for btns, n in scenario.SCENARIOS[name]():
        e.set_buttons(*btns)
        for _ in range(n):
            e.run(1)
            f += 1
            log = e.callwatch_log()
            if len(log):
                e.callwatch([PC_DMA, PC_COPY, PC_PAL])
            for row in log:
                pc = int(row[0]); d = [int(x) for x in row[1:9]]; a = [int(x) & 0xFFFFFF for x in row[9:17]]
                if pc == PC_DMA:
                    src, typ, d1 = a[0], d[0] & 0xFFFF, d[1]
                    ln = (d1 & 0xFFFF) * 2
                    dest = (d1 >> 16) & 0xFFFF
                    if src < 0x400000 and ln:
                        dmas.add((src, ln, typ, dest))
                        if typ == 2 and ln % 32 == 0:
                            pending.append((f + DELAY, src, ln, dest // 32, ln // 32))
                elif pc == PC_COPY:
                    if a[0] < 0x400000:
                        copies.add((a[0], d[0] & 0xFFFF, a[1]))
                elif pc == PC_PAL:
                    if a[0] < 0x400000:
                        pals.add(a[0])
            due = [p for p in pending if p[0] <= f]
            if due:
                pending = [p for p in pending if p[0] > f]
                vram, cram, vsram, regs = e.vdp()
                refs = Counter(tile_refs(vram, regs))
                grid = {}
                for plane, x, y, t in placements(vram, regs):
                    grid[(plane, x, y)] = t
                for _, src, ln, t0, nt in due:
                    for (plane, x, y), t in grid.items():
                        if t0 <= t < t0 + nt:
                            below = grid.get((plane, x, y + 1))
                            right = grid.get((plane, x + 1, y))
                            if right == t + 1 and below is not None and t0 <= below < t0 + nt and below > t:
                                layout[(src, ln)][below - t] += 1
                    c = Counter()
                    for (t, pl), k in refs.items():
                        if t0 <= t < t0 + nt:
                            c[pl] += k
                    if c:
                        pl = c.most_common(1)[0][0]
                        votes[(src, ln)][pl] += 1
                        colors[(src, ln)][tuple(cram_to_md(x) for x in cram[pl * 16:pl * 16 + 16])] += 1
    e.close()
    return name, dmas, copies, pals, votes, colors, layout


def main():
    out = os.path.join(ROOT, 'assets', 'probe.json')
    names = list(scenario.SCENARIOS)
    dmas, copies, pals = set(), set(), set()
    votes = defaultdict(Counter); colors = defaultdict(Counter); layout = defaultdict(Counter)
    with Pool(4) as p:
        for name, d, c, pl, v, col, lay in p.imap_unordered(job, names):
            for k, cnt in lay.items(): layout[k].update(cnt)
            dmas |= d; copies |= c; pals |= pl
            for k, cnt in v.items(): votes[k].update(cnt)
            for k, cnt in col.items(): colors[k].update(cnt)
            print('done', name, flush=True)
    res = {
        'dma': sorted(dmas), 'copy': sorted(copies), 'palettes': sorted(pals),
        'gfx_palette': {'%X:%X' % k: {'line': votes[k].most_common(1)[0][0],
                                      'colors': list(colors[k].most_common(1)[0][0])} for k in votes},
        'gfx_width': {'%X:%X' % k: layout[k].most_common(1)[0][0] for k in layout if layout[k]},
    }
    json.dump(res, open(out, 'w'), indent=0)
    print('dma', len(dmas), 'copy', len(copies), 'palettes', len(pals), 'coloured', len(votes))


if __name__ == '__main__':
    main()
