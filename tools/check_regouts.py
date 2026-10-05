#!/usr/bin/env python3
"""Static check of the register contract of C-replaced routines.

A C replacement is reached through a stub that preserves d1-d2/a0-a1 (a0 is
the result for pointer functions) and returns its result in d0.  That is only
right if no caller depends on any other register effect of the original
routine.  For every call site of every C_IMPL routine, in every build variant
(WIDE=0/1), this follows the caller's code after the call and reports
registers that are read before being overwritten when
  - the original routine changes them but the stub does not reproduce them
    (e.g. a caller using d1 = the VDP register value the routine computed), or
  - the original routine leaves them alone but the C version does not
    preserve them (d0 for void routines), or
  - d0 is read as a long after a routine that returns a byte/word.
Register values that flow out of the caller (rts / tail jump) are followed
into the caller's own call sites.

It also checks the other direction: C code that calls an original routine
directly with inline asm ("jsr X_asm", register-argument helpers) must
declare every register X can change (outputs or clobbers); d0-d1/a0-a1 are
the usual ones, but asm routines may change others.

usage: check_regouts.py        (exit status 1 if anything is found)
"""
import os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'disasm'))
import csig

ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, 'src')
REGS = ['d%d' % i for i in range(8)] + ['a%d' % i for i in range(8)]
SCRATCH = {'d0', 'd1', 'a0', 'a1'}


# ---------------------------------------------------------------- flattening
def flatten(syms):
    """main.s with includes expanded and .if blocks evaluated for syms."""
    out = []

    def ev(expr):
        e = expr.split('|')[0].strip()
        try:
            return bool(eval(e, {}, dict(syms)))
        except Exception:
            return False

    def walk(path):
        stack = []            # (active_parent, this_active, taken)
        active = True
        for line in open(path):
            line = line.rstrip('\n')
            s = line.split('|')[0].strip()
            if s.startswith('.if'):
                cond = ev(s[3:].strip()) if s.startswith('.if ') else False
                stack.append((active, active and cond, cond))
                active = active and cond
                continue
            if s == '.else':
                parent, _, taken = stack[-1]
                stack[-1] = (parent, parent and not taken, True)
                active = parent and not taken
                continue
            if s == '.endif':
                active = stack.pop()[0]
                continue
            if not active:
                continue
            m = re.match(r'\s*\.include\s+"([^"]+)"', line)
            if m:
                p = os.path.join(SRC, m.group(1))
                if os.path.exists(p):
                    walk(p)
                continue
            out.append(line)
    walk(os.path.join(SRC, 'main.s'))
    return out


# ---------------------------------------------------------------- parsing
class Insn:
    __slots__ = ('mn', 'size', 'ops', 'text', 'idx')


def split_ops(s):
    ops, depth, cur = [], 0, ''
    for ch in s:
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        if ch == ',' and depth == 0:
            ops.append(cur.strip()); cur = ''
        else:
            cur += ch
    if cur.strip():
        ops.append(cur.strip())
    return ops


def reglist(s):
    out = set()
    for part in s.split('/'):
        m = re.fullmatch(r'([da])(\d)-([da])(\d)', part)
        if m:
            for i in range(int(m.group(2)), int(m.group(4)) + 1):
                out.add(m.group(1) + str(i))
        else:
            r = norm(part)
            if r:
                out.add(r)
    return out


def norm(t):
    t = t.strip().lower()
    if t == 'sp':
        return 'a7'
    if t == 'fp':
        return 'a6'
    return t if re.fullmatch(r'[da][0-7]', t) else None


def regs_in(op):
    return {norm(t) for t in re.findall(r'\b(?:[da][0-7]|sp|fp)\b', op.lower())} - {None}


