#!/usr/bin/env python3
"""Tests for tools/modpatch.py + tools/payload.py (no ROM needed: synthetic
baseroms built from the real config addresses).

usage: python3 tools/test_modpatch.py
"""
import importlib.util
import json
import os
import struct
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'disasm'))


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, name + '.py'))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


modpatch = load('modpatch')
payload = load('payload')

import config                                     # noqa: E402

ROMSIZE = 0x240000
FAILS = []


def check(what, ok, info=''):
    print('%-58s %s %s' % (what, 'ok' if ok else 'FAIL', info))
    if not ok:
        FAILS.append(what)


# ---- a synthetic clean base ROM: every address the payload touches holds a
# tiny routine (moveq #0,d0; rts), hook sites hold distinct filler bytes
def make_baserom():
    rom = bytearray(b'\xE0' + b'\x00' * (ROMSIZE - 1))
    rom[0x100:0x104] = b'SEGA'
    syms = sorted({a for a in config.MOD_HOOKS} | {
        0x0005BA, 0x00062A, 0x008C12, 0x002718, 0x00233C,   # thunks + alias
        0x00400A, 0x001368, 0x0037F0, 0x002D70})             # tramp targets
    for a in syms:
        rom[a:a + 4] = b'\x70\x00\x4E\x75'                   # moveq #0,d0 ; rts
    for a, h in config.MOD_HOOKS.items():
        if 'flag' not in h:
            rom[a:a + h['size']] = bytes([0x11] * h['size'])
    return bytes(rom)


def make_hooks(patch_addrs=None):
    """hooks.json + payload.info.json as modpatch.py postlink would write them."""
    hooks = []
    for a, h in sorted(config.MOD_HOOKS.items()):
        if 'flag' in h:
            continue
        b = b'\x4E\xB9' + struct.pack('>I', 0x240010) if h['size'] == 6 else \
            b'\x4E\xF9' + struct.pack('>I', 0x240020) + b'\x4E\x71'
        hooks.append({'addr': a, 'size': h['size'], 'bytes': b.hex(), 'what': h['what']})
    return {'payload_base': ROMSIZE, 'baserom_sha1': None, 'code_end': 0x1FA82,
            'hooks': hooks,
            'protected': [0x0005BA, 0x00062A, 0x008C12, 0x002718, 0x00233C,
                          0x00400A, 0x001368, 0x0037F0, 0x002D70]}


# ---------------------------------------------------------------- payload.py
def test_payload():
    b = payload.encode_hook([('jmp', 'x')], {'x': 0x123456})
    check('encode_hook jmp', b == bytes.fromhex('4EF9') + bytes.fromhex('00123456'))
    b = payload.encode_hook([('jsr', 'y'), ('nop', None)], {'y': 0x240010})
    check('encode_hook jsr+nop', b == bytes.fromhex('4EB9') + bytes.fromhex('00240010') + bytes.fromhex('4E71'))
    try:
        payload.encode_hook([('lea', 'y')], {'y': 0})
        check('encode_hook rejects unknown', False)
    except ValueError:
        check('encode_hook rejects unknown', True)
    # every MODS hook must encode to exactly its size (AUTOPLAY/TESTHW hooks excluded)
    for a, h in config.MOD_HOOKS.items():
        if 'flag' in h:
            continue
        ops = payload.parse_hook_lines(h)
        b = payload.encode_hook(ops, {t: 0x240000 for _, t in ops if t})
        check('hook %06X encodes to %d bytes' % (a, h['size']), len(b) == h['size'], repr(b.hex()))
    # used_declarations: the known extern set of input.c + group.c
    used = payload.used_declarations()
    want = {'Order_Frame', 'Map_GetUnitAt', 'Map_GetStructureAt', 'Selection_Clear'}
    check('payload thunks found', want <= set(used), sorted(set(want) - set(used)) or '')
    check('payload k_unitPtrs alias', used.get('k_unitPtrs_asm', (None,))[0] == 'alias')
    check('payload g_spriteTable ram', used.get('g_spriteTable', (None,))[0] == 'ram')
    check('payload Map_IsCellVisible_asm', used.get('Map_IsCellVisible_asm', (None,))[0] == 'alias')
    check('payload g_mouse excluded', 'g_mouse' not in used)


