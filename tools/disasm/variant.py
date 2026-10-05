#!/usr/bin/env python3
"""Fold a variant ROM (another build of the same source, e.g. the 480x464
"wide" ROM) into the sources as .if <FLAG> blocks.

  1. align the variant with the base: functions are matched by masked byte
     patterns (tools/variant_align.py), the regions between them by an
     instruction-level diff -> a byte address map base <-> variant
  2. map the base's emulator traces through it and disassemble the variant
     with the same analysis; every label is named after its *base* address,
     so unchanged code emits identical text
  3. diff the two generated trees module by module and merge them:
     differences become  .if FLAG / variant / .else / base / .endif

usage: variant.py baserom.gen traces.npz variant.gen FLAG srcdir
(run after generate.py has written srcdir from the base ROM)
"""
import os, sys, re, difflib, pickle, types
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
from analyze import Analysis
from emit import Emitter
from m68k import Decoder, Instr, Op
import config
import generate
from variant_align import align as align_funcs


# ------------------------------------------------------------ address map
def linear(data, s, e):
    d = Decoder(data)
    out, a = [], s
    while a < e:
        try:
            ins = d.decode(a)
            if a + ins.length > e:
                raise ValueError
        except Exception:
            ins = Instr(a); ins.mnem = '.word'; ins.length = 2
            ins.ops = [Op('imm', value=int.from_bytes(data[a:a + 2], 'big'))]
        out.append(ins)
        a += ins.length
    return out


def token(ins):
    ops = []
    for o in ins.ops:
        if o.kind in ('branch', 'pcdisp', 'pcindex', 'absw', 'absl'):
            ops.append(o.kind)
        elif o.kind == 'imm' and o.extlen == 4:
            ops.append('imm32')
        else:
            ops.append('%s:%s:%s:%s' % (o.kind, o.reg, o.disp, o.value))
    return ins.mnem + ' ' + ','.join(ops)