def parse(lines):
    insns, labels = [], {}
    for line in lines:
        s = line.split('|')[0].rstrip()
        m = re.match(r'^([.\w]+):\s*(.*)$', s)
        if m:
            labels[m.group(1)] = len(insns)
            s = m.group(2)
        s = s.strip()
        if not s:
            continue
        m = re.match(r'^([.\w]+)\s*(.*)$', s)
        mn = m.group(1).lower()
        if mn.startswith('.') and mn not in ('.byte', '.word', '.long', '.ascii', '.asciz', '.incbin', '.short', '.space', '.fill'):
            continue
        ins = Insn()
        ins.text = s
        ins.idx = len(insns)
        if '.' in mn and not mn.startswith('.'):
            ins.mn, ins.size = mn.split('.', 1)
        else:
            ins.mn, ins.size = mn, ''
        ins.ops = split_ops(m.group(2)) if not mn.startswith('.') else []
        insns.append(ins)
    return insns, labels


READ_ONLY = {'tst', 'cmp', 'cmpa', 'cmpi', 'cmpm', 'btst', 'chk', 'pea'}
WRITE_ONLY = {'move', 'movea', 'moveq', 'lea', 'clr', 'st', 'sf', 'seq', 'sne', 'scc', 'scs', 'smi', 'spl',
              'shi', 'sls', 'sge', 'slt', 'sgt', 'sle', 'svc', 'svs'}
BRANCH = {'bra', 'bcc', 'bcs', 'beq', 'bne', 'bmi', 'bpl', 'bhi', 'bls', 'bge', 'blt', 'bgt', 'ble', 'bvc', 'bvs',
          'bhs', 'blo'}
DBCC = {'dbra', 'dbf', 'dbeq', 'dbne', 'dbcc', 'dbcs', 'dbmi', 'dbpl', 'dbge', 'dblt', 'dbgt', 'dble', 'dbhi', 'dbls'}


def effects(ins):
    """(reads, writes, longreads) register sets of one instruction."""
    mn, ops = ins.mn, ins.ops
    r, w, lr = set(), set(), set()
    if mn == 'movem':
        if '-(' in ops[1] or '(' in ops[1]:             # registers -> memory
            r |= reglist(ops[0]); r |= regs_in(ops[1])
            if ins.size == 'l':
                lr |= reglist(ops[0])
        else:
            r |= regs_in(ops[0]); w |= reglist(ops[1])
        return r, w, lr
    if mn == 'exg':
        a, b = norm(ops[0]), norm(ops[1])
        return {a, b}, {a, b}, {a, b}
    if mn in ('swap', 'ext', 'extb', 'neg', 'negx', 'not'):
        x = regs_in(ops[0])
        return x, {norm(ops[0])} - {None}, x if mn == 'swap' or (ins.size == 'l' and mn not in ('ext', 'extb')) else set()
    if mn in ('unlk', 'link'):
        return {'a6', 'a7'}, {'a6', 'a7'}, set()
    if mn in DBCC:
        x = norm(ops[0])
        return {x}, {x}, set()
    for i, op in enumerate(ops):
        rr = regs_in(op)
        dest = i == len(ops) - 1 and len(ops) > 1 or (len(ops) == 1 and mn in ('clr', 'st', 'sf') or mn.startswith('s') and len(ops) == 1 and mn not in ('swap',))
        bare = norm(op)
        if dest and bare:
            if mn in READ_ONLY:
                r.add(bare)
            elif mn in WRITE_ONLY:
                w.add(bare)
            else:
                r.add(bare); w.add(bare)
            continue
        # addressing: registers used as base/index are read; -(An)/(An)+ also write
        r |= rr
        if re.search(r'-\((a\d|sp)\)|\((a\d|sp)\)\+', op.lower()):
            w |= rr
        if not dest and bare and ins.size == 'l':
            lr.add(bare)
        if re.search(r'\b(d\d)\.l\b', op.lower()):
            lr |= set(re.findall(r'\b(d\d)\.l\b', op.lower()))
    if mn in ('mulu', 'muls', 'divu', 'divs'):
        pass
    return r, w, lr


