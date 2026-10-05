#!/usr/bin/env python3
"""Generate the injectable mouse / multi-select payload for third-party ROMs.

`make payload` builds build/payload/payload.bin + hooks.json out of
src/c/input.c and src/c/group.c alone - no full ROM rebuild involved.  The
payload carries its own hook trampolines (config.MOD_HOOKS) and the C -> asm
thunks, links at the end of the base ROM and keeps its state in the free RAM
block (rom.ld's FFC380 area).  tools/modpatch.py then injects it into any ROM
whose code matches the R82c base (the hundreds of existing Dune II mods are
data edits of exactly that base).

usage:
  payload.py gen DIR           write DIR/payload.s, DIR/payload.ld,
                               DIR/hooks.tpl.json
  payload.py postlink ELF DIR  after linking (m68k-linux-gnu-nm on ELF):
                               write DIR/hooks.json (ready patch bytes) and
                               DIR/payload.info.json

env: PAYLOAD_BASE  payload link address (default: size of baserom.gen; the
                    payload is appended to the ROM, so the base is its length)
"""
import json
import os
import re
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, 'disasm'))

import config                                     # noqa: E402  (needs sys.path)
import csig                                       # noqa: E402
import names                                      # noqa: E402

C_FILES = ('input.c', 'group.c')                  # the whole payload
RAM_BSS = 0xFFC380                                # free RAM block, as rom.ld
RAM_BSS_MAX = 0x1C0
CODE_END = 0x1FA82                                # base ROM code region (generate.py)
PAYLOAD_FUNCS = {'Input_PadHook', 'Cursor_Hook', 'Group_OrderFrame', 'Group_DrawMarkers'}


def addr_of(label):
    """Address of a game label, from names.py or an address-encoded name."""
    rev = {n: a for a, n in names.NAMES.items()}
    if label in rev:
        return rev[label]
    m = re.fullmatch(r'(?:sub|loc|dat|ram)_([0-9A-Fa-f]{6})', label)
    if m:
        return int(m.group(1), 16)
    raise KeyError(label)


def strip_comments(txt):
    txt = re.sub(r'/\*.*?\*/', '', txt, flags=re.S)
    return re.sub(r'//[^\n]*', '', txt)


def used_declarations():
    """(C symbol -> ('thunk'|'alias'|'ram', address, label)) for everything
    input.c/group.c reference outside the payload, derived from their text."""
    body = strip_comments(''.join(open(os.path.join(ROOT, 'src', 'c', f)).read() for f in C_FILES))
    decls = {}
    # every extern declaration with RAM()/ASM() in the payload C files + dune2.h
    #   extern <type> <name>(params)|[[]] RAM(x) / ASM(x);
    # ASM(x) renames the symbol to <name>_asm (see dune2.h), RAM(x) keeps it.
    decl = re.compile(r'extern[^;{]*?\b(\w+)\s*(?:\([^)]*\)|\[[^\]]*\]|\s)*(?:(RAM)|(ASM))\((\w+)\)\s*;')
    for f in C_FILES + ('dune2.h',):
        txt = strip_comments(open(os.path.join(ROOT, 'src', 'c', f)).read())
        for m in decl.finditer(txt):
            decls[m.group(1)] = (m.group(4), 'ASM' if m.group(3) else 'RAM')
    sigs = csig.load()                              # (kind, label) -> (ret, args)
    ram = {n: a for a, n in names.RAM_NAMES.items()}
    out = {}
    for cname, (label, macro) in decls.items():
        if not re.search(r'\b%s\b' % re.escape(cname), body):
            continue                                # declared but not used
        if cname == 'g_mouse':                      # defined inside the payload
            continue
        sig = sigs.get(('ASM', label))
        if sig is not None and addr_of(label) < CODE_END:
            out[cname] = ('thunk', addr_of(label), label)      # code: C -> thunk
        elif label in ram:
            out[cname] = ('ram', ram[label], label)
        elif macro == 'ASM':
            out[cname + '_asm'] = ('alias', addr_of(label), label)
        else:
            out[cname] = ('alias', addr_of(label), label)      # data: plain alias
    # register-argument helpers used through inline asm ("jsr X_asm")
    for m in re.finditer(r'jsr\s+(\w+)_asm\b', body):
        label = m.group(1)
        out[label + '_asm'] = ('alias', addr_of(label), label)
    return out


def game_labels_of_tramps(hooks):
    """Game labels the hook trampolines jump to (labels in (..) operands)."""
    out = {}
    for h in hooks.values():
        for line in h.get('tramp', []):
            line = line.split('|')[0]
            for m in re.finditer(r'\(([A-Za-z_]\w*)\)(?:\.l)?', line):
                s = m.group(1)
                if s in PAYLOAD_FUNCS or s.startswith('Hook_') or s in ('sp', 'a0', 'a1'):
                    continue
                if s not in out:
                    out[s] = addr_of(s)
    return out