class AddressMap:
    def __init__(self, rom, var, code_end=0x23480):
        self.n, self.nv = len(rom), len(var)
        self.b2v = np.full(self.n + 1, -1, np.int64)
        self.v2b = np.full(self.nv + 1, -1, np.int64)
        self.hunks = []             # (base_s, base_e, var_s, var_e) unmapped regions
        self.trust = np.zeros(self.n + 1, bool)   # mapping known exactly (not a diff guess)
        A, rom_, var_, funcs, mapping, _ = align_funcs_nonzero(rom, var)
        ends = dict(funcs)
        anchors = sorted((s, mapping[s], ends[s]) for s in mapping if s < code_end)
        # header/vectors and everything from code_end on: same addresses
        self.seg(0, 0, anchors[0][0])
        self.seg(code_end, code_end, self.n - code_end)
        for s, v, e in anchors:
            self.seg(s, v, e - s)
        bounds = anchors + [(code_end, code_end, code_end)]
        for (s, v, e), (s2, v2, _) in zip(bounds, bounds[1:]):
            self.gap(rom, var, e, s2, v + (e - s), v2)
        self.b2v[self.n] = self.nv
        self.v2b[self.nv] = self.n

    def seg(self, b, v, n, trusted=True):
        if n <= 0:
            return
        self.b2v[b:b + n] = np.arange(v, v + n)
        self.v2b[v:v + n] = np.arange(b, b + n)
        self.trust[b:b + n] = trusted

    def gap(self, rom, var, bs, be, vs, ve):
        if be - bs == ve - vs and rom[bs:be] == var[vs:ve]:
            self.seg(bs, vs, be - bs)
            return
        bi, vi = linear(rom, bs, be), linear(var, vs, ve)
        sm = difflib.SequenceMatcher(None, [token(i) for i in bi], [token(i) for i in vi], autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            b0 = bi[i1].addr if i1 < len(bi) else be
            b1 = bi[i2].addr if i2 < len(bi) else be
            v0 = vi[j1].addr if j1 < len(vi) else ve
            v1 = vi[j2].addr if j2 < len(vi) else ve
            if tag == 'equal':
                self.seg(b0, v0, b1 - b0)
                continue
            self.hunks.append((b0, b1, v0, v1))
            if b1 - b0 == v1 - v0:
                self.seg(b0, v0, b1 - b0, trusted=False)
            elif b1 > b0 and v1 > v0:
                self.bytes_align(rom, var, b0, b1, v0, v1)

    def bytes_align(self, rom, var, b0, b1, v0, v1):
        """Changed regions that hold data: bytes differ only where pointers
        moved, so a byte-level alignment maps them (untrusted guess)."""
        sm = difflib.SequenceMatcher(None, rom[b0:b1], var[v0:v1], autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == 'equal' and i2 - i1 >= 2:
                self.seg(b0 + i1, v0 + j1, i2 - i1, trusted=False)
            elif tag == 'replace' and i2 - i1 == j2 - j1:
                self.seg(b0 + i1, v0 + j1, i2 - i1, trusted=False)

    def refine(self, Ab, rom, var):
        """Data references are exact label anchors: an absolute / PC-relative
        operand or a data pointer at mapped, unchanged code/data names its
        target's variant address.  Between two consistent anchors with the
        same shift, the range maps at that shift (data blocks in changed
        regions, where the diffs are unreliable)."""
        dec = Decoder(var)
        anchors = {}
        REF = ('pcdisp', 'absl')
        for a, ins in Ab.code.items():
            va = int(self.b2v[a])
            if va < 0 or not self.trust[a] or var[va:va + 2] != rom[a:a + 2]:
                continue
            try:
                vi = dec.decode(va)
            except Exception:
                continue
            if vi.length != ins.length or len(vi.ops) != len(ins.ops):
                continue
            for o, vo in zip(ins.ops, vi.ops):
                if o.kind in REF and vo.kind == o.kind and o.target is not None and vo.target is not None:
                    t, vt = o.target, vo.target
                    if 0x200 <= t < self.n and 0 <= vt < self.nv and Ab.owner[t] < 0:
                        anchors.setdefault(t, set()).add(vt)
        for p_, (kind, t, base) in Ab.dptr.items():
            vp = int(self.b2v[p_])
            if kind in ('L', 'A') and vp >= 0 and self.trust[p_] and t < self.n and Ab.owner[t] < 0:
                vt = int.from_bytes(var[vp:vp + 4], 'big') & 0xFFFFFF
                if vt < self.nv:
                    anchors.setdefault(t, set()).add(vt)
        good = sorted((t, next(iter(v))) for t, v in anchors.items() if len(v) == 1)
        fixed = 0
        for (t1, v1), (t2, v2) in zip(good, good[1:]):
            d = v1 - t1
            if v2 - t2 != d or t2 - t1 > 0x2000 or self.trust[t1:t2].all():
                continue
            same = sum(1 for k in range(t2 - t1) if rom[t1 + k] == var[v1 + k])
            if same < 0.6 * (t2 - t1):
                continue
            # keep the map monotone around the range
            lo = int(self.b2v[t1 - 1]) if t1 > 0 else -1
            hi = int(self.b2v[t2]) if t2 <= self.n else self.nv
            if (lo >= 0 and lo >= v1) or (hi >= 0 and hi < v2):
                continue
            self.b2v[t1:t2] = np.arange(v1, v2)
            self.trust[t1:t2] = True
            fixed += t2 - t1
        self.v2b[:] = -1
        idx = np.nonzero(self.b2v >= 0)[0]
        self.v2b[self.b2v[idx]] = idx
        return len(good), fixed


def align_funcs_nonzero(rom, var):
    """variant_align.align, ignoring 'functions' made of zero padding."""
    import variant_align
    A, labels = variant_align.load()
    orig = variant_align.func_ranges
    def fr(A_):
        return [(s, e) for s, e in orig(A_) if any(rom[s:e])]
    variant_align.func_ranges = fr
    try:
        res = align_funcs(os.environ['VARIANT_ROM'])
    finally:
        variant_align.func_ranges = orig
    return res


# ------------------------------------------------------------ traces
def map_traces(tr, amap, rom, var, Ab):
    nv = amap.nv
    b2v = amap.b2v
    idx = np.nonzero(b2v[:amap.n] >= 0)[0]
    vi = b2v[idx]
    out = {}
    for k in ('ex', 'rd', 'rc', 'rr'):
        src = tr[k]
        dst = np.zeros_like(src)
        dst[vi] = src[idx]
        out[k] = dst
    who = tr['who']
    wv = np.zeros_like(who)
    ev = idx[(idx & 1) == 0]
    for b in ev:
        pc = int(who[b >> 1])
        if pc:
            v = int(b2v[b])
            if v >= 0 and not (v & 1):
                m = int(b2v[pc]) if pc < amap.n else -1
                wv[v >> 1] = m if m >= 0 else 0
    out['who'] = wv
    # variant-only code: mark decodable instructions in hunks whose base side was code
    def pure_code(bs, be):
        if be == bs:                      # insertion: inside code?
            return bs > 0 and Ab.owner[bs - 1] >= 0 and Ab.owner[bs] >= 0
        return all(Ab.owner[a] >= 0 for a in range(bs, be))
    for bs, be, vs, ve in amap.hunks:
        if ve > vs and pure_code(bs, be):
            for ins in linear(var, vs, ve):
                if ins.mnem != '.word':
                    out['ex'][ins.addr] = 1
    return out


# ------------------------------------------------------------ variant emitter
class VariantEmitter(Emitter):
    def __init__(self, A, names, cfg, amap):
        self.amap = amap
        super().__init__(A, names, cfg)
        # the asset manifest holds base addresses
        moved = {}
        for a, m in self.assets.items():
            m = dict(m)
            v, ve = int(amap.b2v[a]), int(amap.b2v[m['end']])
            assert v >= 0 and ve - v == m['end'] - a, m['name']
            m['end'] = ve
            moved[v] = m
        self.assets = moved
        # C-replaced routines keep their base names (their C prototypes use them)
        self.cfuncs = {a: (config.NAMES.get(int(amap.v2b[a])) or 'sub_%06X' % int(amap.v2b[a]))
                       for a in self.cfuncs}

    def default_name(self, a):
        if a in self.names:
            return self.names[a]
        b = int(self.amap.v2b[a]) if a <= self.amap.nv else -1
        if b >= 0 and not self.amap.trust[b]:
            b = -1                        # guessed mapping: variant-only name
        A = self.A
        if a == self.n:
            return 'ROM_End'
        pre = '' if b >= 0 else 'w'
        x = b if b >= 0 else a
        if a in A.code:
            return pre + ('sub_%06X' if a in A.funcs else 'loc_%06X') % x
        if a in A.jtables or A.labels.get(a) == 'jt':
            return pre + 'jtbl_%06X' % x
        if A.owner[a] >= 0:
            return pre + 'loc_%06X' % x
        return pre + 'dat_%06X' % x


def translated_cfg(amap):
    b2v = amap.b2v
    def m(a):
        v = int(b2v[a]) if a < len(b2v) else -1
        return v if v >= 0 else None
    c = types.SimpleNamespace(**{k: getattr(config, k) for k in dir(config) if k.isupper()})
    c.FORCE_LABELS = [m(a) for a in config.FORCE_LABELS if m(a) is not None]
    c.FILE_SPLITS = {m(a): n for a, n in config.FILE_SPLITS.items() if m(a) is not None}
    c.C_FUNCS = {m(a): v for a, v in config.C_FUNCS.items() if m(a) is not None}
    c.C_EXPORTS = [m(a) for a in config.C_EXPORTS if m(a) is not None]
    c.C_REGOUT = {m(a): v for a, v in getattr(config, "C_REGOUT", {}).items() if m(a) is not None}
    c.C_REGIN = {m(a): v for a, v in getattr(config, "C_REGIN", {}).items() if m(a) is not None}
    c.NAMES = {m(a): n for a, n in config.NAMES.items() if m(a) is not None}
    c.MOD_HOOKS = {m(a): dict(h, label=h.get('label', '%06X' % a)) for a, h in getattr(config, 'MOD_HOOKS', {}).items()
                   if m(a) is not None}
    return c


def sync_dptrs(Av, Ab, amap, var):
    """Where the map covers a location, the base's pointer decision wins
    (keeps unchanged data identical); only changed regions keep the
    variant analysis' own pointer detection."""
    in_hunk = np.zeros(amap.nv + 1, bool)
    for bs, be, vs, ve in amap.hunks:
        in_hunk[vs:ve] = True
    for vp in list(Av.dptr):
        bp = int(amap.v2b[vp])
        if bp >= 0 and not in_hunk[vp] and bp not in Ab.dptr:
            del Av.dptr[vp]
    for bp, (kind, t, base) in Ab.dptr.items():
        vp = int(amap.b2v[bp])
        if vp < 0 or vp in Av.dptr:
            continue
        if kind in ('L', 'A'):
            val = int.from_bytes(var[vp:vp + 4], 'big')
            vt = val & 0xFFFFFF
            if vt <= amap.nv and int(amap.v2b[vt]) == t:
                Av.dptr[vp] = (kind, vt, val & 0xFF000000 if kind == 'A' else base)
        elif kind == 'W':
            vt = int.from_bytes(var[vp:vp + 2], 'big')
            if int(amap.v2b[vt]) == t:
                Av.dptr[vp] = (kind, vt, base)


# ------------------------------------------------------------ merge
IMM = re.compile(r'#(-?0x[0-9A-Fa-f]+|-?\d+)')
SCREEN = [(160, 'SCREEN_W', 320), (240, 'SCREEN_H', 224), (80, 'SCREEN_W/2', 160), (120, 'SCREEN_H/2', 112)]


def screen_expr(bv, wv):
    """Express a constant that changes between the builds in terms of the
    screen size, if the change matches one."""
    for d, sym, base in SCREEN:
        if wv - bv == d:
            k = bv - base
            return sym if k == 0 else '%s%+d' % (sym, k)
    return None


LABEL = re.compile(r'^(\S+:|\t\w+ = \. \+ \d+)$')


def items(lines):
    """(labels, content line) pairs; labels attach to the next content line."""
    out, labels = [], []
    for l in lines:
        if LABEL.match(l):
            labels.append(l)
        else:
            out.append((labels, l)); labels = []
    out.append((labels, None))
    return out


def flat(its):
    out = []
    for labels, l in its:
        out += labels
        if l is not None:
            out.append(l)
    return out


def label_names(lines):
    return {l.split(':')[0].split('=')[0].strip() for l in lines if LABEL.match(l)}


def merge_lines(bl, vl, flag, base_defs=frozenset(), var_defs=frozenset()):
    """Labels name the same logical location in both trees (base-address
    names), so labels only one side needed are emitted unconditionally -
    unless the other tree defines that label elsewhere, then only for the
    build that has it here."""
    def name(x):
        return x.split(':')[0].split('=')[0].strip()
    bi, vi = items(bl), items(vl)
    sm = difflib.SequenceMatcher(None, [l for _, l in bi], [l for _, l in vi], autojunk=False)
    out = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            for (lb, l), (lv, _) in zip(bi[i1:i2], vi[j1:j2]):
                for x in lb:
                    if x not in lv and name(x) in var_defs:
                        out += ['.if %s == 0' % flag, x, '.endif']
                    else:
                        out.append(x)
                for x in lv:
                    if x in lb:
                        continue
                    if name(x) in base_defs:
                        out += ['.if %s' % flag, x, '.endif']
                    else:
                        out.append(x)
                if l is not None:
                    out.append(l)
            continue
        out += merge_hunk(flat(bi[i1:i2]), flat(vi[j1:j2]), flag)
    return out


def merge_hunk(bl, vl, flag):
    # constants that change with the screen size -> SCREEN_W/SCREEN_H expressions
    if bl and len(bl) == len(vl):
        done = []
        for x, y in zip(bl, vl):
            mx, my = IMM.findall(x), IMM.findall(y)
            e = None
            if len(mx) == len(my) and IMM.sub('#', x) == IMM.sub('#', y):
                diff = [(a, b) for a, b in zip(mx, my) if a != b]
                if len(diff) == 1:
                    e = screen_expr(int(diff[0][0], 0), int(diff[0][1], 0))
            if not e:
                done = None
                break
            done.append(x.replace('#' + diff[0][0], '#' + e, 1))
        if done is not None:
            return done
    out = ['.if %s' % flag] + vl
    if bl:
        out += ['.else'] + bl
    return out + ['.endif']


INCBIN = re.compile(r'\.incbin\t"bin/([0-9A-F]{6})\.bin"')


def fix_incbin(line, amap, src, vdir, flag):
    """Variant blobs are named by variant address: use the base blob when the
    content is the same, else copy it in as bin/<flag>_XXXXXX.bin."""
    m = INCBIN.search(line)
    if not m:
        return line
    va = int(m.group(1), 16)
    data = open(os.path.join(vdir, 'bin', m.group(1) + '.bin'), 'rb').read()
    b = int(amap.v2b[va])
    if b >= 0:
        bp = os.path.join(src, 'bin', '%06X.bin' % b)
        if os.path.exists(bp) and open(bp, 'rb').read() == data:
            return line.replace(m.group(1), '%06X' % b)
    fn = '%s_%06X.bin' % (flag.lower(), b if b >= 0 else va)
    open(os.path.join(src, 'bin', fn), 'wb').write(data)
    return line.replace(m.group(1) + '.bin', fn)


def main():
    rom = open(sys.argv[1], 'rb').read()
    tr = np.load(sys.argv[2])
    variant = sys.argv[3]
    flag = sys.argv[4]
    src = sys.argv[5]
    os.environ['VARIANT_ROM'] = variant
    var = open(variant, 'rb').read()
    amap = AddressMap(rom, var)
    Ab, _ = pickle.load(open(os.path.join(os.path.dirname(src.rstrip('/')), 'build', 'analysis.pkl'), 'rb'))
    na, nf = amap.refine(Ab, rom, var)
    print('address map: %d hunks, %d anchors, %d bytes remapped' % (len(amap.hunks), na, nf))
    vt = map_traces(tr, amap, rom, var, Ab)
    cfg = translated_cfg(amap)
    # the same label set as the base, so data lines are chunked the same way
    _, base_labels = pickle.load(open(os.path.join(os.path.dirname(src.rstrip('/')), 'build', 'analysis.pkl'), 'rb'))
    cfg.FORCE_LABELS = sorted(set(cfg.FORCE_LABELS) | {int(amap.b2v[a]) for a in base_labels
                                                       if a <= amap.n and amap.trust[a] and int(amap.b2v[a]) >= 0})
    cfg.IMM_PTR = [int(amap.b2v[a]) for a in config.IMM_PTR if int(amap.b2v[a]) >= 0]
    cfg.NOT_PTRS = [int(amap.b2v[a]) for a in config.NOT_PTRS if int(amap.b2v[a]) >= 0]
    cfg.DATA_PTRS = {int(amap.b2v[a]): k for a, k in config.DATA_PTRS.items() if int(amap.b2v[a]) >= 0}
    A = Analysis(var, vt['ex'], vt['rd'], cfg, vt['who'], vt['rc'], vt['rr'])
    A.discover()
    for _ in range(3):
        A.speculative_pointers(); A.table_pass(False)
        A.fill_gaps(); A.table_pass(False)
    A.find_data_pointers()
    A.pcrel_ptr_tables()
    sync_dptrs(A, Ab, amap, var)
    print('variant analysis: %d insns, %d dptrs' % (len(A.code), len(A.dptr)))
    E = VariantEmitter(A, cfg.NAMES, cfg, amap)
    bad = E.validate()
    print('validate: %d raw' % len(bad))
    # same files as the base tree, at mapped addresses
    names = open(os.path.join(src, 'files.txt')).read().split()
    splits = []
    for nm in names:
        b = 0 if nm == 'header' else int(nm.split('_')[1], 16)
        v = int(amap.b2v[b])
        assert v >= 0, nm
        splits.append((v, nm))
    vdir = os.path.join(os.path.dirname(src.rstrip('/')), 'build', 'variant_' + flag.lower())
    os.makedirs(vdir, exist_ok=True)
    E.emit_all(vdir, sorted(splits), bindir_name='bin')
    # merge module by module
    nblocks = 0
    base_defs, var_defs = set(), set()
    for nm in names:
        base_defs |= label_names(open(os.path.join(src, nm + '.s')).read().split('\n'))
        var_defs |= label_names(open(os.path.join(vdir, nm + '.s')).read().split('\n'))
    for nm in names + ['symbols']:
        bp = os.path.join(src, nm + ('.inc' if nm == 'symbols' else '.s'))
        vp = os.path.join(vdir, nm + ('.inc' if nm == 'symbols' else '.s'))
        bl = open(bp).read().split('\n')
        vl = open(vp).read().split('\n')
        if nm == 'symbols':
            extra = [l for l in vl if l not in set(bl)]
            hdr = ['.ifndef %s' % flag, '\t.set\t%s,0' % flag, '.endif']
            if flag == 'WIDE':
                hdr += ['| screen size: 320x224, or 480x464 for the WIDE build (needs an',
                        '| emulator with the matching screen hack)',
                        '.if WIDE', '\t.set\tSCREEN_W,480', '\t.set\tSCREEN_H,464',
                        '.else', '\t.set\tSCREEN_W,320', '\t.set\tSCREEN_H,224', '.endif']
            merged = bl[:2] + hdr + bl[2:-1] + extra + ['']
        else:
            vl[0] = bl[0]            # header comment carries the base addresses
            vl = [fix_incbin(l, amap, src, vdir, flag) for l in vl]
            merged = merge_lines(bl, vl, flag, base_defs, var_defs)
        nblocks += sum(1 for l in merged if l.startswith('.if %s' % flag))
        open(bp, 'w').write('\n'.join(merged))
    print('merged: %d .if %s blocks' % (nblocks, flag))
    n = symbolize_raw_pointers(src, names, flag, variant)
    print('raw variant pointers made symbolic: %d' % n)


def symbolize_operands(line, L, i, syms, rom_end):
    """A numeric ROM address operand in a variant-only instruction becomes
    label[+offset] when the base side of the block has the same instruction
    with a label there (or it is cmpi.l against a code label)."""
    code = line.split('|')[0]
    m = re.search(r'(#|\()0x([0-9A-Fa-f]+)(\)\.l)?', code)
    if not m or (m.group(1) == '(' and not m.group(3)):
        return line
    v = int(m.group(2), 16)
    if not (0x200 <= v < rom_end):
        return line
    # base side of this block
    k, depth, base = i + 1, 0, []
    while k < len(L):
        t = L[k].split('|')[0].strip()
        if t.startswith('.if'):
            depth += 1
        elif t == '.endif':
            if depth == 0:
                break
            depth -= 1
        elif t == '.else' and depth == 0:
            k += 1
            while k < len(L) and L[k].split('|')[0].strip() != '.endif':
                base.append(L[k].split('|')[0].strip()); k += 1
            break
        k += 1
    pat = code.strip()[:m.start() - (len(code) - len(code.lstrip()))] + m.group(1)
    tail = code.strip()[m.end() - (len(code) - len(code.lstrip())):]
    rx = re.compile(re.escape(pat) + r'[A-Za-z_]\w*' + re.escape(m.group(3) or '') + re.escape(tail) + '$')
    is_ptr = any(rx.match(b) for b in base)
    if not is_ptr and code.strip().startswith('cmpi.l') and v in syms:
        is_ptr = True
    if not is_ptr:
        return line
    if v in syms:
        sym = syms[v]
    else:
        lo = max((a for a in syms if a <= v and v - a < 0x400), default=None)
        if lo is None:
            return line
        sym = '%s+0x%X' % (syms[lo], v - lo)
    print('  symbolized: %s -> %s' % (code.strip(), sym))
    return line[:m.start(2) - 2] + sym + line[m.end(2):]


def symbolize_raw_pointers(src, names, flag, variant):
    """Variant-only data emitted as raw .byte can still hold absolute
    pointers (the variant analysis did not find every table).  Those are not
    relocated when code moves, so rewrite them as .long <label>: a 32-bit
    value in a variant-only .byte run is taken as a pointer when it is the
    address of a label of the variant build and either the base side of the
    same block is a pointer table (.long) or the value is >= 0x10000.  The
    variant ROM must come out byte-identical."""
    import subprocess, tempfile, hashlib
    root = os.path.dirname(src.rstrip('/'))
    def build():
        d = tempfile.mkdtemp()
        subprocess.run(['m68k-linux-gnu-as', '-m68000', '--register-prefix-optional', '-I', src, '-I', root,
                        '--defsym', '%s=1' % flag, '-o', d + '/m.o', os.path.join(src, 'main.s')], check=True)
        subprocess.run(['m68k-linux-gnu-ld', '-T', os.path.join(root, 'rom.ld'), '-o', d + '/m.elf', d + '/m.o'],
                       check=True, stderr=subprocess.DEVNULL)
        subprocess.run(['m68k-linux-gnu-objcopy', '-O', 'binary', '-j', '.text', d + '/m.elf', d + '/m.bin'], check=True)
        nm = subprocess.run(['m68k-linux-gnu-nm', d + '/m.elf'], capture_output=True, text=True).stdout
        syms = {}
        for l in nm.split('\n'):
            p = l.split()
            if len(p) == 3 and p[1] in 'tT' and not p[2].startswith('.L'):
                syms.setdefault(int(p[0], 16), p[2])
        return open(d + '/m.bin', 'rb').read(), syms
    ref = open(variant, 'rb').read()
    rom, syms = build()
    if rom != ref:
        raise SystemExit('symbolize: the %s build does not match before the rewrite' % flag)
    total = 0
    for nm in names:
        path = os.path.join(src, nm + '.s')
        L = open(path).read().split('\n')
        out, i, stack = [], 0, []
        while i < len(L):
            line = L[i]
            st = line.split('|')[0].strip()
            if st.startswith('.if'):
                stack.append([st == '.if %s' % flag, False, i])
            elif st == '.else' and stack:
                stack[-1][1] = True
            elif st == '.endif' and stack:
                stack.pop()
            if st.startswith('.byte') and stack and stack[-1][0] and not stack[-1][1]:
                j = i
                data = b''
                while j < len(L) and L[j].split('|')[0].strip().startswith('.byte'):
                    data += bytes(int(x, 0) for x in L[j].split('|')[0].strip()[5:].split(','))
                    j += 1
                # base side of this block
                k, depth, base = j, 0, []
                while k < len(L):
                    t = L[k].split('|')[0].strip()
                    if t.startswith('.if'):
                        depth += 1
                    elif t == '.endif':
                        if depth == 0:
                            break
                        depth -= 1
                    elif t == '.else' and depth == 0:
                        base = []
                        k += 1
                        while k < len(L) and L[k].split('|')[0].strip() != '.endif':
                            base.append(L[k]); k += 1
                        break
                    k += 1
                table = any(b.split('|')[0].strip().startswith('.long') for b in base)
                ptrs = {}
                for o in range(0, len(data) - 3, 4):
                    v = int.from_bytes(data[o:o + 4], 'big')
                    if v >= 0x200 and v in syms and (table or v >= 0x10000):
                        ptrs[o] = syms[v]
                if ptrs:
                    o, raw = 0, []
                    def flush_raw():
                        for q in range(0, len(raw), 16):
                            out.append('\t.byte\t' + ','.join('0x%02X' % x for x in raw[q:q + 16]))
                        raw.clear()
                    while o < len(data):
                        if o in ptrs:
                            flush_raw()
                            out.append('\t.long\t%s' % ptrs[o])
                            o += 4
                        else:
                            raw.append(data[o]); o += 1
                    flush_raw()
                    total += len(ptrs)
                else:
                    out.extend(L[i:j])
                i = j
                continue
            if stack and stack[-1][0] and not stack[-1][1] and not st.startswith('.') and st:
                line = symbolize_operands(line, L, i, syms, rom_end=len(ref))
                if line != L[i]:
                    total += 1
            out.append(line)
            i += 1
        open(path, 'w').write('\n'.join(out))
    rom2, _ = build()
    if rom2 != ref:
        raise SystemExit('symbolize: the rewrite changed the %s build' % flag)
    return total


if __name__ == '__main__':
    main()