def target(ins):
    op = ins.ops[0] if ins.ops else ''
    m = re.fullmatch(r'\(?([.\w]+)\)?(\.[wl])?|\(([.\w]+),pc\)', op)
    if m:
        return m.group(1) or m.group(3)
    return None


# ---------------------------------------------------------------- analysis
def func_starts(insns, labels, referenced=()):
    starts = {}
    for name, i in labels.items():
        if i >= len(insns):
            continue
        if re.match(r'^(loc_|wloc_|\.L|\d)', name) and name not in referenced:
            continue
        if insns[i].mn.startswith('.'):
            continue
        starts[i] = name
    return starts


_MOD = {}


def body_writes(insns, labels, starts, i0, depth=0):
    """Registers the routine at i0 changes at its return (saved ones
    excluded).  Follows the routine's control flow from its entry, and calls
    into known routines (an asm callee can leave any register changed, not
    just d0-d1/a0-a1)."""
    if i0 in _MOD:
        return _MOD[i0]
    _MOD[i0] = set(SCRATCH)          # recursion guard: assume scratch
    w, saved = set(), set()
    seen = set()
    work = [i0]
    while work:
        i = work.pop()
        while i < len(insns) and i not in seen:
            seen.add(i)
            ins = insns[i]
            mn = ins.mn
            if mn.startswith('.'):
                break
            if mn == 'movem' and '-(' in ins.ops[1]:
                saved |= reglist(ins.ops[0])
            if mn == 'move' and ins.size == 'l' and len(ins.ops) == 2 and ins.ops[1].lower() in ('-(sp)', '-(a7)') \
                    and norm(ins.ops[0]) and i - i0 < 6:
                saved.add(norm(ins.ops[0]))     # prologue push, restored before rts
            if mn == 'link':
                saved.add('a6')                 # link/unlk frame pointer
            _, ww, _ = effects(ins)
            w |= ww
            if mn in ('rts', 'rte', 'rtr'):
                break
            if mn in ('jsr', 'bsr', 'jmp'):
                t = target(ins)
                if t == 'EntryPoint':
                    break                       # reset: does not return
                if t in labels and labels[t] in starts and depth < 60:
                    w |= body_writes(insns, labels, starts, labels[t], depth + 1)
                    if mn == 'jmp':
                        break                   # tail call
                elif mn == 'jmp':
                    if t in labels:
                        work.append(labels[t])
                    else:
                        w |= SCRATCH            # computed jump
                    break
                else:
                    w |= SCRATCH                # indirect call
                i += 1
                continue
            if mn in BRANCH or mn in DBCC:
                t = re.sub(r'\.[sbwl]$', '', ins.ops[-1] if ins.ops else '')
                if t in labels:
                    work.append(labels[t])
                if mn == 'bra':
                    break
            i += 1
    r = w - saved - {'a7'}
    _MOD[i0] = r
    return r


def follow(insns, labels, starts, i0, live, budget=400):
    """From instruction i0 with registers 'live' (holding values from the
    routine just called), yield (kind, reg, insn) for reads / escapes."""
    seen = set()
    work = [(i0, frozenset(live))]
    steps = 0
    while work and steps < budget:
        i, lv = work.pop()
        while lv and i < len(insns) and steps < budget:
            if (i, lv) in seen:
                break
            seen.add((i, lv))
            steps += 1
            ins = insns[i]
            mn = ins.mn
            if mn.startswith('.'):
                break
            if mn in ('rts', 'rte', 'rtr'):
                for x in lv:
                    yield 'escape', x, ins, False
                break
            if mn in ('jsr', 'bsr'):
                t = target(ins)
                r, _, lr = effects(ins)
                for x in lv & r:
                    yield 'read', x, ins, x in lr
                if t in labels and labels[t] in starts:
                    lv = lv - body_writes(insns, labels, starts, labels[t]) - SCRATCH
                else:
                    lv = lv - SCRATCH   # calls change the scratch registers
                i += 1
                continue
            if mn == 'jmp':
                t = target(ins)
                r, _, lr = effects(ins)
                for x in lv & r:
                    yield 'read', x, ins, x in lr
                if t == 'EntryPoint':
                    break
                if t in labels and labels[t] in starts:
                    for x in lv:          # tail call: the values reach that routine
                        yield 'tail', x, ins, False
                elif t in labels:
                    work.append((labels[t], lv))
                break
            r, w, lr = effects(ins)
            for x in lv & r:
                yield 'read', x, ins, x in lr
            lv = lv - w
            if mn in BRANCH or mn in DBCC:
                t = ins.ops[-1] if ins.ops else ''
                t = re.sub(r'\.[sbwl]$', '', t)
                if t in labels:
                    work.append((labels[t], lv))
                if mn == 'bra':
                    break
            i += 1


