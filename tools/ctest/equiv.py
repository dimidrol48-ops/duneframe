#!/usr/bin/env python3
"""Differential test: original 68000 routines vs their C replacements.

Each decompiled function is called in a CPU emulator (Unicorn, m68k) twice -
once from the original ROM, once through its C version in the mod build (via the stub) -
with identical random arguments and identical RAM / I/O contents.  Return
registers and the final state of RAM and I/O space must match exactly.

usage: equiv.py [function ...] [--n 2000]
"""
import sys, os, random, struct, subprocess, ctypes
from unicorn import Uc, UC_ARCH_M68K, UC_MODE_BIG_ENDIAN, UC_HOOK_MEM_READ, UC_HOOK_CODE, UcError
from unicorn.m68k_const import *

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, 'tools', 'disasm'))
from names import NAMES, RAM_NAMES

BY_NAME = {v: k for k, v in NAMES.items()}
RET_MAGIC = 0x3FFFF0
DREGS = [UC_M68K_REG_D0 + i for i in range(8)]
AREGS = [UC_M68K_REG_A0 + i for i in range(8)]


def c_symbols(elf):
    out = {}
    for line in subprocess.run(['m68k-linux-gnu-nm', elf], capture_output=True, text=True).stdout.split('\n'):
        p = line.split()
        if len(p) == 3:
            out[p[2]] = int(p[0], 16)
    return out


class Machine:
    def __init__(self, rom):
        self.uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
        self.uc.ctl_set_cpu_model(UC_CPU_M68K_M68000)   # default model is a ColdFire
        self.bufs = {}
        romimg = bytearray(0x400000); romimg[:len(rom)] = rom
        self.map(0x000000, bytes(romimg))
        ram = self.map(0x00FF0000, bytes(0x10000))
        self.alias(0xFFFF0000, ram)             # (xxxx).w addresses sign-extend
        self.map(0x00A00000, bytes(0x20000))    # Z80 RAM / YM / I/O
        self.map(0x00A10000 + 0x20000, bytes(0x10000))
        self.map(0x00C00000, bytes(0x10000))    # VDP
        # no Z80 here: a bus request is granted at once (the sound driver
        # polls Z80_BUSREQ bit 0 until it reads 0)
        self.uc.hook_add(UC_HOOK_MEM_READ, lambda uc, acc, addr, size, val, user: uc.mem_write(0xA11100, b'\x00\x00'),
                         begin=0xA11100, end=0xA11101)

    def map(self, addr, data):
        buf = ctypes.create_string_buffer(data, len(data))
        self.uc.mem_map_ptr(addr, len(data), 7, buf)
        self.bufs[addr] = buf
        return buf

    def alias(self, addr, buf):
        self.uc.mem_map_ptr(addr, ctypes.sizeof(buf) - 1 if ctypes.sizeof(buf) & 1 else ctypes.sizeof(buf), 7, buf)

    def ram(self):
        return self.bufs[0x00FF0000].raw[:0x10000]

    def io(self):
        return self.bufs[0x00A00000].raw[:0x20000] + self.bufs[0x00C00000].raw[:0x100]

    def call(self, pc, stack_args, ram_init, regs=None, limit=200000, fill=0x5A5A5A5A):
        self.bufs[0x00FF0000][:0x10000] = ram_init
        self.bufs[0x00A00000][:0x20000] = bytes(0x20000)
        sp = 0x00FFFE00
        data = b''.join(struct.pack('>H' if sz == 2 else '>I', v & (0xFFFF if sz == 2 else 0xFFFFFFFF)) for v, sz in stack_args)
        sp -= len(data)
        self.uc.mem_write(sp, data)
        sp -= 4
        self.uc.mem_write(sp, struct.pack('>I', RET_MAGIC))
        for r in DREGS + AREGS[:7]:
            self.uc.reg_write(r, fill)
        for r, v in (regs or {}).items():
            self.uc.reg_write(r, v)
        self.uc.reg_write(UC_M68K_REG_SR, 0x2700)      # before A7: SR selects the stack pointer
        self.uc.reg_write(UC_M68K_REG_A7, sp)
        self.uc.emu_start(pc, RET_MAGIC, count=limit)
        if self.uc.reg_read(UC_M68K_REG_PC) != RET_MAGIC:
            raise UcError(0) if False else RuntimeError('timeout (did not return)')
        return [self.uc.reg_read(r) for r in DREGS + AREGS]


# ---------------------------------------------------------------- test cases
def rnd_ram(rng):
    b = bytearray(rng.getrandbits(8) for _ in range(0x10000))
    return b


def set_ram(ram, name, value, size=1):
    a = next(k for k, v in RAM_NAMES.items() if v == name) & 0xFFFF
    ram[a:a + size] = value.to_bytes(size, 'big')


def s16(rng):
    return rng.randint(-0x8000, 0x7FFF)


def u16(rng):
    return rng.randint(0, 0xFFFF)


def case_Math_Distance(rng, ram):
    return [(s16(rng), 2) for _ in range(4)], {'d0w': True}


def case_Math_MulShr8(rng, ram):
    return [(u16(rng) - 0x10000 if rng.random() < .5 else rng.randint(0, 0x7FFF), 2), (rng.randint(-0x8000, 0x7FFF), 2)], {}


def case_Math_Ratio(rng, ram):
    return [(rng.randint(-0x8000, 0x7FFF), 2), (rng.randint(-0x8000, 0x7FFF), 2)], {}


