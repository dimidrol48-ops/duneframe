"""Code/data separation for the Dune II Genesis ROM.

Inputs:  baserom, merged emulator traces (exec + read flags), optional
         config (config.py: forced code/data, manual pointers, names).
Output:  an Analysis object used by emit.py.
"""
import struct
import numpy as np
from m68k import Decoder, Invalid, Instr

# trace read flags (see tools/emu/gpgx_trace.patch)
RD_B, RD_W, RD_L, RD_LPTR, RD_PC, RD_DMA, RD_Z80, RD_TPTR = 1, 2, 4, 8, 16, 32, 64, 128


class Analysis:
    def __init__(self, rom, ex=None, rd=None, cfg=None, who=None, rc=None, rr=None):
        self.rom = rom
        self.n = len(rom)
        self.D = Decoder(rom)
        self.ex = ex if ex is not None else np.zeros(0x400000, np.uint8)
        self.rd = rd if rd is not None else np.zeros(0x400000, np.uint8)
        self.cfg = cfg
        self.who = who
        self.rc = rc
        self.rr = rr
        self.code = {}                       # addr -> Instr
        self.owner = np.full(self.n + 16, -1, np.int64)   # byte -> instruction start
        self.dptr = {}                       # addr -> (kind, target, base)  kind: L, W, R (rel word), A (24-bit addr in long)
        self.forced_data = np.zeros(self.n + 16, bool)
        self.funcs = set()                   # function entry points
        self.jtables = {}                    # table addr -> (kind, count)
        self.labels = {}                     # addr -> kind hint
        self.notes = []
        self.code_ranges = [(0x200, 0x24000), (0x1b0000, 0x1c0000)]
        if cfg:
            for s, e in getattr(cfg, 'DATA_RANGES', []):
                self.forced_data[s:e] = True

    # ------------------------------------------------------------ helpers
    def u16(self, a):
        return (self.rom[a] << 8) | self.rom[a + 1]

    def u32(self, a):
        return struct.unpack_from('>I', self.rom, a)[0]

    def in_code_range(self, a):
        return any(s <= a < e for s, e in self.code_ranges)

    def is_insn_start(self, a):
        return a in self.code

    # ------------------------------------------------------------ discovery
    def trial(self, seeds, trusted=False):
        """Decode everything reachable from seeds.  Returns dict of new
        instructions, list of (tableaddr, kind, count, targets), or None if
        a speculative walk hits invalid code / conflicts."""
        new = {}
        tables = []
        work = list(seeds)
        owner_local = {}

        def conflict(a, ln):
            for k in range(ln):
                o = self.owner[a + k] if a + k < self.n else -2
                if o not in (-1, a):
                    return True
                ol = owner_local.get(a + k)
                if ol is not None and ol != a:
                    return True
                if self.forced_data[a + k]:
                    return True
            return False

        while work:
            a = work.pop()
            while True:
                if a in self.code or a in new:
                    break
                if a >= self.n or a & 1 or a < 0x200:
                    if trusted:
                        self.notes.append('trusted walk left rom at %06X' % a)
                        break
                    return None
                try:
                    ins = self.D.decode(a)
                except Invalid as e:
                    if trusted:
                        self.notes.append('invalid at %06X (%s)' % (a, e))
                        break
                    return None
                if conflict(a, ins.length):
                    if trusted:
                        self.notes.append('conflict at %06X' % a)
                        break
                    return None
                new[a] = ins
                for k in range(ins.length):
                    owner_local[a + k] = a
                for t in ins.targets:
                    if t < self.n:
                        work.append(t)
                    elif not trusted:
                        return None
                # jump tables
                if ins.mnem == 'jmp' and ins.ops[0].kind == 'pcindex':
                    tt = self.jump_table(ins, new)
                    if tt:
                        tables.append(tt)
                        for t in tt[3]:
                            work.append(t)
                if ins.mnem in ('jmp', 'jsr') and ins.ops[0].kind == 'ind':
                    tt = self.ptr_table_before(ins, new)
                    if tt:
                        tables.append(tt)
                        for t in tt[3]:
                            work.append(t)
                if ins.flow in ('jump', 'ret', 'stop'):
                    break
                a += ins.length
        return new, tables

    def prev_insns(self, addr, new, n):
        out = []
        a = addr
        for _ in range(n):
            # find instruction ending at a
            found = None
            for ln in (2, 4, 6, 8, 10):
                p = a - ln
                i = new.get(p) or self.code.get(p)
                if i is not None and i.length == ln:
                    found = i
                    break
            if not found:
                break
            out.append(found)
            a = found.addr
        return out

    def jump_table(self, jins, new):
        op = jins.ops[0]
        T = op.target
        prev = self.prev_insns(jins.addr, new, 8)
        if prev and prev[0].mnem == 'move.w' and prev[0].ops[0].kind == 'pcindex' and prev[0].ops[0].target == T:
            # GCC switch: table of s16 offsets relative to T
            count = None
            for p in prev[1:]:
                if p.mnem.startswith('cmpi.') and p.ops[1].kind == 'dn':
                    count = (p.ops[0].value & (0xFFFF if p.mnem.endswith('w') else 0xFFFFFFFF)) + 1
                    break
            targets = []
            k = 0
            lim = count if count else 4096
            minT = 1 << 30
            while k < lim:
                ea = T + 2 * k
                if not count and ea >= minT:
                    break
                if ea in self.code or ea in new:
                    break
                w = self.u16(ea)
                t = (T + (w - 0x10000 if w & 0x8000 else w)) & 0xFFFFFF
                if t & 1 or t >= self.n:
                    break
                targets.append(t)
                minT = min(minT, t) if t > T else minT
                k += 1
            return (T, 'R', len(targets), targets)
        # table of branch instructions right after jmp
        if T == jins.addr + 4 or (op.disp == 2 and T == jins.addr + 4):
            targets = []
            a = jins.addr + 4
            while a < self.n:
                try:
                    i = self.D.decode(a)
                except Invalid:
                    break
                if i.mnem.startswith('bra') or i.mnem == 'jmp' or i.mnem == 'rts' or i.mnem.startswith('moveq') or i.mnem == 'nop':
                    targets.append(a)
                    a += i.length
                    if not (i.mnem.startswith('bra') or i.mnem == 'jmp'):
                        break
                else:
                    break
            if targets:
                return (T, 'B', len(targets), targets)
        return None

    def ptr_table_before(self, jins, new):
        """movea.l (T,pc,Xn),An ; jmp/jsr (An)  or movea.w (word abs table)."""
        prev = self.prev_insns(jins.addr, new, 3)
        reg = jins.ops[0].reg
        for p in prev:
            if p.mnem in ('movea.l', 'movea.w') and p.ops[1].reg == reg and p.ops[0].kind == 'pcindex':
                T = p.ops[0].target
                kind = 'L' if p.mnem == 'movea.l' else 'W'
                targets = []
                a = T
                minT = 1 << 30
                while a < minT and a not in self.code and a not in new:
                    v = self.u32(a) if kind == 'L' else self.u16(a)
                    if kind == 'W' and v & 0x8000:
                        break
                    if v & 1 or v >= self.n or v < 0x200:
                        break
                    targets.append(v)
                    if v > T:
                        minT = min(minT, v)
                    a += 4 if kind == 'L' else 2
                if targets:
                    return (T, kind, len(targets), targets)
            if p.ops and len(p.ops) > 1 and p.ops[-1].kind == 'an' and p.ops[-1].reg == reg:
                break
        return None

    def commit(self, res):
        new, tables = res
        for a, ins in new.items():
            self.code[a] = ins
            self.owner[a:a + ins.length] = a
        for T, kind, count, targets in tables:
            if kind == 'B':
                self.labels.setdefault(T, 'jt')
                continue
            self.jtables[T] = (kind, count)
            self.labels.setdefault(T, 'jt')
            step = {'R': 2, 'W': 2, 'L': 4}[kind]
            for k, t in enumerate(targets):
                ea = T + step * k
                self.dptr[ea] = (kind, t, T)
                self.forced_data[ea:ea + step] = True

    def discover(self, extra_seeds=()):
        vec = struct.unpack('>64I', self.rom[:256])
        seeds = set(v & 0xFFFFFF for v in vec[1:])
        self.vectors = vec
        seeds |= set(int(x) for x in np.nonzero(self.ex[:self.n])[0])
        seeds |= set(extra_seeds)
        if self.cfg:
            seeds |= set(getattr(self.cfg, 'CODE_SEEDS', []))
        for s in list(seeds):
            self.funcs.add(s) if s in [v & 0xFFFFFF for v in vec[1:]] else None
        res = self.trial(sorted(seeds), trusted=True)
        self.commit(res)
        self.table_pass(trusted=True)
        self._collect_funcs()

    def table_pass(self, trusted):
        """Detect jump/pointer tables for all indirect jumps (needs the
        preceding instructions to be decoded, hence a separate pass)."""
        done = getattr(self, '_tables_done', set())
        self._tables_done = done
        changed = True
        while changed:
            changed = False
            for a in sorted(self.code):
                if a in done:
                    continue
                ins = self.code[a]
                tt = None
                if ins.mnem == 'jmp' and ins.ops[0].kind == 'pcindex':
                    tt = self.jump_table(ins, {})
                elif ins.mnem in ('jmp', 'jsr') and ins.ops[0].kind == 'ind':
                    tt = self.ptr_table_before(ins, {})
                else:
                    continue
                done.add(a)
                if not tt:
                    continue
                self.commit(({}, [tt]))
                res = self.trial(tt[3], trusted=trusted)
                if res:
                    self.commit(res)
                changed = True

    def _collect_funcs(self):
        for a, ins in self.code.items():
            if ins.flow == 'call':
                for t in ins.targets:
                    self.funcs.add(t)

    def speculative_pointers(self):
        """Scan non-code longwords that point into code range; accept those
        whose target decodes as a clean function."""
        added = 0
        for a in range(0, self.n - 3, 2):
            if self.owner[a] != -1 or self.owner[a + 2] != -1:
                continue
            v = self.u32(a)
            if v & 1 or not self.in_code_range(v) or v in self.code:
                continue
            if self.rd[a] & (RD_DMA | RD_Z80):
                continue
            res = self.trial([v])
            if res and res[0]:
                # require it to look like a function: ends in rts/jmp etc (trial ok means all paths end properly)
                self.commit(res)
                self.funcs.add(v)
                added += 1
        return added

    def data_region(self, a, ln):
        for k in range(ln):
            if self.owner[a + k] != -1:
                return False
        return True

    def reader_class(self, pc):
        i = self.code.get(int(pc))
        if i is None:
            return 'nocode'
        m = i.mnem
        d = i.ops[-1] if i.ops else None
        if m.startswith('movea') or (d is not None and d.kind == 'an' and m.startswith('move')):
            return 'an'
        if m.startswith('move') and d is not None and d.kind == 'dn':
            # data register: pointer if moved into an address register soon after
            reg = d.reg
            a = i.addr + i.length
            for _ in range(10):
                j = self.code.get(a)
                if j is None:
                    break
                if j.mnem in ('movea.l', 'move.l') and j.ops[0].kind == 'dn' and j.ops[0].reg == reg and j.ops[1].kind == 'an':
                    return 'dn-an'
                if j.ops and j.ops[-1].kind == 'dn' and j.ops[-1].reg == reg:
                    break
                if j.flow in ('jump', 'ret', 'call'):
                    break
                a += j.length
            return 'dn'
        if m.startswith('move') and d is not None and d.kind == 'predec' and d.reg == 'sp':
            return 'push'
        if m.startswith('movem'):
            return 'movem'
        if m.startswith('move'):
            return 'copy'
        return 'arith'

    def pcrel_ptr_tables(self):
        """movea.l (T,pc,Xn),An / move.l (T,pc,Xn),An : T is a table of long pointers."""
        for ins in list(self.code.values()):
            if len(ins.ops) != 2 or ins.ops[1].kind not in ('an', 'dn') or not ins.mnem.startswith(('move.l', 'movea.l')):
                continue
            src = ins.ops[0]
            if src.kind not in ('pcindex',):
                continue
            a = src.target
            if ins.ops[1].kind == 'dn':
                # data register: only if every entry is an even pointer to CPU-read data
                ok, b = True, a
                while b + 4 <= self.n and self.data_region(b, 4) and not (b != a and b in self.coderefs):
                    v = self.u32(b)
                    if not (0x200 <= v <= self.n) or (v & 1) or not (self.rd[v:v + 64] & 0x17).any():
                        ok = b > a
                        break
                    b += 4
                if not ok:
                    continue
            while a + 4 <= self.n and self.data_region(a, 4) and a not in self.dptr:
                v = self.u32(a) & 0xFFFFFF
                if not (0x200 <= v <= self.n) or (self.u32(a) >> 24) or (v & 1):
                    break
                if ins.ops[1].kind == 'dn' and not (self.rd[v:v + 64] & 0x17).any():
                    break
                if a != src.target and (a in self.coderefs):
                    break
                self.dptr[a] = ('L', v, 0)
                a += 4

    def find_data_pointers(self):
        """Find 32-bit ROM pointers stored in data."""
        cfg = self.cfg
        # vectors: high byte used as exception number tag
        for i in range(1, 64):
            v = self.vectors[i]
            self.dptr[i * 4] = ('A', v & 0xFFFFFF, v & 0xFF000000)
        no = set(getattr(cfg, 'NOT_PTRS', []))
        forced = dict(getattr(cfg, 'DATA_PTRS', {}))   # addr -> kind
        excl = list(getattr(cfg, 'NO_PTR_SCAN', []))
        cand = {}
        tagged = {}
        for a in range(0x100, self.n - 3, 2):
            if a in self.dptr or (a + 2) in self.dptr:
                continue
            if not self.data_region(a, 4):
                continue
            v = self.u32(a)
            tag = v & 0xFF000000
            if tag:
                # tagged pointer (type byte + 24-bit address): only with trace evidence
                if not (self.rd[a] & RD_TPTR):
                    continue
                v &= 0xFFFFFF
            if v < 0x200 or v > self.n:
                continue
            if tag:
                tagged[a] = tag
            if any(s <= a < e for s, e in excl):
                continue
            if self.rd[a] & (RD_DMA | RD_Z80):
                continue
            cand[a] = v
        # code-referenced ROM addresses
        coderefs = set()
        for ins in self.code.values():
            for o in ins.ops:
                if o.kind in ('pcdisp', 'pcindex') or (o.kind in ('absl', 'absw') and o.target < self.n):
                    coderefs.add(o.target)
                elif o.kind == 'imm' and o.size == 'l' and 0x200 <= o.value < self.n:
                    coderefs.add(o.value)
        self.coderefs = coderefs
        ev = {}
        strong = {}
        self.reader_stats = {}
        for a, v in cand.items():
            r = int(self.rd[a])
            st = bool(r & (RD_LPTR | RD_TPTR))
            if st and self.rc is not None:
                rcl = int(self.rc[a])
                cls = set(self.reader_class(self.who[x >> 1]) for x in (a, a + 2) if self.who[x >> 1])
                target_used = bool(self.rd[v] or self.ex[v] or v in self.code)
                packed = (v >> 16) >= 4 and (v & 0xFFFF) < 0x100      # (w,h) / (x,y) word pair
                plausible = target_used and (v & 0xFF) != 0 and not (v & 1) and not packed
                if rcl & 1 or 'an' in cls or 'dn-an' in cls:
                    st = True
                elif rcl & 2:
                    st = target_used and ((v & 0xFF) != 0 or bool(self.rd[v]))
                elif rcl & 4:
                    if r & RD_TPTR:
                        # tagged value into a data register: needs proof of pointer use
                        rr = int(self.rr[a]) if self.rr is not None else 0
                        st = bool(rr & 1) or 'dn-an' in set(self.reader_class(self.who[x >> 1]) for x in (a, a + 2) if self.who[x >> 1])
                    else:
                        st = plausible
                else:
                    # copied to RAM: use how the RAM copy was used later (taint trace)
                    rr = int(self.rr[a]) if self.rr is not None else 0
                    if rr & 1:
                        st = True
                    elif rr & 2:
                        st = target_used and ((v & 0xFF) != 0 or bool(self.rd[v])) and not packed
                    elif rr & 4:
                        st = plausible
                    else:
                        st = False
                    rcl |= rr << 4
                cls = {('rc%d' % rcl)}
                for c in cls:
                    self.reader_stats[c] = self.reader_stats.get(c, 0) + 1
                if not st:
                    ev[a] = -9
                    strong[a] = False
                    continue
            strong[a] = st
            if not st and (r & (RD_B | RD_W | RD_L)):
                ev[a] = -9          # CPU read it, but not as a pointer
                continue
            e = 0
            if v in self.funcs:
                e += 2
            elif v in self.code:
                e += 1
            if v in coderefs:
                e += 2
            if self.rd[v] & (RD_B | RD_W | RD_L | RD_PC):
                e += 1
            if (v & 0xFF) == 0:
                e -= 2
            if v & 1:
                e -= 2
            ev[a] = e
        acc = {}
        for a, v in cand.items():
            if a in no or a < 0x200:
                continue
            if strong[a]:
                acc[a] = v
                continue
            e = ev[a]
            nb = sum(1 for d in (-12, -8, -4, 4, 8, 12) if strong.get(a + d) or ev.get(a + d, -9) >= 3)
            if (e >= 3 and nb >= 1) or a in forced:
                acc[a] = v
        # pointers into the code region must hit a function, an executed code label,
        # or CPU-read data that is not tile-aligned (VRAM addresses look like that)
        for a in list(acc):
            v = acc[a]
            if v < 0x24000 and a not in forced:
                if v < 0x10000 and v % 0x20 == 0 and not (self.rc is not None and self.rc[a] & 1):
                    del acc[a]
                    continue
                if v in self.funcs:
                    continue
                if v in self.code:
                    if not self.ex[v]:
                        del acc[a]
                    continue
                if not (self.rd[v] & 0x17):
                    del acc[a]
        # avoid overlaps (prefer earlier)
        last = -10
        for a in sorted(acc):
            if a < last + 4:
                continue
            if a in tagged:
                self.dptr[a] = ('A', acc[a], tagged[a])
            elif a in self.dptr:
                continue
            else:
                self.dptr[a] = ('L', acc[a], 0)
            last = a
        for a, kind in forced.items():
            if kind == 'L':
                self.dptr[a] = ('L', self.u32(a), 0)
        return len(acc)

    def fill_gaps(self):
        """Try to decode gaps inside code ranges that follow an unconditional
        flow change (typical for unreferenced / pointer-only functions)."""
        added = 0
        changed = True
        while changed:
            changed = False
            for s, e in self.code_ranges:
                a = s
                while a < min(e, self.n):
                    if self.owner[a] == -1 and not self.forced_data[a]:
                        # gap start: previous instruction must end flow
                        p = self.owner[a - 2] if a >= 2 else -1
                        prev = self.code.get(int(p)) if p >= 0 else None
                        if prev is not None and prev.addr + prev.length == a and prev.flow in ('jump', 'ret', 'stop'):
                            # skip if gap was read as data by CPU
                            g_end = a
                            while g_end < self.n and self.owner[g_end] == -1:
                                g_end += 1
                            datareads = (self.rd[a:g_end] & (RD_B | RD_W | RD_L | RD_PC | RD_DMA | RD_Z80)).any()
                            if not datareads:
                                res = self.trial([a])
                                if res and res[0]:
                                    self.commit(res)
                                    self.funcs.add(a)
                                    added += 1
                                    changed = True
                            a = g_end
                            continue
                    a += 2
        return added
