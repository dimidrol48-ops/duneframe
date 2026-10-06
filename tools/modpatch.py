#!/usr/bin/env python3
"""Add the mouse and the unit-selection box to a third-party Dune II ROM.

Hundreds of Dune II (Mega Drive) mods exist; they are data edits of the same
"Full Version R82c" base, so the mod payload built by `make payload` (from
this repo's src/c/input.c + group.c) can be injected into any of them:

  make payload
  tools/modpatch.py SOME_MOD.gen              # -> SOME_MOD_mouse.gen

What it checks first, against your clean baserom.gen:
  - same ROM size, and the payload was built for that base;
  - every hook site (4 x 6-8 bytes) still has the original R82c code;
  - every game routine the payload calls is unchanged (register contracts).
Everything else - graphics, text, unit data, even code the mod changed
elsewhere - is kept exactly as the mod ships it.  Data-only mods always pass;
a mod that rewired the hooked code is refused (or --force-code, at your risk).

The patched ROM assumes the mod kept the R82c RAM layout (data mods do) and
the free RAM block FFC380-FFC540 for the payload state, exactly like this
repo's own `make mod` build.

usage: modpatch.py MODROM [OUTROM] [--payload DIR] [--base BASE] [--check]
                         [--analyze] [--force-code] [--rebuild]
       --check      only report compatibility, write nothing
       --base FILE  clean reference ROM to check against (default: baserom.gen;
                    also $DUNE2_BASE_ROM); its sha1 must match the payload's
       --analyze    self-calibrate on an unknown base: locate the hook sites
                    by code pattern, rebuild the patch bytes for THIS ROM's
                    addresses and write a new payload dir (--payload DIR) -
                    then patch mods built on that base without --base
       --force-code patch even when protected code differs
       --rebuild    after patching, run make payload PAYLOAD_BASE=<size>
                    (only meaningful with --base: the next run needs a payload
                    linked for that base size)
"""
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, 'disasm'))

MAX_ROUTINE = 0x2000        # sanity cap for a routine's extent
PAYLOAD_DIR_DEFAULT = 'build/payload'


# ---------------------------------------------------------------- payload IO
def load_payload(pdir):
    for f in ('hooks.json', 'payload.info.json', 'payload.bin'):
        if not os.path.exists(os.path.join(pdir, f)):
            sys.exit('modpatch: %s missing - run make payload first' % os.path.join(pdir, f))
    hooks = json.load(open(os.path.join(pdir, 'hooks.json')))
    info = json.load(open(os.path.join(pdir, 'payload.info.json')))
    blob = open(os.path.join(pdir, 'payload.bin'), 'rb').read()
    if blob[:4] != b'D2MP':
        sys.exit('modpatch: %s/payload.bin has no D2MP header' % pdir)
    return hooks, info, blob


def rom_sha1(path):
    return hashlib.sha1(open(path, 'rb').read()).hexdigest()


def rom_sha1_bytes(d):
    return hashlib.sha1(bytes(d)).hexdigest()


def expected_baserom_sha1():
    """The one true base, as in the Makefile / tools/setup/setup.sh."""
    try:
        mk = open(os.path.join(ROOT, 'Makefile')).read()
    except OSError:
        return None
    m = re.search(r'^BASEROM_SHA1\s*:?=\s*([0-9a-f]{40})', mk, re.M)
    return m.group(1) if m else None


def baserom_bytes(path=None):
    """The clean reference ROM the mod is checked against.  Default: the
    repo's baserom.gen (must be the R82c base).  --base / $DUNE2_BASE_ROM
    selects another revision instead; then the payload must have been built
    against it (hooks.json baserom_sha1), which makes payload.py gen's
    absolute symbol addresses correct for that base."""
    p = path or os.path.join(ROOT, 'baserom.gen')
    if not os.path.exists(p):
        sys.exit('modpatch: %s not found (run make setup first, or pass --base ROM)' % p)
    d = open(p, 'rb').read()
    if not path:                                    # the repo's own base: R82c
        want = expected_baserom_sha1()
        if want and rom_sha1_bytes(d) != want:
            sys.exit('modpatch: baserom.gen is not the R82c base ROM (sha1 mismatch)\n'
                     '         put the real R82c ROM there (tools/setup/setup.sh --rom),\n'
                     '         or point --base at your clean ROM of another revision')
    return d