def containing(starts_sorted, i):
    lo = None
    for s in starts_sorted:
        if s <= i:
            lo = s
        else:
            break
    return lo


def check(syms, sigs, verbose=False):
    import config, names
    byname = {v: k for k, v in names.NAMES.items()} if hasattr(names, 'NAMES') else {}
    regout = {}
    for a, regs in getattr(config, 'C_REGOUT', {}).items():
        regout[names.NAMES.get(a, 'sub_%06X' % a)] = regs
    lines = flatten(syms)
    _MOD.clear()
    insns, labels = parse(lines)
    referenced = set()            # call targets and code pointers in tables
    for ins in insns:
        if ins.mn in ('jsr', 'bsr') and ins.ops:
            referenced.add(target(ins))
        elif ins.mn == '.long':
            referenced.update(t.strip() for t in ins.text.split(None, 1)[1].split(','))
    pointed = {t for ins in insns if ins.mn == '.long' for t in (x.strip() for x in ins.text.split(None, 1)[1].split(','))}
    starts = func_starts(insns, labels, referenced)
    indirect = [ins.idx for ins in insns if ins.mn == 'jsr' and ins.ops and target(ins) is None]
    starts_sorted = sorted(starts)
    calls = {}                    # target label -> [insn index]
    for ins in insns:
        if ins.mn in ('jsr', 'bsr', 'jmp', 'bra') and ins.ops:
            t = target(ins)
            if t:
                calls.setdefault(t, []).append(ins.idx)
    problems = []
    for (kind, label), (ret, args) in sorted(sigs.items()):
        if kind != 'C_IMPL' or label not in labels:
            continue
        i0 = labels[label]
        wr = body_writes(insns, labels, starts, i0)
        # what the stub hands back: d0 (and a0 = d0 for pointers); preserved: d1-d2/a0-a1 + GCC's d3-d7/a2-a6
        provided = {'d0'} if ret != 'v' else set()
        provided |= {r.split('.')[0] for r in regout.get(label, [])}
        if ret == 'p':
            provided.add('a0')
        clobbered = {'d0'} if ret == 'v' else set()
        bad_out = wr - provided                       # changed by the original, not by the stub
        bad_keep = clobbered - wr                     # kept by the original, not by C
        watch = bad_out | bad_keep | (provided & {'d0'})
        todo = [(label, idx, frozenset(watch), label) for idx in calls.get(label, [])]
        done = set()
        while todo:
            fn, idx, w, chain = todo.pop()
            if (idx, w) in done:
                continue
            done.add((idx, w))
            ins = insns[idx]
            if ins.mn in ('jmp', 'bra'):
                # tail call: the values go back to the caller of this routine
                c = containing(starts_sorted, idx)
                if c is not None:
                    for j in calls.get(starts[c], []):
                        todo.append((starts[c], j, w, chain + ' <- ' + starts[c]))
                continue
            for what, reg, at, islong in follow(insns, labels, starts, idx + 1, w):
                if reg == 'd0' and reg in provided:
                    if islong and ret in ('b', 'w') and chain == label:
                        problems.append((label, chain, at.text, 'd0 read as long after a %s result' % {'b': 'byte', 'w': 'word'}[ret]))
                    continue
                if what == 'read':
                    why = 'changed by the original, not by the C stub' if reg in bad_out else 'kept by the original, clobbered by C'
                    c2 = containing(starts_sorted, at.idx)
                    where = '%s+%d insns' % (starts[c2], at.idx - c2) if c2 is not None else '?'
                    problems.append((label, chain, '%s [in %s]' % (at.text, where), '%s used after the call: %s' % (reg, why)))
                elif what in ('escape', 'tail'):
                    c = containing(starts_sorted, at.idx)
                    if c is not None:
                        callers = calls.get(starts[c], [])
                        if starts[c] in pointed:      # called through a pointer: try every indirect call
                            callers = callers + indirect
                        for j in callers:
                            todo.append((starts[c], j, frozenset([reg]), chain + ' <- ' + starts[c]))
    return problems