def parse_hook_lines(hook):
    """config MOD_HOOKS 'code' lines -> [(mnemonic, target|None)] in order."""
    ops = []
    for line in hook['code']:
        line = line.split('|')[0].strip()
        m = re.fullmatch(r'(jmp|jsr)\s+\((\w+)\)\.l', line)
        if m:
            ops.append((m.group(1), m.group(2)))
        elif re.fullmatch(r'nop', line):
            ops.append(('nop', None))
        else:
            raise ValueError('MOD_HOOKS %s: cannot encode %r' % (hook.get('what', '?'), line))
    return ops


def encode_hook(ops, syms):
    """Patch bytes written over the hook site (absolute jmp/jsr.l + nops)."""
    out = bytearray()
    for mn, target in ops:
        if mn == 'nop':
            out += b'\x4E\x71'
        elif mn in ('jmp', 'jsr'):
            out += bytes((0x4E, 0xF9 if mn == 'jmp' else 0xB9))
            out += struct.pack('>I', syms[target])
        else:
            raise ValueError('cannot encode %r as hook bytes' % (mn,))
    return bytes(out)


def c_thunk(label, sig):
    """<label>_asm for C: repack 4-byte C argument slots into the original
    words / longs; keep every register C expects preserved.
    (Ported verbatim from tools/disasm/emit.py Emitter.c_thunk.)"""
    ret, args = sig
    out = ['\t.globl\t%s_asm' % label,
           '%s_asm:\t\t| C -> original, args %s' % (label, ''.join(args) or '-'),
           '\tmovem.l\td3-d7/a2-a6,-(sp)']
    pushed = 0
    for i in reversed(range(len(args))):
        slot = 4 + 40 + 4 * i + pushed              # 10 saved registers
        if args[i] == 'w':
            out.append('\tmove.w\t(%d,sp),-(sp)' % (slot + 2))
            pushed += 2
        else:
            out.append('\tmove.l\t(%d,sp),-(sp)' % slot)
            pushed += 4
    out.append('\tjsr\t(%s).l' % label)
    if pushed:
        out.append('\tlea\t(%d,sp),sp' % pushed)
    if ret == 'p':
        out.append('\tmove.l\ta0,d0')
    out += ['\tmovem.l\t(sp)+,d3-d7/a2-a6', '\trts']
    return out


def payload_base():
    if os.environ.get('PAYLOAD_BASE'):
        return int(os.environ['PAYLOAD_BASE'], 0)
    p = os.path.join(ROOT, 'baserom.gen')
    if not os.path.exists(p):
        sys.exit('payload: no baserom.gen (run make setup) and no PAYLOAD_BASE set')
    n = os.path.getsize(p)
    if n & 1:
        sys.exit('payload: baserom.gen has odd size %d' % n)
    return n


def baserom_sha1():
    import hashlib
    p = os.path.join(ROOT, 'baserom.gen')
    if not os.path.exists(p):
        return None
    return hashlib.sha1(open(p, 'rb').read()).hexdigest()


