#!/usr/bin/env python3
"""Differential test of C replacements against real game states.

For each function, snapshots of registers + all of work RAM at its entry are
captured by replaying short windows from the save-state pool
(tools/ctest/states.py) in the tracing emulator; they are cached in
build/snaps/.  Then the original (baserom.gen) and the C-only build
(build/nm, same layout) run the function in Unicorn from the same snapshot
until it returns.  Compared:
  - the result (d0, as wide as the C prototype says; a0 too for pointers)
  - all RAM except the stack below the entry SP
  - the sequence of writes to I/O (VDP, Z80, pads)
  - every 16-bit register half the original leaves untouched

usage: snaptest.py NAME [NAME ...] [--n 24] [--recapture]
       (NAME as in tools/disasm/names.py, or sub_XXXXXX)
"""
import sys, os, re, glob, struct, subprocess, ctypes
import numpy as np
from unicorn import Uc, UC_ARCH_M68K, UC_MODE_BIG_ENDIAN, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE, UcError
from unicorn.m68k_const import *

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, 'tools', 'disasm'))
sys.path.insert(0, os.path.join(ROOT, 'tools', 'emu'))
from names import NAMES

BY_NAME = {v: k for k, v in NAMES.items()}
RET_MAGIC = 0x3FFFF0
DREGS = [UC_M68K_REG_D0 + i for i in range(8)]
AREGS = [UC_M68K_REG_A0 + i for i in range(8)]
SNAPDIR = os.path.join(ROOT, 'build', 'snaps')
POOL = os.path.join(ROOT, 'build', 'states', 'pool')


def addr_of(name):
    if name in BY_NAME:
        return BY_NAME[name]
    m = re.match(r'sub_([0-9A-Fa-f]{6})$', name)
    if m:
        return int(m.group(1), 16)
    raise KeyError(name)


def c_prototypes():
    """label -> return kind (v b w l p), from the same parser the generator uses"""
    import csig
    return {lab: r for (k, lab), (r, a) in csig.load().items() if k == 'C_IMPL'}