# ---------------------------------------------------------------- modpatch.py
def test_modpatch():
    base = make_baserom()
    hooks = make_hooks()
    blob = b'D2MP' + bytes(range(60))

    # compatibility: identical ROM
    p, n = modpatch.scan(base, base, hooks)
    check('scan: identical ROM is compatible', not p and not n)

    # data-only mod
    mod = bytearray(base)
    mod[0x100000:0x100010] = b'\xAA' * 0x10
    p, n = modpatch.scan(base, bytes(mod), hooks)
    check('scan: data-only mod passes', not p)
    check('scan: data diff reported', any('data bytes' in x for x in n), n)

    # hook site touched
    mod = bytearray(base)
    mod[0x001242] ^= 0xFF
    p, n = modpatch.scan(base, bytes(mod), hooks)
    check('scan: hook site diff -> incompatible', len(p) == 1 and '001242' in p[0], p)

    # called routine changed
    mod = bytearray(base)
    mod[0x008C12 + 2] ^= 0xFF                      # inside Order_Frame's extent
    p, n = modpatch.scan(base, bytes(mod), hooks)
    check('scan: Order_Frame changed -> incompatible', len(p) >= 1, p)

    # code change outside the touchpoints: allowed, reported
    mod = bytearray(base)
    mod[0x001000:0x001004] = b'\x70\x01\x4E\x75'   # some other routine
    p, n = modpatch.scan(base, bytes(mod), hooks)
    check('scan: unrelated code change allowed', not p, p)
    check('scan: unrelated code change noted', any('code bytes' in x for x in n), n)

    # patching
    mod = bytearray(base)
    mod[0x100000] ^= 0xFF
    out, csum = modpatch.patch(bytes(mod), hooks, {'bss_size': 0x90, 'bss_max': 0x1C0}, blob)
    check('patch: size grows by payload', len(out) == ROMSIZE + len(blob))
    check('patch: payload appended intact', out[ROMSIZE:] == blob)
    ok = all(out[h['addr']:h['addr'] + h['size']] == bytes.fromhex(h['bytes']) for h in hooks['hooks'])
    check('patch: hook bytes written', ok)
    check('patch: header ROM end', struct.unpack_from('>I', out, 0x1A4)[0] == len(out) - 1)
    s = sum(struct.unpack('>%dH' % ((len(out) - 0x200) // 2), out[0x200:])) & 0xFFFF
    check('patch: checksum', struct.unpack_from('>H', out, 0x18E)[0] == s == csum)

    # size mismatch vs payload base
    try:
        modpatch.patch(bytes(0x200000), hooks, {}, blob)
        check('patch: wrong size refused', False)
    except SystemExit:
        check('patch: wrong size refused', True)

    # routine_extent: rts stops it, jmp stops it
    rom = bytearray(b'\x00' * 0x10000)
    rom[0x100:0x104] = b'\x70\x00\x4E\x75'
    rom[0x200:0x204] = b'\x70\x00\x4E\xF9' + b'\x00' * 4
    check('routine_extent rts', modpatch.routine_extent(bytes(rom), 0x100) == (0x100, 0x104))
    check('routine_extent jmp', modpatch.routine_extent(bytes(rom), 0x200) == (0x200, 0x208))

    # protected ranges merge
    r = modpatch.protected_ranges(hooks, base)
    check('protected ranges: sorted, merged', all(a[0] < b[0] and a[1] < b[0] for a, b in zip(r, r[1:])))
    check('protected ranges: hooks covered',
          all(any(s <= h['addr'] and h['addr'] + h['size'] <= e for s, e in r) for h in hooks['hooks']))


# ---------------------------------------------------------------- CLI
def test_cli():
    import subprocess
    r = subprocess.run([sys.executable, os.path.join(HERE, 'modpatch.py')],
                       capture_output=True, text=True)
    check('cli: no args -> usage', r.returncode != 0 and 'usage' in (r.stdout + r.stderr))
    r = subprocess.run([sys.executable, os.path.join(HERE, 'modpatch.py'), '--check', 'x.gen'],
                       capture_output=True, text=True)
    check('cli: missing baserom.gen -> clean error',
          r.returncode != 0 and 'make setup' in (r.stdout + r.stderr),
          (r.stdout + r.stderr).strip().splitlines()[-1] if (r.stdout + r.stderr).strip() else '')


if __name__ == '__main__':
    test_payload()
    test_modpatch()
    test_cli()
    print('\n%s' % ('ALL TESTS PASSED' if not FAILS else 'FAILED: %s' % FAILS))
    sys.exit(1 if FAILS else 0)
