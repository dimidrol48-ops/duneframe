#!/usr/bin/env python3
"""Run two ROMs side by side on the same input scenario and report the first
frame where work RAM differs (ignoring the C .bss area and the stack).

usage: lockstep.py ROM_A ROM_B [scenario] [--oc N] [--mouse] [--every N] [--persist F]
                   [--equal-timing ELF_B [--elf-a ELF_A]] [--map ELF_A ELF_B] [--no-y] [--stop FRAME]

--equal-timing gives both builds the same timing: the bodies of the
C-replaced routines (taken from ROM_B's ELF, a NONMATCHING build) and
everything past the original ROM's end (C code, stubs, thunks, test hooks)
take no CPU time in the emulator, so the shared code runs on identical
cycles and any difference is a behaviour difference.  ROM_A uses the same
ranges unless --elf-a names an ELF with its own layout (a NONMATCHING build
of it; e.g. the C-only build for the original when ROM_B is a MODS build).
MOD_HOOKS sites are free in both builds.

--map compares ROM pointers in RAM through the two builds' symbol tables
(MODS builds move code in high ROM).  --no-y drops the Y button from the
scenario (in MODS builds Y drags a selection box).

A slower build (the C code) finishes CPU-bound phases such as mission
loading a few frames later, so RAM can differ for a while and then match
again.  With --persist F only differences lasting F frames are reported
(default 0: the first difference).  Run with a generous overclock (--oc 400)
so frame-locked gameplay never lags in either build.
"""
import sys, os, re
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, 'emu'))
from harness import Emu
from scenario import SCENARIOS

MOD_CALLS = ['Map_GetUnitAt', 'Map_GetStructureAt', 'Map_IsCellVisible', 'Selection_Clear']

IGNORE = [(0xC356, 0xC574),      # free RAM used by the C code / mods
          (0xF3B0, 0x10000)]     # stack (boot paints F3B0..SP with FFFF; C / mod code goes deeper)


def elf_syms(elf):
    import subprocess
    syms = []
    for l in subprocess.run(['m68k-linux-gnu-nm', '-n', elf], capture_output=True, text=True).stdout.split('\n'):
        p = l.split()
        if len(p) == 3 and p[1] in 'tT' and not p[2].startswith('.L'):
            syms.append((int(p[0], 16), p[2]))
    return syms


def timing_ranges(elf, orig_len=0x25A342):
    sys.path.insert(0, os.path.join(HERE, 'disasm'))
    sys.path.insert(0, HERE)
    import csig, config
    labels = {lab for (k, lab) in csig.load() if k == 'C_IMPL'}
    syms = elf_syms(elf)
    addrs = sorted(set(a for a, _ in syms))
    # C code, stubs and thunks: from the first C -> asm thunk (c_interface.inc,
    # at the end of the main text) to the end of the ROM
    thunks = [a for a, n in syms if n.endswith('_asm') and a > 0x100000]
    c_start = min(thunks) if thunks else orig_len
    rs = []
    for a, n in syms:
        if n in labels and a < c_start:
            nxt = next(x for x in addrs if x > a)
            rs.append((a, nxt))
    for a, h in getattr(config, 'MOD_HOOKS', {}).items():
        if h.get('flag', 'MODS') == 'MODS':
            rs.append((a, a + h['size']))
    # original routines that the mods' C code calls on top of what the game
    # does (double-tap checks, box selection): free in both builds, so those
    # extra calls do not shift the timing.  Not all of C_EXPORTS: some of
    # them wait for VBlank, and a free wait loop never ends.
    starts = [(a, n) for a, n in syms if not re.match(r'(loc_|wloc_|jtbl_|\.L)', n)]
    sa = [a for a, _ in starts]
    byname = {n: a for a, n in syms}
    for n in MOD_CALLS:
        a = byname.get(n)
        if a is None or a not in sa or sa.index(a) + 1 >= len(sa):
            continue
        rs.append((a, sa[sa.index(a) + 1]))
    # asm routines the original bodies of C-replaced routines call but the C
    # code does not (the C version does that work itself, e.g. an inlined
    # allocator or division): free in both builds, or the original spends
    # cycles the C build does not
    for n in inlined_helpers(elf):
        a = byname.get(n)
        if a is None or a not in sa or sa.index(a) + 1 >= len(sa):
            continue
        rs.append((a, sa[sa.index(a) + 1]))
    rs = merge_ranges(rs)
    rs.append((c_start, 0x400000))
    return rs


_HELPERS = {}


