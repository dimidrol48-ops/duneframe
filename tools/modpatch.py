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

usage: modpatch.py MODROM [OUTROM] [--payload DIR] [--check] [--force-code]
       --check      only report compatibility, write nothing
"""
import hashlib
import json
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, 'disasm'))

MAX_ROUTINE = 0x2000        # sanity cap for a routine's extent


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


def expected_baserom_sha1():
    """The one true base, as in the Makefile / tools/setup/setup.sh."""
    mk = open(os.path.join(ROOT, 'Makefile')).read()
    m = re.search(r'^BASEROM_SHA1\s*:?=\s*([0-9a-f]{40})', mk, re.M)
    return m.group(1) if m else None


def baserom_bytes():
    p = os.path.join(ROOT, 'baserom.gen')
    if not os.path.exists(p):
        sys.exit('modpatch: baserom.gen not found (run make setup first)')
    want = expected_baserom_sha1()
    if want and rom_sha1(p) != want:
        sys.exit('modpatch: baserom.gen is not the R82c base ROM (sha1 mismatch)')
    return open(p, 'rb').read()


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
def main():
    args, opts = [], {}
    argv = sys.argv[1:]
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ('--check', '--force-code'):
            opts[a[2:]] = True
        elif a == '--payload':
            i += 1
            opts['payload'] = argv[i]
        elif a in ('-h', '--help'):
            sys.exit(__doc__)
        else:
            args.append(a)
        i += 1
    if len(args) < 1 or len(args) > 2:
        sys.exit(__doc__)
    modrom_path = args[0]
    out_path = args[1] if len(args) > 1 else re.sub(r'\.gen$', '', modrom_path) + '_mouse.gen'
    pdir = opts.get('payload', 'build/payload')

    baserom = baserom_bytes()                     # the clean R82c base, sha1-checked
    hooks, info, blob = load_payload(pdir)
    modrom = bytearray(open(modrom_path, 'rb').read())   # patch() mutates it in place
    if len(modrom) != len(baserom):
        sys.exit('modpatch: %s is %d bytes, baserom.gen is %d - not the same base'
                 % (modrom_path, len(modrom), len(baserom)))
    if hooks.get('baserom_sha1') and hooks['baserom_sha1'] != rom_sha1(os.path.join(ROOT, 'baserom.gen')):
        sys.exit('modpatch: the payload was built against a different baserom.gen - run make payload again')

    print('modpatch: %s' % modrom_path)
    print('  payload: %d hooks, %d protected ranges, %d bytes at %06X'
          % (len(hooks['hooks']), len(protected_ranges(hooks, baserom)), len(blob), hooks['payload_base']))
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
                 '         (--force-code patches anyway; the mouse may misbehave)' % len(problems))

    out, s = patch(modrom, hooks, info, blob)
    open(out_path, 'wb').write(out)
    print('  wrote %s: %d bytes (+%d), checksum %04X'
          % (out_path, len(out), len(out) - len(modrom), s))
    print('  play it like build/mod/dune2.gen (Sega Mouse on port 2; left-drag or Y = selection box)')


if __name__ == '__main__':
    main()