# ---------------------------------------------------------------- compatibility
def routine_extent(rom, addr):
    """[addr, end) of the routine at addr, walking the base ROM's code with
    the repo's m68k decoder (stops after the first rts / jmp / stop)."""
    import m68k
    d = m68k.Decoder(rom)
    a = addr
    while a < addr + MAX_ROUTINE:
        try:
            ins = d.decode(a)
        except Exception:
            break
        if ins is None:
            break
        a += ins.length
        if ins.flow in ('ret', 'jump', 'stop'):
            break
    return addr, min(a, addr + MAX_ROUTINE)


def protected_ranges(hooks, rom):
    """Hook sites + the routines the payload calls, as merged half-open ranges."""
    import names
    ranges = [(h['addr'], h['addr'] + h['size']) for h in hooks['hooks']]
    for a in hooks['protected']:
        ranges.append(routine_extent(rom, a))
    ranges.sort()
    merged = []
    for s, e in ranges:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def diff_indices(a, b, skip=None):
    """Byte offsets where a and b differ (same length), skipping [s,e) ranges."""
    out = []
    step = 0x10000
    for lo in range(0, len(a), step):
        hi = min(lo + step, len(a))
        if a[lo:hi] == b[lo:hi]:
            continue
        for i in range(lo, hi):
            if a[i] != b[i] and not (skip and any(s <= i < e for s, e in skip)):
                out.append(i)
    return out


def scan(baserom, modrom, hooks):
    """-> (problems, notes): protected code that differs / what is kept."""
    ranges = protected_ranges(hooks, baserom)
    by_addr = {h['addr']: h['what'] for h in hooks['hooks']}
    problems = []
    for s, e in ranges:
        if baserom[s:e] != modrom[s:e]:
            problems.append('%06X-%06X  %s' % (s, e, by_addr.get(s) or 'routine the payload calls'))
    diffs = diff_indices(baserom, modrom, ranges)
    code = [i for i in diffs if 0x200 <= i < hooks['code_end']]
    notes = []
    if code:
        notes.append('the mod changes %d code bytes outside the payload\'s touchpoints '
                     '(kept as the mod ships it)' % len(code))
    if len(diffs) - len(code):
        notes.append('%d data bytes differ from the base ROM (the mod\'s own content, kept)'
                     % (len(diffs) - len(code)))
    return problems, notes


# ------------------------------------------------- self-calibration (--analyze)
"""Patch mods built on an UNKNOWN base revision.

The hook sites and the routines the payload calls are found in the new ROM by
matching the linear m68k code around them against the R82c reference (the
code shape survives between revisions, only addresses move); every absolute
jmp/jsr.l target inside the payload blob is repointed accordingly.  The C
payload itself needs no rebuild as long as the bases have the same size: its
state lives at fixed RAM and its link address is the end of the ROM.

Two ways in:
  tools/modpatch.py MOD.gen --base CLEAN_REV_X.gen   # check + patch vs a clean
                                             # ROM of that revision (its sha1
                                             # must equal the payload's base)
  tools/modpatch.py CLEAN_REV_X.gen --analyze --payload DIR
                       # no baserom.gen needed: calibrate from this repo's own
                       # byte-exact rebuild build/dune2.gen; writes a patched
                       # payload.bin (+ hooks.json) into DIR, and DIR/base.gen
                       # so later runs need neither --base nor --analyze
"""

STRIPE = 0x40                 # context window around a site, bytes each side
MIN_SCORE = 6                 # minimum matching instructions to accept a move
MAX_SHIFT = 0x8000            # a site may not drift further than this


def ins_stream(rom, start, end):
    """Decode [start,end) into [(addr, mnem, targets)]; undecodable words are
    skipped as filler."""
    import m68k
    d = m68k.Decoder(rom)
    out = []
    a = start
    while a < end - 1:
        try:
            i = d.decode(a)
        except Exception:
            a += 2
            continue
        if i.length == 0 or a + i.length > len(rom):
            break
        out.append((a, i.mnem, tuple(i.targets)))
        a += i.length
    return out


