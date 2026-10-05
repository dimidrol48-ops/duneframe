"""Emit GNU-as source from an Analysis.

Every instruction is validated against the assembler (see validate());
instructions GAS would encode differently are emitted as raw opcode words
with symbolic extension words, so the output is byte-exact *and*
relocatable.
"""
import os, re, struct, subprocess, tempfile
from m68k import reglist_str

IO_NAMES = {
    0xC00000: 'VDP_DATA', 0xC00002: 'VDP_DATA2', 0xC00004: 'VDP_CTRL', 0xC00006: 'VDP_CTRL2', 0xC00008: 'VDP_HVCOUNTER',
    0xC00011: 'PSG_PORT', 0xA00000: 'Z80_RAM', 0xA04000: 'YM2612_A0', 0xA04001: 'YM2612_D0',
    0xA04002: 'YM2612_A1', 0xA04003: 'YM2612_D1',
    0xA10001: 'IO_VERSION', 0xA10003: 'IO_DATA1', 0xA10005: 'IO_DATA2', 0xA10007: 'IO_DATA3',
    0xA10009: 'IO_CTRL1', 0xA1000B: 'IO_CTRL2', 0xA1000D: 'IO_CTRL3',
    0xA11100: 'Z80_BUSREQ', 0xA11200: 'Z80_RESET', 0xA14000: 'TMSS_SEGA', 0xA130F1: 'SRAM_CTRL',
}


def hexs(v):
    if v < 0:
        return '-' + hexs(-v)
    return '%d' % v if v < 10 else '0x%X' % v