# ------------------------------------------------------------ capture
def capture_many(addrs, n, recapture=False):
    """Snapshots for several functions in one pass over the state pool
    (cached per function in build/snaps/)."""
    os.makedirs(SNAPDIR, exist_ok=True)
    path = lambda a: os.path.join(SNAPDIR, '%06X.npz' % a)
    todo = [a for a in addrs if recapture or not os.path.exists(path(a))]
    got = {a: [] for a in todo}
    if todo:
        from harness import Emu
        states = sorted(glob.glob(os.path.join(POOL, '*.st')))
        e = Emu(os.path.join(ROOT, 'baserom.gen'))
        e.run(1)
        boot = e.save_state()
        from scenario import SCENARIOS
        for group in [todo[i:i + 16] for i in range(0, len(todo), 16)]:
            # start-up code (VDP / sound setup, menus): one run from power-on
            e.load_state(boot)
            e.snapwatch(group, max_n=n, stride=1)
            for btns, k in SCENARIOS['menus']()[:40]:
                e.set_buttons(*btns); e.run(k)
            for pc, regs, sr, ram in e.snapshots():
                if pc in got and len(got[pc]) < n:
                    got[pc].append((regs, sr, ram))
            for window, stride in ((90, 7), (900, 1)):   # second pass for rare functions
                for st in states:
                    need = [a for a in group if len(got[a]) < n]
                    if not need:
                        break
                    e.load_state(open(st, 'rb').read())
                    e.snapwatch(need, max_n=3, stride=stride)
                    e.run(window)
                    for pc, regs, sr, ram in e.snapshots():
                        if pc in got and len(got[pc]) < n:
                            got[pc].append((regs, sr, ram))
                if all(len(got[a]) >= n // 2 for a in group):
                    break
        e.close()
        for a, snaps in got.items():
            if snaps:
                np.savez_compressed(path(a), regs=np.array([s[0] for s in snaps], np.uint32),
                                    sr=np.array([s[1] for s in snaps], np.uint32),
                                    ram=np.array([np.frombuffer(s[2], np.uint8) for s in snaps]))
    out = {}
    for a in addrs:
        if os.path.exists(path(a)):
            d = np.load(path(a))
            out[a] = list(zip(d['regs'], d['sr'], d['ram']))
        else:
            out[a] = []
    return out


# ------------------------------------------------------------ machine
class Machine:
    def __init__(self, rom):
        self.uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
        self.uc.ctl_set_cpu_model(UC_CPU_M68K_M68000)
        self.bufs = {}
        img = bytearray(0x400000); img[:len(rom)] = rom
        self.map(0x000000, bytes(img))
        ram = self.map(0x00FF0000, bytes(0x10000))
        self.uc.mem_map_ptr(0xFFFF0000, 0x10000, 7, ram)      # (xxxx).w addresses
        self.map(0x00A00000, bytes(0x20000))                   # Z80 area, I/O
        self.map(0x00C00000, bytes(0x10000))                   # VDP
        # no Z80 here: a bus request is granted at once (the sound driver
        # polls Z80_BUSREQ bit 0 until it reads 0)
        self.uc.hook_add(UC_HOOK_MEM_READ, lambda uc, acc, addr, size, val, user: uc.mem_write(0xA11100, b'\x00\x00'),
                         begin=0xA11100, end=0xA11101)
        self.io = []
        self.uc.hook_add(UC_HOOK_MEM_WRITE, self._io, begin=0x00A00000, end=0x00A1FFFF)
        self.uc.hook_add(UC_HOOK_MEM_WRITE, self._io, begin=0x00C00000, end=0x00C0FFFF)

    def map(self, addr, data):
        buf = ctypes.create_string_buffer(data, len(data))
        self.uc.mem_map_ptr(addr, len(data), 7, buf)
        self.bufs[addr] = buf
        return buf

    def _io(self, uc, access, addr, size, value, user):
        self.io.append((addr, size, value & ((1 << (8 * size)) - 1)))

    def run(self, pc, regs, sr, ram, limit=2000000):
        ram = bytearray(ram)
        sp = int(regs[15])
        ram[sp & 0xFFFF:(sp & 0xFFFF) + 4] = struct.pack('>I', RET_MAGIC)
        ctypes.memmove(self.bufs[0x00FF0000], bytes(ram), 0x10000)
        ctypes.memset(self.bufs[0x00A00000], 0, 0x20000)
        ctypes.memset(self.bufs[0x00C00000], 0, 0x10000)
        self.io = []
        for i, r in enumerate(DREGS + AREGS[:7]):
            self.uc.reg_write(r, int(regs[i]))
        self.uc.reg_write(UC_M68K_REG_SR, int(sr) | 0x2700)       # before A7 (SR selects SSP)
        self.uc.reg_write(UC_M68K_REG_A7, sp)
        err = None
        try:
            self.uc.emu_start(pc, RET_MAGIC, count=limit)
        except UcError as e:
            err = str(e)
        if self.uc.reg_read(UC_M68K_REG_PC) != RET_MAGIC and not err:
            err = 'timeout'
        out = [self.uc.reg_read(r) for r in DREGS + AREGS]
        return out, self.bufs[0x00FF0000].raw[:0x10000], list(self.io), err


def c_symbol(name, elf):
    for l in subprocess.run(['m68k-linux-gnu-nm', elf], capture_output=True, text=True).stdout.split('\n'):
        p = l.split()
        if len(p) == 3 and p[2] == name:
            return int(p[0], 16)
    return None


def test(name, snaps, base, nm, protos, verbose=True):
    addr = addr_of(name)
    if not snaps:
        print('%-26s no calls captured' % name)
        return None
    kind = protos.get(name, 'w')
    bad = 0
    clob = set()
    timeouts = 0
    for k, (regs, sr, ram) in enumerate(snaps):
        ra, ma, ia, ea = base.run(addr, regs, sr, ram)
        rb, mb, ib, eb = nm.run(addr, regs, sr, ram)
        if ea == 'timeout' and eb == 'timeout':
            timeouts += 1           # does not return here (a whole screen loop): no verdict
            continue
        sp = int(regs[15]) & 0xFFFF
        why = []
        if ea or eb:
            if ea != eb:
                why.append('error %s / %s' % (ea, eb))
        if kind == 'b' and (ra[0] ^ rb[0]) & 0xFF:
            why.append('d0.b %02X/%02X' % (ra[0] & 0xFF, rb[0] & 0xFF))
        if kind == 'w' and (ra[0] ^ rb[0]) & 0xFFFF:
            why.append('d0.w %04X/%04X' % (ra[0] & 0xFFFF, rb[0] & 0xFFFF))
        if kind == 'l' and ra[0] != rb[0]:
            why.append('d0 %08X/%08X' % (ra[0], rb[0]))
        if kind == 'p' and ra[8] != rb[8]:
            why.append('a0 %08X/%08X' % (ra[8], rb[8]))
        # preserved registers: judged with scrambled entry registers (compiled
        # functions take no register arguments), so a value that merely
        # happens to equal the entry value does not count
        pr = [int(regs[i]) ^ (0x5A5A5A5A + 0x01010101 * i) for i in range(15)] + [int(regs[15])]
        pa = base.run(addr, pr, sr, ram)[0]
        pb = nm.run(addr, pr, sr, ram)[0]
        for i in range(1, 15):
            for half, mask in (('.h', 0xFFFF0000), ('.l', 0xFFFF)):
                if (pa[i] ^ pr[i]) & mask == 0 and (pb[i] ^ pr[i]) & mask:
                    clob.add('%s%d%s' % ('da'[i // 8], i % 8, half))
        # RAM: everything except the stack below the entry SP
        da = np.frombuffer(ma, np.uint8); db = np.frombuffer(mb, np.uint8)
        diff = np.nonzero(da != db)[0]
        diff = diff[~((diff >= sp - 0x800) & (diff < sp))]       # callee's stack frame
        diff = diff[~((diff >= 0xC356) & (diff < 0xC574))]        # the C build's own state (.bss)
        if len(diff):
            why.append('ram %s' % ', '.join('%06X:%02X/%02X' % (0xFF0000 + d, da[d], db[d]) for d in diff[:4]))
        if ia != ib:
            why.append('io %d/%d writes' % (len(ia), len(ib)))
        if why:
            bad += 1
            if verbose and bad <= 3:
                print('  #%d %s' % (k, '; '.join(why)))
    if timeouts == len(snaps):
        print('%-26s inconclusive (does not return within the test limit)' % name)
        return None
    res = 'equivalent' if not bad else '%d MISMATCHES' % bad
    extra = ' clobbers ' + ','.join(sorted(clob)) if clob else ''
    print('%-26s %s (%d snapshots)%s' % (name, res, len(snaps), extra))
    return bad == 0 and not clob


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    n = int(sys.argv[sys.argv.index('--n') + 1]) if '--n' in sys.argv else 24
    if '--n' in sys.argv:
        args = [a for a in args if a != str(n)]
    recapture = '--recapture' in sys.argv
    base = Machine(open(os.path.join(ROOT, 'baserom.gen'), 'rb').read())
    nm = Machine(open(os.path.join(ROOT, 'build', 'nm', 'dune2.gen'), 'rb').read())
    protos = c_prototypes()
    names = args or sorted(protos)
    snaps = capture_many([addr_of(nm_) for nm_ in names], n, recapture)
    ok = untested = 0
    for name in names:
        r = test(name, snaps[addr_of(name)], base, nm, protos)
        if r:
            ok += 1
        elif r is None:
            untested += 1       # no calls captured, or never returns: no verdict
        sys.stdout.flush()
    bad = len(names) - ok - untested
    print('%d/%d equivalent, %d untested, %d failing' % (ok, len(names), untested, bad))
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