def _align(stripe, ref):
    """Best alignment of the reference instruction sequence `ref` inside
    `stripe`; -> matched instructions of stripe, or None."""
    best = None
    for off in range(len(stripe) - len(ref) + 1):
        n = sum(1 for x, y in zip(stripe[off:off + len(ref)], ref) if x[1:] == y[1:])
        if best is None or n > best[0]:
            best = (n, off)
    if best is None or best[0] < MIN_SCORE:
        return None
    return stripe[best[1]:best[1] + len(ref)]


def relocate(rom, ref_rom, addr, size, anchors, log):
    """Where is the window [addr,addr+size) of ref_rom now?  Match the linear
    code around it against rom; absolute-address operands that moved tell us
    the shift.  -> new addr, or None."""
    lo = max(0x200, addr - STRIPE)
    hi = min(len(rom), addr + size + STRIPE)
    stripe = ins_stream(rom, lo, hi)
    ref = ins_stream(ref_rom, lo, hi)
    if not ref:
        return None
    m = _align(stripe, ref)
    if m is None:
        return None
    shifts = []
    for (ra, rmn, rt), (na, nmn, nt) in zip(ref, m):
        if rmn != nmn or not rt or not nt or rt != nt:
            continue
        s = na - ra
        if abs(s) <= MAX_SHIFT:
            shifts.append(s)
    what = anchors.get(addr, 'routine the payload calls')
    if not shifts:
        log('  %-56s kept at %06X' % (what, addr))
        return addr                          # identical code: no move needed
    s = max(set(shifts), key=shifts.count)   # the majority shift
    if addr + s < 0x200 or addr + s + size > len(rom):
        return None
    log('  %-56s %06X -> %06X (shift %+X)' % (what, addr, addr + s, s))
    return addr + s


def analyze(base_path, pdir, log=print):
    """Calibrate the payload for the clean base ROM at base_path.  Reference:
    this repo's byte-exact rebuild build/dune2.gen when present (so no
    baserom.gen is needed), else baserom.gen.  Writes a repointed payload.bin
    + rewritten hooks.json/payload.info.json into pdir (copied from pdir if
    pdir holds the original build).  -> the new hooks dict."""
    ref_path = os.path.join(ROOT, 'build', 'dune2.gen')
    if os.path.exists(ref_path):
        ref = open(ref_path, 'rb').read()
        log('modpatch: calibrating against %s (this repo\'s rebuild)' % ref_path)
    else:
        ref = baserom_bytes()                # the R82c base, sha1-checked
        log('modpatch: calibrating against baserom.gen (R82c)')
    new = open(base_path, 'rb').read()
    hooks, info, blob = load_payload(pdir)
    if hooks.get('baserom_sha1') and hooks['baserom_sha1'] == rom_sha1(base_path):
        log('  already calibrated for %s' % base_path)
        return hooks
    if len(new) != len(ref):
        sys.exit('modpatch: %s is %d bytes, the reference base is %d\n'
                 '         a different-sized base needs a rebuilt payload:\n'
                 '           cp %s baserom.gen && make payload\n'
                 '         (that overwrites your R82c setup - see docs/MODPATCH.md)'
                 % (base_path, len(new), len(ref), base_path))
    if blob[:4] != b'D2MP':
        sys.exit('modpatch: payload.bin has no D2MP header')
    base_link = hooks['payload_base']

    anchors = {h['addr']: h['what'] for h in hooks['hooks']}
    moved = {}                                  # old addr -> new addr

    # ---- hook sites
    for h in hooks['hooks']:
        a = relocate(new, ref, h['addr'], h['size'], anchors, log)
        if a is None:
            sys.exit('modpatch: cannot locate hook site %06X (%s) in %s -\n'
                     '         not a Dune II code layout this tool can calibrate for'
                     % (h['addr'], h['what'], base_path))
        moved[h['addr']] = a
        h['addr'] = a
    # ---- routines the payload calls (thunks / aliases jump there absolutely)
    for a in list(hooks['protected']):
        if a in moved:
            continue                            # a hook site
        e = routine_extent(ref, a)
        b = relocate(new, ref, a, e[1] - a, anchors, log)
        if b is None:
            sys.exit('modpatch: cannot locate routine %06X in %s' % (a, base_path))
        moved[a] = b
    hooks['protected'] = sorted(moved[a] for a in hooks['protected'])

    # ---- repoint the payload's absolute jmp/jsr.l targets inside the blob.
    # Only targets below the payload's own link base are game code; anything
    # above it is a payload-internal call (same relative layout, untouched).
    blob = bytearray(blob)
    delta = 0
    for a in range(0, len(blob) - 5):
        if blob[a] == 0x4E and blob[a + 1] in (0xB9, 0xF9):
            t = struct.unpack_from('>I', blob, a + 2)[0]
            if t < base_link and t in moved and moved[t] != t:
                struct.pack_into('>I', blob, a + 2, moved[t])
                delta += 1
    log('  payload blob: %d absolute game target(s) repointed' % delta)

    # ---- write the calibrated payload dir (never touch the pristine build:
    # if pdir is the default, copy it to DIR-<sha1[0:8]> and write there)
    sha = rom_sha1(base_path)
    calib_dir = pdir
    if os.path.abspath(pdir) == os.path.abspath(os.path.join(ROOT, PAYLOAD_DIR_DEFAULT)):
        calib_dir = '%s-%s' % (pdir.rstrip('/'), sha[:8])
    os.makedirs(calib_dir, exist_ok=True)
    hooks['baserom_sha1'] = sha
    hooks['calibrated_base'] = os.path.abspath(base_path)
    info['baserom_sha1'] = sha
    json.dump(hooks, open(os.path.join(calib_dir, 'hooks.json'), 'w'), indent=1)
    json.dump(info, open(os.path.join(calib_dir, 'payload.info.json'), 'w'), indent=1)
    open(os.path.join(calib_dir, 'payload.bin'), 'wb').write(bytes(blob))
    shutil.copy(base_path, os.path.join(calib_dir, 'base.gen'))  # later runs: no --base
    log('  wrote %s/{hooks.json,payload.info.json,payload.bin,base.gen}' % calib_dir)
    log('  next: tools/modpatch.py MOD.gen --payload %s   (MOD.gen built on %s)'
        % (calib_dir, base_path))
    return hooks