INLINE = re.compile(r'__asm__\s+volatile\s*\(\s*((?:"[^"]*"\s*)+)(?::([^:;]*))?(?::([^:;]*))?(?::([^;]*?))?\)\s*;', re.S)


def inline_calls():
    """(file, routine, registers declared changed) for every inline jsr."""
    import glob
    out = []
    for f in sorted(glob.glob(os.path.join(SRC, 'c', '*.[ch]'))):
        txt = open(f).read()
        regvars = dict(re.findall(r'register\s+[^;]*?\b(\w+)\s+__asm__\("([ad][0-7])"\)', txt))
        for m in INLINE.finditer(txt):
            code, outs, ins, clob = m.groups()
            for call in re.findall(r'jsr\s+(\w+)_asm', code):
                declared = set()
                for part in (outs or '').split(','):
                    mm = re.search(r'\((\w+)\)', part)
                    if mm and mm.group(1) in regvars:
                        declared.add(regvars[mm.group(1)])
                declared |= set(re.findall(r'"([ad][0-7])"', clob or ''))
                # registers saved and restored inside the asm string itself
                for mm in re.finditer(r'movem\.l\s+([^,]+),-\(%%sp\)', code):
                    declared |= reglist(mm.group(1).replace('%', ''))
                for mm in re.finditer(r'move\.l\s+%%(\w+),-\(%%sp\)', code):
                    declared.add(norm(mm.group(1)))
                out.append((os.path.basename(f), call, declared))
    return out


def check_inline(syms):
    lines = flatten(syms)
    _MOD.clear()
    insns, labels = parse(lines)
    referenced = set()
    for ins in insns:
        if ins.mn in ('jsr', 'bsr') and ins.ops:
            referenced.add(target(ins))
    starts = func_starts(insns, labels, referenced)
    probs = []
    for f, call, declared in inline_calls():
        if call not in labels:
            continue
        mods = body_writes(insns, labels, starts, labels[call]) - {'a7'}
        if f.endswith('.c') or f.endswith('.h'):
            missing = mods - declared
            if missing:
                probs.append((f, call, sorted(missing), sorted(declared)))
    return probs


def main():
    sigs = csig.load()
    bad = 0
    for wide in (0, 1):
        seen = set()
        for f, call, missing, declared in check_inline({'WIDE': wide, 'NONMATCHING': 0, 'MODS': 0, 'AUTOPLAY': 0}):
            key = (f, call, tuple(missing))
            if key in seen:
                continue
            seen.add(key)
            print('WIDE=%d  %s: inline jsr %s changes %s, declared only %s' % (wide, f, call, ','.join(missing), ','.join(declared)))
            bad += 1
    for wide in (0, 1):
        syms = {'WIDE': wide, 'NONMATCHING': 0, 'MODS': 0, 'AUTOPLAY': 0}
        seen = set()
        for label, chain, at, msg in check(syms, sigs):
            key = (label, chain, at, msg)
            if key in seen:
                continue
            seen.add(key)
            print('WIDE=%d  %-22s %s\n        via %s: %s' % (wide, label, msg, chain, at))
            bad += 1
    print('%d problem(s)' % bad)
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