class Emitter:
    def __init__(self, A, names=None, cfg=None):
        self.A = A
        self.rom = A.rom
        self.n = A.n
        self.names = dict(names or {})      # addr -> name
        self.cfg = cfg
        self.labels = {}                     # addr -> name (all used ROM labels)
        self.ram = {}                        # 0xFFxxxx -> name
        self.raw_insns = set(getattr(cfg, 'RAW_INSNS', []))
        self.imm_ptr = set(getattr(cfg, 'IMM_PTR', []))
        self.imm_noptr = set(getattr(cfg, 'IMM_NOPTR', []))
        self.abs_noptr = set(getattr(cfg, 'ABS_NOPTR', []))
        self.ram_names = dict(getattr(cfg, 'RAM_NAMES', {}))
        self.cfuncs = {a: self.names.get(a, 'sub_%06X' % a) for a in getattr(cfg, 'C_FUNCS', {})}
        self.cfunc_abi = dict(getattr(cfg, 'C_FUNCS', {}))
        self.hooks = dict(getattr(cfg, 'MOD_HOOKS', {}))
        import csig
        self.csigs = csig.load()
        self.c_exports = list(getattr(cfg, 'C_EXPORTS', []))
        self.assets = {}
        mp = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'assets', 'manifest.json')
        if os.path.exists(mp):
            import json
            for m in json.load(open(mp)):
                self.assets[m['start']] = m

    # ----------------------------------------------------------- symbols
    def default_name(self, a):
        if a in self.names:
            return self.names[a]
        A = self.A
        if a == self.n:
            return 'ROM_End'
        if a in A.code:
            return ('sub_%06X' if a in A.funcs else 'loc_%06X') % a
        if a in A.jtables or A.labels.get(a) == 'jt':
            return 'jtbl_%06X' % a
        if A.owner[a] >= 0:
            return 'loc_%06X' % a     # inside an instruction
        return 'dat_%06X' % a

    def sym(self, a):
        """Symbolic expression for ROM address a (creates label)."""
        if a > self.n:
            return None
        name = self.default_name(a)
        self.labels[a] = name
        f = getattr(self, 'cur_file', None)
        if f is not None:
            self.refs.setdefault(a, set()).add(f)
        return name

    def ramsym(self, a24):
        name = self.ram_names.get(a24)
        if not name:
            name = 'ram_%04X' % (a24 & 0xFFFF)
        self.ram[a24] = name
        return name

    # ----------------------------------------------------------- operands
    def is_rom_ptr(self, v):
        return 0x200 <= v <= self.n and (v >> 24) == 0

    def imm_is_ptr(self, ins, op, idx):
        v = op.value
        if ins.addr in self.imm_noptr:
            return False
        if ins.addr in self.imm_ptr:
            return True
        if op.size != 'l' or not self.is_rom_ptr(v):
            return False
        dst = ins.ops[1] if len(ins.ops) > 1 else None
        m = ins.mnem
        A = self.A
        used = bool(A.rd[v] or A.ex[v]) or v in A.funcs or v in A.dptr or v == self.n
        used_cpu = bool((A.rd[v] & 0x17) or A.ex[v]) or v in A.funcs or v == self.n
        if v < 0x500 and v not in A.funcs:
            return False            # header / init area: small numbers, not pointers
        if v < 0x10000 and v % 0x20 == 0 and not (m == 'move.l' and dst is not None and dst.kind in ('absw', 'absl')):
            return False            # tile-aligned small value: VRAM address, not a code pointer
        if v < 0x24000 and v not in A.funcs:
            # into the code region: executed code label or CPU-read, non-tile-aligned data
            if v in A.code:
                if not A.ex[v]:
                    return False
            elif not (A.rd[v] & 0x17) or (v % 0x20 == 0 and v < 0x10000):
                return False
        if m.startswith(('movea', 'suba', 'adda', 'cmpa')):
            # address-register context
            return ((v & 0xFF) != 0 or used) and not (v & 1) and (v & 0xFFFF) != 0xFFFF
        if (v & 0xFF) == 0 and v >= 0x24000 and bool(A.rd[v]) and dst is not None and \
                dst.kind in ('ind', 'disp', 'postinc', 'index') and m == 'move.l':
            return True             # round, but stored to memory and pointing at used data
        if (v & 0xFF) == 0 or (v & 0xFFFF) == 0xFFFF or (v & 1):
            return False            # round numbers / masks / odd: fixed-point values, packed coords
        packed = (v >> 16) >= 4 and (v & 0xFFFF) < 0x100     # looks like two small words (x,y)
        if m == 'move.l' and dst is not None and dst.kind != 'dn' and not used_cpu and v >= 0x24000 and not packed:
            # stored pointer to an object we have not seen accessed: accept if it points
            # into a data object that code already references
            near = getattr(self, '_near', None)
            if near is None:
                import bisect
                self._near = near = sorted(set(A.coderefs) | set(t for (k, t, b) in A.dptr.values()))
            import bisect
            i = bisect.bisect_right(near, v) - 1
            return i >= 0 and v - near[i] < 0x100
        if m == 'move.l' and dst is not None:
            if v in A.code and v not in A.funcs and not A.labels.get(v):
                # into the middle of code: only a function / code label is plausible
                return A.ex[v] and dst.kind != 'dn'
            return used_cpu
        return False

    def fmt_imm(self, ins, op, idx, check):
        v = op.value
        if op.size == 'q':
            return '#%s' % hexs(v)
        if self.imm_is_ptr(ins, op, idx):
            if check:
                return '#0x%X' % v
            return '#' + self.sym(v)
        if op.size == 'b':
            return '#%s' % hexs(v) if v < 0 else '#0x%X' % v if v >= 10 else '#%d' % v
        if op.size == 'w':
            if ins.mnem == 'link':
                return '#%d' % (v - 0x10000 if v & 0x8000 else v)
            return '#0x%X' % v if v >= 10 else '#%d' % v
        return '#0x%X' % v if v >= 10 else '#%d' % v

    def areg_use(self, ins, reg):
        """How is address register reg (loaded by ins) used before being
        overwritten?  'deref' if it is ever used to access memory, 'call' if
        passed to a subroutine, 'value' if only its value is used, else None."""
        A = self.A
        a = ins.addr + ins.length
        seen_value = False
        for _ in range(24):
            j = A.code.get(a)
            if j is None:
                break
            overwritten = False
            for k, o in enumerate(j.ops):
                if o.reg == reg and o.kind in ('ind', 'postinc', 'predec', 'disp', 'index'):
                    return 'deref'
                if o.kind == 'index' and o.xreg == reg:
                    seen_value = True
                if o.kind == 'an' and o.reg == reg:
                    last = (k == len(j.ops) - 1)
                    if last and j.mnem.startswith(('adda', 'suba')):
                        continue             # pointer arithmetic keeps it a pointer
                    if not last and j.mnem.startswith(('movea', 'exg')) and j.ops[-1].kind == 'an':
                        return 'deref'       # copied into another address register
                    if last and j.mnem.startswith(('movea', 'lea', 'exg')):
                        overwritten = True
                    else:
                        seen_value = True
            if overwritten:
                break
            if j.flow == 'call' or j.mnem == 'jmp':
                return 'value' if seen_value else 'call'
            if j.mnem.startswith('bra') and j.targets:
                a = j.targets[0]          # follow unconditional branches
                continue
            if j.flow in ('jump', 'ret', 'stop'):
                break
            a += j.length
        return 'value' if seen_value else None

    def other_refs(self, addr, v):
        """Set containing v if some other instruction references v as an address operand."""
        refs = getattr(self, '_absrefs', None)
        if refs is None:
            refs = {}
            for a, i in self.A.code.items():
                for o in i.ops:
                    if o.kind in ('absl', 'absw', 'pcdisp', 'pcindex') and o.target is not None:
                        refs.setdefault(o.target, set()).add(a)
            self._absrefs = refs
        return {v} if refs.get(v, set()) - {addr} else set()

    def abs_is_ptr(self, ins, v):
        """Absolute operand v (< ROM size): symbolize?  lea of an absolute
        address is sometimes just a way to load a constant (e.g. a stride)."""
        A = self.A
        if ins.addr in self.abs_noptr:
            return False
        if ins.mnem == 'lea':
            use = self.areg_use(ins, ins.ops[1].reg)
            if use == 'value':
                return v >= 0x10000      # e.g. end-of-block label in a size computation
            if use in ('deref', 'call'):
                return True
            # unknown use: pointer if the target is code, read data, or referenced elsewhere
            return v in A.code or bool((A.rd[v:v + 16] & 0x17).any()) or v in self.other_refs(ins.addr, v)
        return True

    def fmt_abs(self, ins, op, check):
        v = op.value
        if op.kind == 'absw':
            if v & 0x80000000:
                a24 = v & 0xFFFFFF
                if a24 >= 0xFF0000:
                    return '(%s).w' % self.ramsym(a24)
                return '(0x%X).w' % v
            # low ROM address
            if v >= 0x200 and v < self.n and self.abs_is_ptr(ins, v):
                return '(%s).w' % ('0x%X' % v if check else self.sym(v))
            return '(0x%X).w' % v
        # abs.l
        if (v >> 24) == 0 and 0x200 <= v <= self.n and self.abs_is_ptr(ins, v):
            return '(%s).l' % ('0x%X' % v if check else self.sym(v))
        a24 = v & 0xFFFFFF
        if a24 >= 0xFF0000:
            s = self.ramsym(a24)
            if (v >> 24) == 0xFF:
                return '(%s).l' % s
            if (v >> 24) == 0:
                return '(%s&0xFFFFFF).l' % s
        if v in IO_NAMES:
            return '(%s).l' % IO_NAMES[v]
        return '(0x%X).l' % v

    def fmt_op(self, ins, op, idx, check=False):
        k = op.kind
        if k in ('dn', 'an'):
            return op.reg
        if k == 'ind':
            return '(%s)' % op.reg
        if k == 'postinc':
            return '(%s)+' % op.reg
        if k == 'predec':
            return '-(%s)' % op.reg
        if k == 'disp':
            return '(%s,%s)' % (hexs(op.disp), op.reg)
        if k == 'index':
            return '(%s,%s,%s.%s)' % (hexs(op.disp), op.reg, op.xreg, op.xsize)
        if k in ('absw', 'absl'):
            return self.fmt_abs(ins, op, check)
        if k == 'pcdisp':
            t = '.+%d' % (op.target - ins.addr) if check else self.sym(op.target)
            return '(%s,pc)' % t
        if k == 'pcindex':
            t = '.+%d' % (op.target - ins.addr) if check else self.sym(op.target)
            return '(%s,pc,%s.%s)' % (t, op.xreg, op.xsize)
        if k == 'imm':
            return self.fmt_imm(ins, op, idx, check)
        if k == 'branch':
            if check:
                return '.+%d' % (op.target - ins.addr)
            return self.sym(op.target)
        if k == 'reglist':
            return reglist_str(op.value, op.reg == 'predec')
        if k in ('sr', 'ccr', 'usp'):
            return k
        raise ValueError(k)

    def fmt_insn(self, ins, check=False):
        if not ins.ops:
            return ins.mnem
        return '%s\t%s' % (ins.mnem, ','.join(self.fmt_op(ins, o, i, check) for i, o in enumerate(ins.ops)))

    # raw fallback: opcode + extension words with symbolic parts
    def fmt_raw(self, ins, check=False):
        raw = ins.raw
        parts = ['.short\t0x%04X' % (raw[0] << 8 | raw[1])]
        pos = 2
        exts = sorted([o for o in ins.ops if o.ext is not None], key=lambda o: o.ext)
        for o in exts:
            while pos < o.ext:
                parts.append('.short\t0x%04X' % (raw[pos] << 8 | raw[pos + 1])); pos += 2
            sym_needed = False
            expr = None
            if o.kind in ('branch', 'pcdisp') and not check:
                expr = '.short\t%s-.' % self.sym(o.target)
            elif o.kind == 'pcindex' and not check:
                hi = raw[pos]
                expr = '.short\t0x%02X00|((%s-.)&0xFF)' % (hi, self.sym(o.target))
            elif o.kind in ('absw', 'absl'):
                txt = self.fmt_abs(ins, o, check)[1:-3]  # strip ( ).x
                expr = ('.short\t%s' if o.kind == 'absw' else '.long\t%s') % txt
            elif o.kind == 'imm' and o.size == 'l' and self.imm_is_ptr(ins, o, 0) and not check:
                expr = '.long\t%s' % self.sym(o.value)
            if expr:
                parts.append(expr)
            else:
                for k in range(0, o.extlen, 2):
                    parts.append('.short\t0x%04X' % (raw[pos + k] << 8 | raw[pos + k + 1]))
            pos += o.extlen
        while pos < len(raw):
            parts.append('.short\t0x%04X' % (raw[pos] << 8 | raw[pos + 1])); pos += 2
        return parts

    # ----------------------------------------------------------- validation
    def validate(self, gas='m68k-linux-gnu-as'):
        """Assemble every instruction in isolation (check mode) and record
        the ones GAS encodes differently -> raw_insns."""
        addrs = sorted(self.A.code)
        for a in addrs:
            self.fmt_insn(self.A.code[a], check=True)
        body = []
        for a in addrs:
            body.append('\t.balign 16,0xPAD')
            body.append('\t' + self.fmt_insn(self.A.code[a], check=True))
        pre = self.symbol_defs() + ['\t.text']
        self._pre_lines = len(pre)
        src = '\n'.join(pre + body) + '\n'
        outs = []
        for pad in ('0x00', '0xFF'):
            with tempfile.TemporaryDirectory() as td:
                s = os.path.join(td, 'v.s'); o = os.path.join(td, 'v.o'); b = os.path.join(td, 'v.bin')
                open(s, 'w').write(src.replace('0xPAD', pad).replace('0x%s' % 'PAD', pad))
                r = subprocess.run([gas, '-m68000', '--register-prefix-optional', '-o', o, s], capture_output=True, text=True)
                errs = {}
                for line in r.stderr.splitlines():
                    m = re.match(r'.*?:(\d+): (Error|Warning): (.*)', line)
                    if m:
                        errs[int(m.group(1))] = m.group(3)
                if r.returncode != 0 and not errs:
                    raise RuntimeError(r.stderr)
                if r.returncode != 0:
                    # drop erroring lines and retry so that others can be validated
                    bad_lines = set(errs)
                    ls = src.replace('0xPAD', pad).split('\n')
                    for ln in bad_lines:
                        ls[ln - 1] = '\t.short 0x4AFC' if ls[ln - 1].strip() and not ls[ln - 1].strip().startswith('.balign') else ls[ln - 1]
                    open(s, 'w').write('\n'.join(ls))
                    r = subprocess.run([gas, '-m68000', '--register-prefix-optional', '-o', o, s], capture_output=True, text=True)
                    if r.returncode:
                        raise RuntimeError(r.stderr[:2000])
                    self._err_lines = {(ln - self._pre_lines - 1) // 2: msg for ln, msg in errs.items()}
                else:
                    self._err_lines = {(ln - self._pre_lines - 1) // 2: msg for ln, msg in errs.items()}
                subprocess.run(['m68k-linux-gnu-objcopy', '-O', 'binary', '-j', '.text', o, b], check=True)
                outs.append(open(b, 'rb').read())
        bad = set()
        errs = getattr(self, '_err_lines', {})
        for i, a in enumerate(addrs):
            ins = self.A.code[a]
            s0 = outs[0][16 * i:16 * i + 16].ljust(16, b'\0')
            s1 = outs[1][16 * i:16 * i + 16].ljust(16, b'\xff')
            n = 0
            while n < 16 and s0[n] == s1[n]:
                n += 1
            if s0[:n] != ins.raw or i in errs:
                bad.add(a)
        self.raw_insns |= bad
        return bad

    def symbol_defs(self):
        inc = ['.ifndef NONMATCHING', '\t.set\tNONMATCHING, 0\t| 1 = use the C versions of functions (src/c/)', '.endif',
               '.ifndef MODS', '\t.set\tMODS, 0\t\t| 1 = enable the modifications marked .if MODS', '.endif',
               '.ifndef AUTOPLAY', '\t.set\tAUTOPLAY, 0\t| 1 = scripted input from autoplay.bin (tools/autoplay.py)', '.endif',
               '.ifndef TEXTMODS', '\t.set\tTEXTMODS, 0\t| 1 = small visible text edits that move high ROM (relocation test)', '.endif',
               '.ifndef TESTHW', '\t.set\tTESTHW, 0\t| 1 = 480x464 build runs on stock emulators (logic tests)', '.endif', '']
        for v, nm in sorted(IO_NAMES.items()):
            inc.append('\t.set\t%s, 0x%X' % (nm, v))
        inc.append('')
        for a24, nm in sorted(self.ram.items()):
            inc.append('\t.set\t%s, 0x%08X' % (nm, 0xFF000000 | a24))
        return inc

    # ----------------------------------------------------------- emission
    def breaks(self):
        A = self.A
        b = set(self.labels) | set(A.code) | set(A.dptr) | set(self.splits_at)
        return sorted(x for x in b if x <= self.n)

    def emit_range(self, s, e, out, bindir, relbin):
        """Emit ROM range [s,e) into list of lines."""
        A = self.A
        brks = [x for x in self._brks if s < x < e] + [e]
        import bisect
        a = s
        while a < e:
            if getattr(self, '_in_cfunc', False) and (a not in A.code or a in A.funcs):
                out.append('.endif')
                self._in_cfunc = False
            # labels
            if a in self.labels:
                out.append('%s:' % self.labels[a])
            if a in A.code and a in self.cfuncs:
                out.extend(self.cfunc_stub(a))
                out.append('.else')
                self._in_cfunc = True
            elif getattr(self, '_in_cfunc', False) and (a not in A.code or a in A.funcs):
                out.append('.endif')
                self._in_cfunc = False
            if a in A.code and a in self.hooks:
                self.emit_hook_start(a, out)
            if a in A.code:
                ins = A.code[a]
                for k in range(1, ins.length):
                    if a + k in self.labels:
                        out.append('\t%s = . + %d' % (self.labels[a + k], k))
                if a in self.raw_insns:
                    parts = self.fmt_raw(ins)
                    out.append('\t%s\t| %s' % ('; '.join(parts), self.fmt_insn(ins).replace('\t', ' ')))
                else:
                    out.append('\t' + self.fmt_insn(ins))
                a += ins.length
                if a == getattr(self, '_hook_end', None):
                    out.append('.endif')
                    self._hook_end = None
                continue
            if getattr(self, '_in_cfunc', False) and a not in A.code:
                out.append('.endif')
                self._in_cfunc = False
            if a in self.assets:
                m = self.assets[a]
                out.append('\t.incbin\t"build/assets/%s.bin"\t| %s: %s' % (m['name'], m['kind'], m.get('file', m.get('header', ''))))
                base = self.labels.get(a)
                inner = sorted(x for x in self.labels if a < x < m['end'])
                for x in inner:
                    out.append('\t%s = %s + 0x%X' % (self.labels[x], base, x - a))
                a = m['end']
                continue
            if a in A.dptr:
                kind, t, base = A.dptr[a]
                if kind == 'L':
                    out.append('\t.long\t%s' % self.sym(t)); a += 4
                elif kind == 'A':
                    out.append('\t.long\t%s+0x%08X' % (self.sym(t), base)); a += 4
                elif kind == 'W':
                    out.append('\t.short\t%s' % self.sym(t)); a += 2
                elif kind == 'R':
                    out.append('\t.short\t%s-%s' % (self.sym(t), self.sym(base))); a += 2
                elif kind == 'R8':
                    out.append('\t.byte\t%s-%s' % (self.sym(t), self.sym(base))); a += 1
                continue
            i = bisect.bisect_right(brks, a)
            nxt = brks[i] if i < len(brks) else e
            nxt = min(nxt, e)
            if nxt - a >= 1024:
                fn = '%06X.bin' % a
                open(os.path.join(bindir, fn), 'wb').write(self.rom[a:nxt])
                out.append('\t.incbin\t"%s/%s"' % (relbin, fn))
            else:
                out.extend(self.data_lines(a, nxt, None))
            a = nxt
        if getattr(self, '_in_cfunc', False):
            out.append('.endif')
            self._in_cfunc = False
        return out

    def cfunc_len(self, a):
        """Byte length of the routine at a (up to the next function)."""
        import bisect
        funcs = sorted(self.A.funcs)
        k = bisect.bisect_right(funcs, a)
        end = funcs[k] if k < len(funcs) else self.n
        b = a
        while b < end and b in self.A.code:
            b += self.A.code[b].length
        return b - a

    def cfunc_stub(self, a):
        """NONMATCHING body of a C-replaced routine.  It keeps the original
        size (jmp + nop padding) so nothing else in ROM moves: the game has
        layout-dependent reads in low ROM.  The jmp goes to a stub placed with
        the C code that
          - saves the registers the original leaves intact (C_FUNCS), and
          - repacks the stack arguments: the original passes words / longs
            (16-bit int), the C code takes a 4-byte slot per argument."""
        name = self.cfuncs[a]
        _, save = self.cfunc_abi[a]
        sig = self.csigs.get(('C_IMPL', name))
        if sig is None:
            raise ValueError('C_FUNCS %06X: no C prototype with C_IMPL(%s)' % (a, name))
        ret, args = sig
        # preserve every scratch register except the results (d0, and a0 for
        # pointers): hand-written callers rely on registers the original
        # leaves alone, and never on what it leaves behind in d1-d2/a1
        save = 'd1-d2/a1' if ret == 'p' else 'd1-d2/a0-a1'
        size = self.cfunc_len(a)
        direct = False
        target = '%s_c' % name if direct else '%s_stub' % name
        out = ['.if NONMATCHING\t| replaced by the C version in src/c/',
               '\tjmp\t(%s).l' % target,
               '\t.rept\t%d\t\t| keep the original size' % ((size - 6) // 2),
               '\tnop',
               '\t.endr']
        if not direct:
            nsave = 0
            for part in (save.split('/') if save else []):
                r = part.split('-')
                nsave += 4 * (int(r[-1][1]) - int(r[0][1]) + 1)
            out += ['\t.pushsection .text.cstubs,"ax"\t| linked after the C code',
                    '%s_stub:\t\t| args %s%s' % (name, ''.join(args) or '-',
                                                   (', ' + save + ' preserved') if save else '')]
            if save:
                out.append('\tmovem.l\t%s,-(sp)' % save)
            for r in getattr(self.cfg, 'C_REGIN', {}).get(a, []):
                out.append('\tmove.l\t%s,(g_cRegIn).l\t| the C version needs the caller\'s %s' % (r, r))
            offs, o = [], 4
            for x in args:
                offs.append(o)
                o += 2 if x == 'w' else 4
            pushed = 0
            for x, off in reversed(list(zip(args, offs))):
                src = off + nsave + pushed
                if x == 'w':
                    out += ['\tmove.w\t(%d,sp),-(sp)' % src, '\tsubq.l\t#2,sp']
                else:
                    out.append('\tmove.l\t(%d,sp),-(sp)' % src)
                pushed += 4
            out.append('\tjsr\t(%s_c).l' % name)
            if pushed:
                out.append('\tlea\t(%d,sp),sp' % pushed)
            if save:
                out.append('\tmovem.l\t(sp)+,%s' % save)
            for r in getattr(self.cfg, 'C_REGOUT', {}).get(a, []):
                reg, sz = r.split('.')
                out.append('\tmove.%s\t(g_cRegOut%s).l,%s\t| result some callers take from %s'
                           % (sz, '+2' if sz == 'w' else '', reg, reg))
            out += ['\trts', '\t.popsection']
        assert size >= 6 and size % 2 == 0, name
        return out

    def c_thunk(self, label, sig):
        """<label>_asm for C: repack 4-byte C argument slots into the
        original words / longs; keep every register C expects preserved."""
        ret, args = sig
        out = ['\t.globl\t%s_asm' % label, '%s_asm:\t\t| C -> original, args %s' % (label, ''.join(args) or '-'),
               '\tmovem.l\td3-d7/a2-a6,-(sp)']
        pushed = 0
        for i in reversed(range(len(args))):
            slot = 4 + 40 + 4 * i + pushed          # 10 saved registers
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

    def emit_hook_start(self, a, out):
        """MOD_HOOKS: overwrite [a, a+size) with same-size code (usually a jmp
        or jsr to a trampoline linked with the C code).  Nothing else in ROM
        moves - low ROM is layout-sensitive."""
        h = self.hooks[a]
        size = h['size']
        inner = [x for x in self.labels if a < x < a + size]
        if inner:
            raise ValueError('MOD_HOOKS %06X: label inside the overwritten range' % a)
        b = a
        while b < a + size:
            b += self.A.code[b].length
        if b != a + size:
            raise ValueError('MOD_HOOKS %06X: size %d does not end on an instruction' % (a, size))
        out.append('.if %s\t| hook: %s' % (h.get('flag', 'MODS'), h.get('what', '')))
        tag = h.get('label', '%06X' % a)
        out.append('.Lhook_%s:' % tag)
        out += h['code']
        out += ['\t.if (. - .Lhook_%s) - %d' % (tag, size), '\t.error "hook %s must be %d bytes"' % (tag, size), '\t.endif']
        if h.get('tramp'):
            out.append('\t.pushsection .text.cstubs,"ax"')
            out += h['tramp']
            out.append('\t.popsection')
        out.append('.else')
        self._hook_end = a + size

    def apply_mods(self, bodies):
        """Wrap the lines named in config MOD_PATCHES in .if TEXTMODS/.else/.endif.
        Each original line must occur exactly once in the whole ROM."""
        for orig, repl in getattr(self.cfg, 'MOD_PATCHES', []):
            hits = [(out, i) for _, _, _, out in bodies for i, l in enumerate(out) if l == orig]
            if len(hits) != 1:
                raise ValueError('MOD_PATCHES: %r matches %d lines' % (orig, len(hits)))
            out, i = hits[0]
            out[i:i + 1] = ['.if TEXTMODS\t| visible test modification (moves high ROM)'] + repl + ['.else', orig, '.endif']

    def check_cfuncs(self):
        """C-replaced functions: nothing outside may reference labels inside
        their instruction range (other than the entry point)."""
        A = self.A
        funcs = sorted(A.funcs)
        import bisect
        for a in list(self.cfuncs):
            i = bisect.bisect_right(funcs, a)
            end = funcs[i] if i < len(funcs) else a + 2
            b = a
            while b < end and b in A.code:
                b += A.code[b].length
            inner = set(range(a + 1, b))
            for x, ins in A.code.items():
                if a <= x < b:
                    continue
                for o in ins.ops:
                    t = o.target if o.kind in ('branch', 'pcdisp', 'pcindex', 'absw', 'absl') else None
                    if t in inner:
                        raise ValueError('C function %s: label %06X referenced from %06X' % (self.cfuncs[a], t, x))

    def emit_all(self, outdir, splits, bindir_name='bin'):
        """splits: list of (start, name). Produces outdir/<name>.s files,
        outdir/rom.ld and returns list of file names in order."""
        A = self.A
        self.splits_at = [s for s, _ in splits]
        # pass 1: register all labels by formatting everything
        for a, ins in A.code.items():
            self.fmt_insn(ins)
            if a in self.raw_insns:
                self.fmt_raw(ins)
        for a, (kind, t, base) in A.dptr.items():
            self.sym(t)
            if kind in ('R', 'R8'):
                self.sym(base)
        for a in list(A.funcs):
            if a in A.code:
                self.sym(a)
        for a in list(A.jtables):
            self.sym(a)
        for a in getattr(self.cfg, 'FORCE_LABELS', []):
            self.sym(a)
        for a, m in self.assets.items():
            self.names.setdefault(a, m['name'])
            self.sym(a)
        # a label inside a data pointer means the 'pointer' was a false positive
        sizes = {'L': 4, 'A': 4, 'W': 2, 'R': 2, 'R8': 1}
        for a in sorted(A.dptr):
            kind = A.dptr[a][0]
            if any((a + k) in self.labels for k in range(1, sizes[kind])):
                A.notes.append('dropped dptr at %06X (label inside)' % a)
                del A.dptr[a]
        self._brks = self.breaks()
        os.makedirs(outdir, exist_ok=True)
        bindir = os.path.join(outdir, bindir_name)
        os.makedirs(bindir, exist_ok=True)
        files = []
        bounds = [s for s, _ in splits] + [self.n]
        self.refs = {}
        bodies = []
        for (s, name), e in zip(splits, bounds[1:]):
            self.cur_file = name
            out = []
            self.emit_range(s, e, out, bindir, bindir_name)
            if e == self.n and self.n in self.labels:
                out.append('%s:' % self.labels[self.n])
            bodies.append((s, e, name, out))
        self.cur_file = None
        self.apply_mods(bodies)
        for s, e, name, out in bodies:
            hdr = ['| %s: ROM 0x%06X-0x%06X' % (name, s, e), '']
            open(os.path.join(outdir, name + '.s'), 'w').write('\n'.join(hdr + out) + '\n')
            files.append(name)
        main = ['| Dune II: The Battle for Arrakis (Genesis) - "Full Version R82c" rebuild',
                '| Master assembly file: all modules are assembled as one unit (in ROM order)',
                '| so labels need no .globl; C code reaches assembly through c_interface.inc.',
                '', '\t.include\t"symbols.inc"', '\t.text', '']
        for f in files:
            main.append('\t.include\t"%s.s"' % f)
        main += ['', '\t.include\t"c_interface.inc"']
        open(os.path.join(outdir, 'main.s'), 'w').write('\n'.join(main) + '\n')
        ci = ['| Symbols shared with the C code (src/c/).  Assembly labels are local to',
              '| main.s, so C sees them through global aliases named <label>_asm; RAM and',
              '| hardware symbols are absolute and exported as-is.', '']
        for a in self.c_exports:
            nm = self.names.get(a) or self.labels.get(a) or self.default_name(a)
            sig = self.csigs.get(('ASM', nm))
            if sig is not None and a in self.A.code:
                ci += ['.if NONMATCHING\t| code: only in builds with C'] + self.c_thunk(nm, sig) + ['.endif']
            else:
                ci += ['\t.globl\t%s_asm' % nm, '\t%s_asm = %s' % (nm, nm)]
        ci.append('')
        for a24, nm in sorted(self.ram.items()):
            if not nm.startswith('ram_'):
                ci.append('\t.globl\t%s' % nm)
        open(os.path.join(outdir, 'c_interface.inc'), 'w').write('\n'.join(ci) + '\n')
        # symbols include
        inc = ['| RAM and hardware symbols', ''] + self.symbol_defs()
        open(os.path.join(outdir, 'symbols.inc'), 'w').write('\n'.join(inc) + '\n')
        return files

    # ----------------------------------------------------------- data
    def data_lines(self, s, e, breaks):
        """Emit raw data bytes s..e (no pointers inside)."""
        out = []
        rom = self.rom
        a = s
        while a < e:
            # ascii string?
            j = a
            while j < e and (32 <= rom[j] < 127) and rom[j] != 0x22 and rom[j] != 0x5C:
                j += 1
            if j - a >= 4:
                if j < e and rom[j] == 0:
                    out.append('\t.asciz\t"%s"' % rom[a:j].decode('ascii'))
                    a = j + 1
                else:
                    out.append('\t.ascii\t"%s"' % rom[a:j].decode('ascii'))
                    a = j
                continue
            j = a + 1
            # up to 16 bytes, stop before a string start
            while j < e and j - a < 16:
                k = j
                while k < e and 32 <= rom[k] < 127 and rom[k] not in (0x22, 0x5C) and k - j < 5:
                    k += 1
                if k - j >= 5:
                    break
                j += 1
            out.append('\t.byte\t' + ','.join('0x%02X' % x for x in rom[a:j]))
            a = j
        return out