def gen(outdir):
    os.makedirs(outdir, exist_ok=True)
    base = payload_base()
    hooks = {a: h for a, h in config.MOD_HOOKS.items() if 'flag' not in h}
    used = used_declarations()
    sigs = csig.load()
    tramp_games = game_labels_of_tramps(hooks)

    # ---- sanity: every referenced symbol must resolve to an address
    for cname, (kind, addr, label) in sorted(used.items()):
        print('  %-24s %-6s %06X' % (cname, kind, addr))
    for label, addr in sorted(tramp_games.items()):
        print('  %-24s %-6s %06X' % (label, 'tramp', addr))

    # ---- payload.s
    s = ['| Injectable mouse / multi-select payload (applied by tools/modpatch.py).',
         '| Generated by tools/payload.py - do not edit: change src/c/ or',
         '| tools/disasm/config.py and run make payload again.',
         '\t.text',
         '\t.balign\t2',
         '| payload header, never executed (nothing jumps to the base address)',
         '\t.ascii\t"D2MP"',
         '\t.word\t1']
    for a, h in sorted(hooks.items()):
        if h.get('tramp'):
            label = h['tramp'][0].rstrip(':')
            s += ['', '| ---- %s (config.MOD_HOOKS %06X)' % (h.get('what', ''), a),
                 '\t.globl\t%s' % label] + h['tramp']
    for cname, (kind, addr, label) in sorted(used.items()):
        if kind == 'thunk':
            s += ['', '| ---- C -> game thunk'] + c_thunk(label, sigs[('ASM', label)])
    open(os.path.join(outdir, 'payload.s'), 'w').write('\n'.join(s) + '\n')

    # ---- payload.ld
    syms = dict(tramp_games)
    for cname, (kind, addr, label) in used.items():
        if kind == 'thunk':
            syms[label] = addr                       # the thunk jsr's the raw label
        else:
            syms[cname] = addr                       # RAM / data: the C symbol itself
    ld = ['/* Injectable payload linker script - generated by tools/payload.py */',
          'OUTPUT_FORMAT("elf32-m68k")',
          'OUTPUT_ARCH(m68k)',
          'SECTIONS',
          '{',
          '\t.text 0x%06X :' % base,
          '\t{',
          '\t\t*(.text .text.*)',
          '\t\t*(.rodata .rodata.*)',
          '\t\t. = ALIGN(2);',
          '\t}',
          '\t.data : { *(.data .data.*) }',
          '\tASSERT(SIZEOF(.data) == 0, "payload must not use initialised writable data")',
          '\t.bss 0x%06X (NOLOAD) : { *(.bss .bss.* COMMON) }' % RAM_BSS,
          '\tASSERT(SIZEOF(.bss) <= 0x%03X, "payload state does not fit the free RAM block")' % RAM_BSS_MAX,
          '\t/DISCARD/ : { *(.comment) *(.note*) *(.eh_frame) }',
          '}',
          '/* ---- game symbols (R82c addresses, absolute) */']
    for n in sorted(syms):
        ld.append('%s = 0x%06X;' % (n, syms[n]))
    open(os.path.join(outdir, 'payload.ld'), 'w').write('\n'.join(ld) + '\n')

    # ---- hooks.tpl.json (bytes are filled in postlink, when label addresses are known)
    tpl = {'payload_base': base, 'baserom_sha1': baserom_sha1(), 'code_end': CODE_END,
           'hooks': [{'addr': a, 'size': h['size'], 'what': h.get('what', ''),
                      'ops': parse_hook_lines(h)} for a, h in sorted(hooks.items())],
           # every game code symbol the payload calls or hooks (data / RAM are
           # the mod's own and are never checked)
           'protected': sorted({v[1] for v in used.values() if v[1] < CODE_END}
                               | set(tramp_games.values())
                               | set(hooks))}
    json.dump(tpl, open(os.path.join(outdir, 'hooks.tpl.json'), 'w'), indent=1)
    print('payload: gen -> %s (base %06X, %d hooks, %d protected symbols)'
          % (outdir, base, len(tpl['hooks']), len(tpl['protected'])))


def elf_symbols(elf):
    nm = os.environ.get('NM', 'm68k-linux-gnu-nm')
    out = subprocess.run([nm, elf], capture_output=True, text=True)
    if out.returncode:
        sys.exit('payload: %s' % out.stderr.strip())
    syms = {}
    for line in out.stdout.splitlines():
        p = line.split()
        if len(p) == 3 and p[1] in 'tTbBdD':
            syms[p[2]] = int(p[0], 16)
    return syms


def postlink(elf, outdir):
    tpl = json.load(open(os.path.join(outdir, 'hooks.tpl.json')))
    syms = elf_symbols(elf)
    missing = {t for h in tpl['hooks'] for _, t in h['ops'] if t and t not in syms}
    missing |= PAYLOAD_FUNCS - set(syms)
    if missing:
        sys.exit('payload: symbols missing from %s: %s' % (elf, ' '.join(sorted(missing))))
    hooks = []
    for h in tpl['hooks']:
        b = encode_hook(h['ops'], syms)
        if len(b) != h['size']:
            sys.exit('payload: hook %06X encodes to %d bytes, size says %d'
                     % (h['addr'], len(b), h['size']))
        hooks.append({'addr': h['addr'], 'size': h['size'], 'bytes': b.hex(),
                      'what': h['what']})
    json.dump({'payload_base': tpl['payload_base'], 'baserom_sha1': tpl['baserom_sha1'],
               'code_end': tpl['code_end'], 'hooks': hooks,
               'protected': tpl['protected'],
               'payload_syms': {n: syms[n] for n in sorted(PAYLOAD_FUNCS)}},
              open(os.path.join(outdir, 'hooks.json'), 'w'), indent=1)
    # the free-RAM state block actually used (for modpatch's sanity check)
    used = [a for n, a in syms.items() if n not in PAYLOAD_FUNCS and RAM_BSS <= a < RAM_BSS + RAM_BSS_MAX]
    bss = (max(used) + 2 - RAM_BSS) if used else 0
    json.dump({'payload_base': tpl['payload_base'], 'baserom_sha1': tpl['baserom_sha1'],
               'bss_addr': RAM_BSS, 'bss_size': bss, 'bss_max': RAM_BSS_MAX},
              open(os.path.join(outdir, 'payload.info.json'), 'w'), indent=1)
    print('payload: postlink -> hooks.json (%d hooks), payload.info.json (bss %d/%d)'
          % (len(hooks), bss, RAM_BSS_MAX))


if __name__ == '__main__':
    if len(sys.argv) >= 3 and sys.argv[1] == 'gen':
        gen(sys.argv[2])
    elif len(sys.argv) >= 4 and sys.argv[1] == 'postlink':
        postlink(sys.argv[2], sys.argv[3])
    else:
        sys.exit(__doc__)