def inlined_helpers(elf):
    import subprocess, check_regouts as cr, csig, config
    wide = 0
    for l in subprocess.run(['m68k-linux-gnu-nm', elf], capture_output=True, text=True).stdout.split('\n'):
        p = l.split()
        if len(p) == 3 and p[2] == 'WIDE':
            wide = int(p[0], 16)
    if wide in _HELPERS:
        return _HELPERS[wide]
    insns, labels = cr.parse(cr.flatten({'WIDE': wide, 'NONMATCHING': 0, 'MODS': 0, 'AUTOPLAY': 0}))
    ref = {cr.target(i) for i in insns if i.mn in ('jsr', 'bsr') and i.ops}
    starts = cr.func_starts(insns, labels, ref)
    impl = {lab for (k, lab) in csig.load() if k == 'C_IMPL'}
    names = getattr(config, 'NAMES', {})
    exported = {names.get(a, 'sub_%06X' % a) for a in getattr(config, 'C_EXPORTS', [])}
    out = set()
    for lab in impl:
        if lab not in labels:
            continue
        seen, work = set(), [labels[lab]]
        while work:
            i = work.pop()
            while i < len(insns) and i not in seen:
                seen.add(i)
                ins = insns[i]
                if ins.mn.startswith('.') or ins.mn in ('rts', 'rte'):
                    break
                if ins.mn in ('jsr', 'bsr', 'jmp'):
                    t = cr.target(ins)
                    if t in labels and labels[t] in starts:
                        if t not in impl and t not in exported:
                            out.add(t)
                    elif ins.mn == 'jmp' and t in labels:
                        work.append(labels[t])
                    if ins.mn == 'jmp':
                        break
                if ins.mn in cr.BRANCH or ins.mn in cr.DBCC:
                    t = re.sub(r'\.[sbwl]$', '', ins.ops[-1] if ins.ops else '')
                    if t in labels:
                        work.append(labels[t])
                    if ins.mn == 'bra':
                        break
                i += 1
    _HELPERS[wide] = sorted(out)
    return _HELPERS[wide]


def merge_ranges(rs):
    out = []
    for lo, hi in sorted(rs):
        if out and lo <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], hi))
        else:
            out.append((lo, hi))
    return out


def ptr_map(elf_a, elf_b):
    """B ROM address -> A ROM address, through labels both builds have."""
    import bisect
    sa = {n: a for a, n in elf_syms(elf_a)}
    pairs = sorted((b, sa[n]) for b, n in elf_syms(elf_b) if n in sa)
    keys = [b for b, _ in pairs]
    def m(v):
        i = bisect.bisect_right(keys, v) - 1
        if i < 0:
            return v
        b, a = pairs[i]
        return a + (v - b)
    return m


def _masked(x):
    return x[:IGNORE[0][0]] + x[IGNORE[0][1]:IGNORE[1][0]]


def diffs(a, b, pmap=None):
    if a == b or _masked(a) == _masked(b):
        return []
    out = []
    for i in range(0, 0x10000, 2):
        if a[i:i+2] != b[i:i+2] and not any(lo <= i < hi for lo, hi in IGNORE):
            if pmap and explained(a, b, i, pmap):
                continue
            out.append(i)
    return out


def explained(a, b, i, pmap):
    """The word at i belongs to a ROM pointer that maps from B to A (or is a
    queued VDP DMA source register write, 0x95xx-0x97xx, for moved data)."""
    if a[i] == b[i] and a[i] in (0x95, 0x96, 0x97):
        return True
    for j in (i, i - 2):
        if j < 0 or j + 4 > 0x10000:
            continue
        va = int.from_bytes(a[j:j+4], 'big'); vb = int.from_bytes(b[j:j+4], 'big')
        if 0x200 <= vb < 0x400000 and pmap(vb) == va:
            return True
    return False


def main():
    args = [a for a in sys.argv[1:]]
    opt = lambda k, d: (int(args[args.index(k) + 1]), args.__delitem__(slice(args.index(k), args.index(k) + 2)))[0] if k in args else d
    oc = opt('--oc', 100); every = opt('--every', 1); persist = opt('--persist', 0); stop = opt('--stop', 0)
    def sopt(k, n=1):
        if k not in args:
            return None
        i = args.index(k); v = args[i + 1:i + 1 + n]; del args[i:i + 1 + n]
        return v if n > 1 else v[0]
    eq = sopt('--equal-timing'); elf_a = sopt('--elf-a'); mp = sopt('--map', 2)
    mouse = '--mouse' in args
    noy = '--no-y' in args
    args = [a for a in args if a not in ('--mouse', '--no-y')]
    pmap = ptr_map(*mp) if mp else None
    ra, rb = args[0], args[1]
    scen = args[2] if len(args) > 2 else 'mission1'
    es = [Emu(r, options={'genesis_plus_gx_overclock': str(oc)}, mouse=mouse) for r in (ra, rb)]
    if eq:
        rb_ = timing_ranges(eq)
        ra_ = timing_ranges(elf_a) if elf_a else rb_
        print('equal timing: %d / %d free ranges' % (len(ra_), len(rb_)))
        es[0].free_ranges(ra_)
        es[1].free_ranges(rb_)
    f = 0
    since, first = None, None
    healed = 0
    for btns, n in SCENARIOS[scen]():
        if noy:
            btns = tuple(b for b in btns if b != 'Y')
        for e in es: e.set_buttons(*btns)
        if stop and f >= stop:
            break
        while n > 0:
            k = min(every, n)
            for e in es: e.run(k)
            f += k; n -= k
            a, b = es[0].ram(), es[1].ram()
            d = diffs(a, b, pmap)
            if d and since is None:
                since, first = f, (d, a, b)
            elif not d and since is not None:
                healed += 1
                since = None
            if d and f - since >= persist:
                d0, a0, b0 = first
                print('RAM difference from frame %d to %d (persisting)' % (since, f))
                for i in d0[:40]:
                    print('  %06X  %s  %s' % (0xFF0000 + i, a0[i:i+2].hex(), b0[i:i+2].hex()))
                if len(d0) > 40: print('  ... %d words' % len(d0))
                print('now %d words differ' % len(d))
                return es, f
    print('no lasting difference in %d frames (%d transient ones)' % (f, healed))
    return es, f


if __name__ == '__main__':
    main()