def case_Sound_PlayFx(rng, ram):
    set_ram(ram, 'g_soundEnabled', rng.choice([0, 1, 0xFF]))
    return [(rng.randint(0, 120), 2)], {'void': True}


def case_Sound_PlayHouseVoice(rng, ram):
    set_ram(ram, 'g_soundEnabled', rng.choice([0, 1]))
    set_ram(ram, 'g_playerHouse', rng.randint(0, 4), 2)
    set_ram(ram, 'g_lastVoice', rng.randint(0, 0xFF))
    return [(rng.randint(0, 60), 2)], {'void': True}


def case_Anim_Start(rng, ram):
    return [(0xFF8000 + rng.randrange(0, 0x100, 2), 4), (rng.getrandbits(31), 4)], {'void': True}


def case_Anim_SetFrame(rng, ram):
    anim = 0xFF8000
    script = 0xFF9000
    base = rng.getrandbits(23) & ~1
    tbl = 0xFF9100
    ram[0x8004:0x8008] = (script if rng.random() > .05 else 0).to_bytes(4, 'big')
    ram[0x9004:0x9008] = base.to_bytes(4, 'big')
    ram[0x9008:0x900C] = tbl.to_bytes(4, 'big')
    n = rng.randint(0, 30)
    a = anim if rng.random() > .05 else 0
    # with a null Anim the original leaves the caller's a0, the C version returns 0
    return [(a, 4), (n, 2)], {'void': True, 'ignore': ['a0'] if a == 0 else []}


def rnd_str(rng, ram, at, maxlen):
    n = rng.randint(0, maxlen)
    s = bytes(rng.choice(b'AB\x80\xffz') for _ in range(n)) + b'\0'
    ram[at & 0xFFFF:(at & 0xFFFF) + len(s)] = s
    return s


def case_strlen(rng, ram):
    rnd_str(rng, ram, 0xFF8000, 40)
    return [(0xFF8000, 4)], {}


def case_strcmp(rng, ram):
    a = rnd_str(rng, ram, 0xFF8000, 6)
    if rng.random() < .4:
        ram[0x8100:0x8100 + len(a)] = a
    else:
        rnd_str(rng, ram, 0xFF8100, 6)
    return [(0xFF8000, 4), (0xFF8100, 4)], {}


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    n = int(sys.argv[sys.argv.index('--n') + 1]) if '--n' in sys.argv else 1000
    if '--n' in sys.argv:
        args = [a for a in args if a != str(n)]
    base = Machine(open(os.path.join(ROOT, 'baserom.gen'), 'rb').read())
    mod = Machine(open(os.path.join(ROOT, 'build', 'nm', 'dune2.gen'), 'rb').read())
    syms = c_symbols(os.path.join(ROOT, 'build', 'nm', 'dune2.elf'))
    funcs = args or [k[5:] for k in globals() if k.startswith('case_')]
    fails = 0
    for fn in funcs:
        case = globals()['case_' + fn]
        rng = random.Random(fn)
        bad = 0
        clobbered = set()
        for i in range(n):
            ram = rnd_ram(rng) if i % 50 == 0 or i == 0 else ram
            ram2 = bytearray(ram)
            stack, opts = case(rng, ram2)
            try:
                fill = rng.getrandbits(32)
                ra = base.call(BY_NAME[fn], stack, bytes(ram2), fill=fill)
                sa, ia = base.ram(), base.io()
                rb = mod.call(syms[fn], stack, bytes(ram2), fill=fill)   # through the NONMATCHING stub
                sb, ib = mod.ram(), mod.io()
            except (UcError, RuntimeError) as e:
                print('  %s: emulation error %s on %s' % (fn, e, stack)); bad += 1; continue
            if opts.get('void'):
                same_ret = True
            elif opts.get('d0w'):
                same_ret = (ra[0] & 0xFFFF) == (rb[0] & 0xFFFF)
            else:
                same_ret = ra[0] == rb[0]
            # registers the original leaves intact must survive the C version
            # too: hand-written callers may rely on them (even "scratch" ones)
            ign = [8 + int(r[1]) if r[0] == 'a' else int(r[1]) for r in opts.get('ignore', [])]
            # checked per 16-bit half: word-sized code keeps the upper half,
            # and callers do use it (e.g. swap d1 / call / swap d1)
            clob = []
            for k in range(1, 15):
                if k in ign:
                    continue
                for half, mask in (('.h', 0xFFFF0000), ('.l', 0xFFFF)):
                    if (ra[k] ^ fill) & mask == 0 and (rb[k] ^ fill) & mask:
                        clob.append('%s%d%s' % ('da'[k // 8], k % 8, half))
            if clob:
                clobbered.update(clob)
            lo = 0xFE00 - 0x100   # ignore the stack area
            if not same_ret or clob or sa[:lo] != sb[:lo] or ia != ib:
                bad += 1
                if bad <= 3:
                    diff = [hex(0xFF0000 + k) for k in range(lo) if sa[k] != sb[k]][:5]
                    print('  %s MISMATCH args=%s d0 %08X/%08X ram %s io %s' % (fn, [hex(v & 0xFFFFFFFF) for v, s in stack], ra[0], rb[0], diff, ia != ib))
        print('%-22s %s (%d cases)%s' % (fn, 'equivalent' if not bad else '%d MISMATCHES' % bad, n,
                                          ' clobbers ' + ','.join(sorted(clobbered)) if clobbered else ''))
        fails += bad > 0
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