# ---------------------------------------------------------------- patching
def fix_header(d):
    """ROM end address + checksum, as tools/fixheader.py."""
    if len(d) & 1:
        d.append(0xFF)
    struct.pack_into('>I', d, 0x1A4, max(len(d) - 1, struct.unpack_from('>I', d, 0x1A4)[0]))
    s = sum(struct.unpack('>%dH' % ((len(d) - 0x200) // 2), d[0x200:])) & 0xFFFF
    struct.pack_into('>H', d, 0x18E, s)
    return s


def patch(modrom, hooks, info, blob):
    if len(modrom) != hooks['payload_base']:
        sys.exit('modpatch: ROM is %d bytes, the payload was linked for %d\n'
                 '         rebuild it with: make payload PAYLOAD_BASE=0x%X'
                 % (len(modrom), hooks['payload_base'], len(modrom)))
    if info.get('bss_size', 0) > info.get('bss_max', 0x1C0):
        sys.exit('modpatch: payload state (%d bytes) exceeds the free RAM block' % info['bss_size'])
    out = bytearray(modrom)
    out += blob
    for h in hooks['hooks']:
        out[h['addr']:h['addr'] + h['size']] = bytes.fromhex(h['bytes'])
    csum = fix_header(out)
    return bytes(out), csum


# ---------------------------------------------------------------- CLI
def rebuild_payload(size):
    """Rebuild build/payload for a base of `size` bytes (make payload
    PAYLOAD_BASE=size), so mods of that base can be patched afterwards."""
    env = dict(os.environ, PAYLOAD_BASE=str(size))
    r = subprocess.run(['make', '-C', ROOT, 'payload', 'PAYLOAD_BASE=%d' % size], env=env)
    if r.returncode:
        sys.exit('modpatch: make payload PAYLOAD_BASE=%d failed' % size)


def main():
    args, opts = [], {}
    argv = sys.argv[1:]
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ('--check', '--force-code', '--analyze', '--rebuild'):
            opts[a[2:]] = True
        elif a in ('--payload', '--base'):
            i += 1
            if i >= len(argv):
                sys.exit('modpatch: %s needs an argument' % a)
            opts[a[2:]] = argv[i]
        elif a in ('-h', '--help'):
            sys.exit(__doc__)
        else:
            args.append(a)
        i += 1
    if len(args) < 1 or len(args) > 2:
        sys.exit(__doc__)
    modrom_path = args[0]
    out_path = args[1] if len(args) > 1 else re.sub(r'\.gen$', '', modrom_path) + '_mouse.gen'
    pdir = opts.get('payload') or os.environ.get('DUNE2_PAYLOAD_DIR') or \
        (os.path.join(ROOT, PAYLOAD_DIR_DEFAULT) if not opts.get('analyze') else PAYLOAD_DIR_DEFAULT)
    if not opts.get('payload') and not opts.get('analyze') and \
            os.path.exists(os.path.join(pdir, 'base.gen')):
        opts.setdefault('base', os.path.join(pdir, 'base.gen'))   # calibrated dir

    # ---- --analyze: calibrate the payload for another base revision
    if opts.get('analyze'):
        if len(args) > 1:
            sys.exit('modpatch: --analyze takes one ROM: the CLEAN base to calibrate on')
        analyze(modrom_path, pdir)
        return

    base_path = opts.get('base') or os.environ.get('DUNE2_BASE_ROM') or None
    baserom = baserom_bytes(base_path)          # the clean reference ROM
    hooks, info, blob = load_payload(pdir)
    modrom = bytearray(open(modrom_path, 'rb').read())
    base_sha = rom_sha1_bytes(baserom)
    if len(modrom) != len(baserom):
        sys.exit('modpatch: %s is %d bytes, %s is %d - not the same base\n'
                 '         (--analyze cannot help a different-sized base either:\n'
                 '          make payload PAYLOAD_BASE=%d first, see docs/MODPATCH.md)'
                 % (modrom_path, len(modrom), base_path or 'baserom.gen', len(baserom),
                    len(modrom)))
    if hooks.get('baserom_sha1') and hooks['baserom_sha1'] != base_sha:
        msg = ('modpatch: the payload was built against a different base ROM '
               '(sha1 %s...)' % hooks['baserom_sha1'][:12])
        if base_path:
            msg += '\n         rebuild it for that base: make payload PAYLOAD_BASE=%d' % len(baserom)
        else:
            msg += '\n         run make payload again, or pass --base / --analyze'
        sys.exit(msg)
    if not base_path and expected_baserom_sha1() and base_sha != expected_baserom_sha1():
        print('  note: checking against a non-R82c baserom.gen (calibrated copy?)')

    print('modpatch: %s' % modrom_path)
    print('  base:   %s (%d bytes, sha1 %s...)'
          % (base_path or 'baserom.gen', len(baserom), base_sha[:12]))
    print('  payload: %d hooks, %d protected ranges, %d bytes at %06X'
          % (len(hooks['hooks']), len(protected_ranges(hooks, baserom)), len(blob),
             hooks['payload_base']))
    problems, notes = scan(baserom, modrom, hooks)
    for p in problems:
        print('  INCOMPATIBLE: %s' % p)
    for n in notes:
        print('  note: %s' % n)

    if opts.get('check'):
        print('  check: %s' % ('INCOMPATIBLE - not patchable' if problems else 'compatible'))
        sys.exit(1 if problems else 0)
    if problems and not opts.get('force-code'):
        sys.exit('modpatch: %d protected code range(s) differ - not patched\n'
                 '         (--force-code patches anyway; the mouse may misbehave)\n'
                 '         (if this mod is built on ANOTHER base revision, run\n'
                 '          modpatch.py CLEAN_BASE.gen --analyze first)' % len(problems))

    out, s = patch(modrom, hooks, info, blob)
    open(out_path, 'wb').write(out)
    print('  wrote %s: %d bytes (+%d), checksum %04X'
          % (out_path, len(out), len(out) - len(modrom), s))
    print('  play it like build/mod/dune2.gen (Sega Mouse on port 2; left-drag or Y = selection box)')
    if opts.get('rebuild'):
        rebuild_payload(len(baserom))


if __name__ == '__main__':
    main()
