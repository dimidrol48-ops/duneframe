"""Motorola 68000 instruction decoder producing structured instructions.

Output syntax targets GNU as (m68k, --register-prefix-optional, Motorola
operand syntax).  The decoder only accepts encodings that are valid on a
plain 68000; anything else is reported as invalid so that code/data
separation can reject it.
"""
import struct

SZ = {0: 'b', 1: 'w', 2: 'l'}
CC = ['t', 'f', 'hi', 'ls', 'cc', 'cs', 'ne', 'eq', 'vc', 'vs', 'pl', 'mi', 'ge', 'lt', 'gt', 'le']


class Invalid(Exception):
    pass


class Op:
    __slots__ = ('kind', 'reg', 'disp', 'xreg', 'xsize', 'value', 'size', 'target', 'ext', 'extlen')

    def __init__(self, kind, reg=None, disp=0, xreg=None, xsize=None, value=None, size=None, target=None, ext=None, extlen=0):
        self.kind = kind; self.reg = reg; self.disp = disp; self.xreg = xreg; self.xsize = xsize
        self.value = value; self.size = size; self.target = target; self.ext = ext; self.extlen = extlen

    def __repr__(self):
        return 'Op(%s)' % ', '.join('%s=%r' % (k, getattr(self, k)) for k in self.__slots__ if getattr(self, k) is not None)


class Instr:
    __slots__ = ('addr', 'length', 'mnem', 'ops', 'flow', 'targets', 'raw')

    def __init__(self, addr):
        self.addr = addr; self.length = 2; self.mnem = ''; self.ops = []; self.flow = 'normal'; self.targets = []
        self.raw = b''

    def __repr__(self):
        return '%06X: %s %s' % (self.addr, self.mnem, self.ops)


def areg(n):
    return 'sp' if n == 7 else 'a%d' % n


def s8(x):
    return x - 0x100 if x & 0x80 else x


def s16(x):
    return x - 0x10000 if x & 0x8000 else x


def s32(x):
    return x - 0x100000000 if x & 0x80000000 else x


class Decoder:
    def __init__(self, data, base=0):
        self.data = data
        self.base = base

    def w(self, addr):
        o = addr - self.base
        if o < 0 or o + 2 > len(self.data):
            raise Invalid('eof')
        return (self.data[o] << 8) | self.data[o + 1]

    def l(self, addr):
        return (self.w(addr) << 16) | self.w(addr + 2)

    # --- effective address decoding
    def ea(self, ins, pos, mode, reg, size, allowed):
        """Decode EA; pos is address of next extension word. Returns (Op, newpos).
        allowed: string of mode letters: d a m + - D X W L P Q I
        (Dn, An, (An), (An)+, -(An), d16(An), d8(An,Xn), abs.w, abs.l, d16(PC), d8(PC,Xn), #imm)"""
        if mode == 0:
            k = 'd'; op = Op('dn', reg='d%d' % reg)
        elif mode == 1:
            k = 'a'; op = Op('an', reg=areg(reg))
        elif mode == 2:
            k = 'm'; op = Op('ind', reg=areg(reg))
        elif mode == 3:
            k = '+'; op = Op('postinc', reg=areg(reg))
        elif mode == 4:
            k = '-'; op = Op('predec', reg=areg(reg))
        elif mode == 5:
            k = 'D'; op = Op('disp', reg=areg(reg), disp=s16(self.w(pos)), ext=pos - ins.addr, extlen=2); pos += 2
        elif mode == 6:
            k = 'X'; ext = self.w(pos)
            if ext & 0x0700:
                raise Invalid('full ext word')
            xr = ('a%d' % ((ext >> 12) & 7)) if ext & 0x8000 else ('d%d' % ((ext >> 12) & 7))
            if xr == 'a7': xr = 'sp'
            op = Op('index', reg=areg(reg), disp=s8(ext & 0xff), xreg=xr, xsize='l' if ext & 0x800 else 'w',
                    ext=pos - ins.addr, extlen=2)
            pos += 2
        elif mode == 7:
            if reg == 0:
                k = 'W'; v = s16(self.w(pos)) & 0xFFFFFFFF
                op = Op('absw', value=v, target=v & 0xFFFFFF, ext=pos - ins.addr, extlen=2); pos += 2
            elif reg == 1:
                k = 'L'; v = self.l(pos)
                op = Op('absl', value=v, target=v & 0xFFFFFF, ext=pos - ins.addr, extlen=4); pos += 4
            elif reg == 2:
                k = 'P'; d = s16(self.w(pos))
                op = Op('pcdisp', disp=d, target=(pos + d) & 0xFFFFFF, ext=pos - ins.addr, extlen=2); pos += 2
            elif reg == 3:
                k = 'Q'; ext = self.w(pos)
                if ext & 0x0700:
                    raise Invalid('full ext word')
                xr = ('a%d' % ((ext >> 12) & 7)) if ext & 0x8000 else ('d%d' % ((ext >> 12) & 7))
                if xr == 'a7': xr = 'sp'
                d = s8(ext & 0xff)
                op = Op('pcindex', disp=d, xreg=xr, xsize='l' if ext & 0x800 else 'w', target=(pos + d) & 0xFFFFFF,
                        ext=pos - ins.addr, extlen=2)
                pos += 2
            elif reg == 4:
                k = 'I'
                if size == 'b':
                    v = self.w(pos)
                    if (v & 0xFF00) == 0xFF00 and (v & 0x80):
                        v = (v & 0xff) - 0x100   # sign-extended byte immediate (emitted as negative)
                    elif v & 0xFF00:
                        raise Invalid('imm byte high')
                    else:
                        v &= 0xff
                    n = 2
                elif size == 'w':
                    v = self.w(pos); n = 2
                elif size == 'l':
                    v = self.l(pos); n = 4
                else:
                    raise Invalid('imm no size')
                op = Op('imm', value=v, size=size, ext=pos - ins.addr, extlen=n); pos += n
            else:
                raise Invalid('bad mode7')
        if k not in allowed:
            raise Invalid('ea not allowed')
        return op, pos

    # allowed-mode sets
    ALL = 'dam+-DXWLPQI'
    DATA = 'dm+-DXWLPQI'          # data addressing
    MEM = 'm+-DXWLPQI'
    ALT = 'dam+-DXWL'             # alterable
    DALT = 'dm+-DXWL'             # data alterable
    MALT = 'm+-DXWL'              # memory alterable
    CTRL = 'mDXWLPQ'              # control
    CALT = 'mDXWL'                # control alterable

    def decode(self, addr):
        ins = Instr(addr)
        op = self.w(addr)
        pos = addr + 2
        hi = op >> 12
        try:
            pos = getattr(self, 'line%X' % hi)(ins, op, pos)
        except IndexError:
            raise Invalid('idx')
        ins.length = pos - addr
        ins.raw = bytes(self.data[addr - self.base:pos - self.base])
        return ins

    # ---------------------------------------------------------------- line 0
    def line0(self, ins, op, pos):
        mode = (op >> 3) & 7; reg = op & 7
        if op & 0x0100:
            if mode == 1:  # movep
                dr = (op >> 9) & 7; opm = (op >> 6) & 7
                d = s16(self.w(pos))
                mem = Op('disp', reg=areg(reg), disp=d, ext=2, extlen=2); pos += 2
                sz = 'w' if opm in (4, 6) else 'l'
                ins.mnem = 'movep.' + sz
                dn = Op('dn', reg='d%d' % dr)
                ins.ops = [mem, dn] if opm in (4, 5) else [dn, mem]
                return pos
            # dynamic bit ops
            t = (op >> 6) & 3
            name = ['btst', 'bchg', 'bclr', 'bset'][t]
            dn = Op('dn', reg='d%d' % ((op >> 9) & 7))
            if t == 0:
                ea, pos = self.ea(ins, pos, mode, reg, 'b', 'dm+-DXWLPQI')
            else:
                ea, pos = self.ea(ins, pos, mode, reg, 'b', self.DALT)
            ins.mnem = name + ('.l' if mode == 0 else '.b')
            ins.ops = [dn, ea]
            return pos
        sub = (op >> 9) & 7
        szb = (op >> 6) & 3
        if sub == 4:  # static bit
            t = szb
            name = ['btst', 'bchg', 'bclr', 'bset'][t]
            b = self.w(pos)
            if b & 0xFF00:
                raise Invalid('bitnum')
            imm = Op('imm', value=b & 0xff, size='b', ext=2, extlen=2); pos += 2
            if t == 0:
                ea, pos = self.ea(ins, pos, mode, reg, 'b', 'dm+-DXWLPQ')
            else:
                ea, pos = self.ea(ins, pos, mode, reg, 'b', self.DALT)
            ins.mnem = name + ('.l' if mode == 0 else '.b')
            ins.ops = [imm, ea]
            return pos
        names = {0: 'ori', 1: 'andi', 2: 'subi', 3: 'addi', 5: 'eori', 6: 'cmpi'}
        if sub not in names or szb == 3:
            raise Invalid('line0')
        name = names[sub]
        sz = SZ[szb]
        # to CCR / SR
        if mode == 7 and reg == 4 and sub in (0, 1, 5):
            if szb == 0:
                v = self.w(pos)
                if v & 0xFF00: raise Invalid('ccr imm')
                ins.mnem = name + '.b'; ins.ops = [Op('imm', value=v, size='b', ext=2, extlen=2), Op('ccr')]
                return pos + 2
            if szb == 1:
                v = self.w(pos)
                ins.mnem = name + '.w'; ins.ops = [Op('imm', value=v, size='w', ext=2, extlen=2), Op('sr')]
                return pos + 2
            raise Invalid('sr l')
        imm, pos = self.ea(ins, pos, 7, 4, sz, 'I')
        if sub == 6:
            ea, pos = self.ea(ins, pos, mode, reg, sz, 'dm+-DXWL')  # 68000: no pc-rel for cmpi
        else:
            ea, pos = self.ea(ins, pos, mode, reg, sz, self.DALT)
        ins.mnem = name + '.' + sz
        ins.ops = [imm, ea]
        return pos

    # ---------------------------------------------------------------- move
    def _move(self, ins, op, pos, sz):
        smode = (op >> 3) & 7; sreg = op & 7
        dreg = (op >> 9) & 7; dmode = (op >> 6) & 7
        src, pos = self.ea(ins, pos, smode, sreg, sz, self.ALL if sz != 'b' else self.DATA)
        if dmode == 1:
            if sz == 'b':
                raise Invalid('movea.b')
            ins.mnem = 'movea.' + sz
            ins.ops = [src, Op('an', reg=areg(dreg))]
            return pos
        dst, pos = self.ea(ins, pos, dmode, dreg, sz, self.DALT)
        ins.mnem = 'move.' + sz
        ins.ops = [src, dst]
        return pos

    def line1(self, ins, op, pos): return self._move(ins, op, pos, 'b')
    def line2(self, ins, op, pos): return self._move(ins, op, pos, 'l')
    def line3(self, ins, op, pos): return self._move(ins, op, pos, 'w')

    # ---------------------------------------------------------------- line 4
    def line4(self, ins, op, pos):
        mode = (op >> 3) & 7; reg = op & 7
        if op & 0x0100:
            if (op >> 6) & 7 == 7:  # lea
                ea, pos = self.ea(ins, pos, mode, reg, 'l', self.CTRL)
                ins.mnem = 'lea'; ins.ops = [ea, Op('an', reg=areg((op >> 9) & 7))]
                return pos
            if (op >> 6) & 7 == 6:  # chk.w
                ea, pos = self.ea(ins, pos, mode, reg, 'w', self.DATA)
                ins.mnem = 'chk.w'; ins.ops = [ea, Op('dn', reg='d%d' % ((op >> 9) & 7))]
                return pos
            raise Invalid('line4 0x100')
        sub = (op >> 8) & 0xF
        szb = (op >> 6) & 3
        if op == 0x4AFC:
            ins.mnem = 'illegal'; ins.flow = 'stop'; return pos
        if sub == 0:
            if szb == 3:
                ea, pos = self.ea(ins, pos, mode, reg, 'w', self.DALT)
                ins.mnem = 'move.w'; ins.ops = [Op('sr'), ea]; return pos
            ea, pos = self.ea(ins, pos, mode, reg, SZ[szb], self.DALT)
            ins.mnem = 'negx.' + SZ[szb]; ins.ops = [ea]; return pos
        if sub == 2:
            if szb == 3: raise Invalid('move from ccr (68010)')
            ea, pos = self.ea(ins, pos, mode, reg, SZ[szb], self.DALT)
            ins.mnem = 'clr.' + SZ[szb]; ins.ops = [ea]; return pos
        if sub == 4:
            if szb == 3:
                ea, pos = self.ea(ins, pos, mode, reg, 'w', self.DATA)
                ins.mnem = 'move.w'; ins.ops = [ea, Op('ccr')]; return pos
            ea, pos = self.ea(ins, pos, mode, reg, SZ[szb], self.DALT)
            ins.mnem = 'neg.' + SZ[szb]; ins.ops = [ea]; return pos
        if sub == 6:
            if szb == 3:
                ea, pos = self.ea(ins, pos, mode, reg, 'w', self.DATA)
                ins.mnem = 'move.w'; ins.ops = [ea, Op('sr')]; return pos
            ea, pos = self.ea(ins, pos, mode, reg, SZ[szb], self.DALT)
            ins.mnem = 'not.' + SZ[szb]; ins.ops = [ea]; return pos
        if sub == 8:
            if szb == 0:
                ea, pos = self.ea(ins, pos, mode, reg, 'b', self.DALT)
                ins.mnem = 'nbcd.b'; ins.ops = [ea]; return pos
            if szb == 1:
                if mode == 0:
                    ins.mnem = 'swap'; ins.ops = [Op('dn', reg='d%d' % reg)]; return pos
                ea, pos = self.ea(ins, pos, mode, reg, 'l', self.CTRL)
                ins.mnem = 'pea'; ins.ops = [ea]; return pos
            if mode == 0:
                ins.mnem = 'ext.' + ('w' if szb == 2 else 'l'); ins.ops = [Op('dn', reg='d%d' % reg)]; return pos
            # movem reg->mem
            mask = self.w(pos); pos += 2
            ea, pos = self.ea(ins, pos, mode, reg, 'l', 'm-DXWL')
            ins.mnem = 'movem.' + ('w' if szb == 2 else 'l')
            ins.ops = [Op('reglist', value=mask, reg='predec' if mode == 4 else 'normal', ext=2, extlen=2), ea]
            return pos
        if sub == 0xA:
            if szb == 3:
                ea, pos = self.ea(ins, pos, mode, reg, 'b', self.DALT)
                ins.mnem = 'tas'; ins.ops = [ea]; return pos
            ea, pos = self.ea(ins, pos, mode, reg, SZ[szb], self.DALT)  # 68000 tst: data alterable
            ins.mnem = 'tst.' + SZ[szb]; ins.ops = [ea]; return pos
        if sub == 0xC:
            if szb in (2, 3):
                mask = self.w(pos); pos += 2
                ea, pos = self.ea(ins, pos, mode, reg, 'l', 'm+DXWLPQ')
                ins.mnem = 'movem.' + ('w' if szb == 2 else 'l')
                ins.ops = [ea, Op('reglist', value=mask, reg='normal', ext=2, extlen=2)]
                return pos
            raise Invalid('mul/div long')
        if sub == 0xE:
            if szb == 1:
                low = op & 0x3F
                if low < 0x10:
                    ins.mnem = 'trap'; ins.ops = [Op('imm', value=low & 15, size='q')]; return pos
                if low < 0x18:
                    d = s16(self.w(pos))
                    ins.mnem = 'link'; ins.ops = [Op('an', reg=areg(reg)), Op('imm', value=d & 0xFFFF, size='w', ext=2, extlen=2)]
                    return pos + 2
                if low < 0x20:
                    ins.mnem = 'unlk'; ins.ops = [Op('an', reg=areg(reg))]; return pos
                if low < 0x28:
                    ins.mnem = 'move.l'; ins.ops = [Op('an', reg=areg(reg)), Op('usp')]; return pos
                if low < 0x30:
                    ins.mnem = 'move.l'; ins.ops = [Op('usp'), Op('an', reg=areg(reg))]; return pos
                if op == 0x4E70: ins.mnem = 'reset'; return pos
                if op == 0x4E71: ins.mnem = 'nop'; return pos
                if op == 0x4E72:
                    v = self.w(pos); ins.mnem = 'stop'; ins.ops = [Op('imm', value=v, size='w', ext=2, extlen=2)]; return pos + 2
                if op == 0x4E73: ins.mnem = 'rte'; ins.flow = 'ret'; return pos
                if op == 0x4E75: ins.mnem = 'rts'; ins.flow = 'ret'; return pos
                if op == 0x4E76: ins.mnem = 'trapv'; return pos
                if op == 0x4E77: ins.mnem = 'rtr'; ins.flow = 'ret'; return pos
                raise Invalid('4e7x')
            if szb == 2:
                ea, pos = self.ea(ins, pos, mode, reg, 'l', self.CTRL)
                ins.mnem = 'jsr'; ins.ops = [ea]; ins.flow = 'call'
                if ea.kind in ('absw', 'absl', 'pcdisp'): ins.targets = [ea.target]
                return pos
            if szb == 3:
                ea, pos = self.ea(ins, pos, mode, reg, 'l', self.CTRL)
                ins.mnem = 'jmp'; ins.ops = [ea]; ins.flow = 'jump'
                if ea.kind in ('absw', 'absl', 'pcdisp'): ins.targets = [ea.target]
                return pos
        raise Invalid('line4')

    # ---------------------------------------------------------------- line 5
    def line5(self, ins, op, pos):
        mode = (op >> 3) & 7; reg = op & 7
        szb = (op >> 6) & 3
        if szb == 3:
            cond = (op >> 8) & 0xF
            if mode == 1:
                d = s16(self.w(pos))
                t = (pos + d) & 0xFFFFFF
                ins.mnem = 'db' + {'f': 'f', 't': 't'}.get(CC[cond], CC[cond])
                if cond == 1: ins.mnem = 'dbra'
                ins.ops = [Op('dn', reg='d%d' % reg), Op('branch', target=t, ext=2, extlen=2)]
                ins.flow = 'branch'; ins.targets = [t]
                return pos + 2
            ea, pos = self.ea(ins, pos, mode, reg, 'b', self.DALT)
            ins.mnem = 's' + CC[cond]; ins.ops = [ea]
            return pos
        q = (op >> 9) & 7
        q = 8 if q == 0 else q
        sz = SZ[szb]
        if mode == 1 and sz == 'b':
            raise Invalid('addq.b an')
        ea, pos = self.ea(ins, pos, mode, reg, sz, self.ALT)
        ins.mnem = ('subq.' if op & 0x100 else 'addq.') + sz
        ins.ops = [Op('imm', value=q, size='q'), ea]
        return pos

    # ---------------------------------------------------------------- line 6
    def line6(self, ins, op, pos):
        cond = (op >> 8) & 0xF
        d = op & 0xFF
        if d == 0:
            disp = s16(self.w(pos)); sfx = '.w'; t = (pos + disp) & 0xFFFFFF; pos += 2
        elif d == 0xFF:
            raise Invalid('bra.l (68020)')
        else:
            disp = s8(d); sfx = '.s'; t = (pos + disp) & 0xFFFFFF
        if cond == 0:
            ins.mnem = 'bra' + sfx; ins.flow = 'jump'
        elif cond == 1:
            ins.mnem = 'bsr' + sfx; ins.flow = 'call'
        else:
            ins.mnem = 'b' + CC[cond] + sfx; ins.flow = 'branch'
        ins.ops = [Op('branch', target=t, size=sfx, ext=2 if sfx == '.w' else None, extlen=2 if sfx == '.w' else 0)]
        ins.targets = [t]
        return pos

    # ---------------------------------------------------------------- line 7
    def line7(self, ins, op, pos):
        if op & 0x100:
            raise Invalid('moveq bit8')
        ins.mnem = 'moveq'
        ins.ops = [Op('imm', value=s8(op & 0xff), size='q'), Op('dn', reg='d%d' % ((op >> 9) & 7))]
        return pos

    # ------------------------------------------------- arithmetic helpers
    def _arith(self, ins, op, pos, name, allow_an_src=True, adda=None, x=None, logical=False):
        mode = (op >> 3) & 7; reg = op & 7
        dn = (op >> 9) & 7
        opm = (op >> 6) & 7
        if opm in (3, 7):
            if adda is None:
                raise Invalid('no adda')
            sz = 'w' if opm == 3 else 'l'
            ea, pos = self.ea(ins, pos, mode, reg, sz, self.ALL)
            ins.mnem = adda + '.' + sz; ins.ops = [ea, Op('an', reg=areg(dn))]
            return pos
        sz = SZ[opm & 3]
        if opm < 4:  # ea -> Dn
            allowed = self.ALL if (allow_an_src and sz != 'b') else self.DATA
            ea, pos = self.ea(ins, pos, mode, reg, sz, allowed)
            ins.mnem = name + '.' + sz; ins.ops = [ea, Op('dn', reg='d%d' % dn)]
            return pos
        # Dn -> ea
        if mode in (0, 1):
            if x is None:
                raise Invalid('x form')
            if name == 'eor':  # eor Dn,Dn has mode 0
                pass
            else:
                ins.mnem = x + '.' + sz
                if mode == 0:
                    ins.ops = [Op('dn', reg='d%d' % reg), Op('dn', reg='d%d' % dn)]
                else:
                    ins.ops = [Op('predec', reg=areg(reg)), Op('predec', reg=areg(dn))]
                return pos
        ea, pos = self.ea(ins, pos, mode, reg, sz, self.MALT if name != 'eor' else self.DALT)
        ins.mnem = name + '.' + sz; ins.ops = [Op('dn', reg='d%d' % dn), ea]
        return pos

    # ---------------------------------------------------------------- line 8
    def line8(self, ins, op, pos):
        opm = (op >> 6) & 7; mode = (op >> 3) & 7; reg = op & 7; dn = (op >> 9) & 7
        if opm == 3 or opm == 7:
            ea, pos = self.ea(ins, pos, mode, reg, 'w', self.DATA)
            ins.mnem = 'divu.w' if opm == 3 else 'divs.w'; ins.ops = [ea, Op('dn', reg='d%d' % dn)]
            return pos
        if opm == 4 and mode in (0, 1):
            ins.mnem = 'sbcd'
            ins.ops = [Op('dn', reg='d%d' % reg), Op('dn', reg='d%d' % dn)] if mode == 0 else \
                [Op('predec', reg=areg(reg)), Op('predec', reg=areg(dn))]
            return pos
        if opm >= 4 and mode in (0, 1):
            raise Invalid('pack/unpk')
        return self._arith(ins, op, pos, 'or', allow_an_src=False)

    # ---------------------------------------------------------------- line 9 / D
    def line9(self, ins, op, pos):
        return self._arith(ins, op, pos, 'sub', adda='suba', x='subx')

    def lineD(self, ins, op, pos):
        return self._arith(ins, op, pos, 'add', adda='adda', x='addx')

    # ---------------------------------------------------------------- line B
    def lineB(self, ins, op, pos):
        opm = (op >> 6) & 7; mode = (op >> 3) & 7; reg = op & 7; dn = (op >> 9) & 7
        if opm in (3, 7):
            sz = 'w' if opm == 3 else 'l'
            ea, pos = self.ea(ins, pos, mode, reg, sz, self.ALL)
            ins.mnem = 'cmpa.' + sz; ins.ops = [ea, Op('an', reg=areg(dn))]
            return pos
        sz = SZ[opm & 3]
        if opm < 4:
            ea, pos = self.ea(ins, pos, mode, reg, sz, self.ALL if sz != 'b' else self.DATA)
            ins.mnem = 'cmp.' + sz; ins.ops = [ea, Op('dn', reg='d%d' % dn)]
            return pos
        if mode == 1:
            ins.mnem = 'cmpm.' + sz; ins.ops = [Op('postinc', reg=areg(reg)), Op('postinc', reg=areg(dn))]
            return pos
        ea, pos = self.ea(ins, pos, mode, reg, sz, self.DALT)
        ins.mnem = 'eor.' + sz; ins.ops = [Op('dn', reg='d%d' % dn), ea]
        return pos

    # ---------------------------------------------------------------- line C
    def lineC(self, ins, op, pos):
        opm = (op >> 6) & 7; mode = (op >> 3) & 7; reg = op & 7; dn = (op >> 9) & 7
        if opm in (3, 7):
            ea, pos = self.ea(ins, pos, mode, reg, 'w', self.DATA)
            ins.mnem = 'mulu.w' if opm == 3 else 'muls.w'; ins.ops = [ea, Op('dn', reg='d%d' % dn)]
            return pos
        if opm == 4 and mode in (0, 1):
            ins.mnem = 'abcd'
            ins.ops = [Op('dn', reg='d%d' % reg), Op('dn', reg='d%d' % dn)] if mode == 0 else \
                [Op('predec', reg=areg(reg)), Op('predec', reg=areg(dn))]
            return pos
        if opm == 5 and mode == 0:
            ins.mnem = 'exg'; ins.ops = [Op('dn', reg='d%d' % dn), Op('dn', reg='d%d' % reg)]; return pos
        if opm == 5 and mode == 1:
            ins.mnem = 'exg'; ins.ops = [Op('an', reg=areg(dn)), Op('an', reg=areg(reg))]; return pos
        if opm == 6 and mode == 1:
            ins.mnem = 'exg'; ins.ops = [Op('dn', reg='d%d' % dn), Op('an', reg=areg(reg))]; return pos
        if opm >= 4 and mode in (0, 1):
            raise Invalid('lineC')
        return self._arith(ins, op, pos, 'and', allow_an_src=False)

    # ---------------------------------------------------------------- line E
    def lineE(self, ins, op, pos):
        names = ['as', 'ls', rox := 'rox', 'ro']
        szb = (op >> 6) & 3
        d = 'l' if op & 0x100 else 'r'
        if szb == 3:
            t = (op >> 9) & 7
            if t > 3:
                raise Invalid('bitfield')
            mode = (op >> 3) & 7; reg = op & 7
            ea, pos = self.ea(ins, pos, mode, reg, 'w', self.MALT)
            ins.mnem = names[t] + d + '.w'; ins.ops = [ea]
            return pos
        t = (op >> 3) & 3
        cnt = (op >> 9) & 7
        sz = SZ[szb]
        if op & 0x20:
            src = Op('dn', reg='d%d' % cnt)
        else:
            src = Op('imm', value=8 if cnt == 0 else cnt, size='q')
        ins.mnem = names[t] + d + '.' + sz
        ins.ops = [src, Op('dn', reg='d%d' % (op & 7))]
        return pos

    def lineA(self, ins, op, pos):
        raise Invalid('line A')

    def lineF(self, ins, op, pos):
        raise Invalid('line F')


def reglist_str(mask, predec):
    if predec:
        mask = int('{:016b}'.format(mask)[::-1], 2)
    regs = [('d%d' % i) for i in range(8)] + [('a%d' % i) for i in range(8)]
    parts = []
    i = 0
    while i < 16:
        if mask >> i & 1:
            j = i
            while j + 1 < 16 and (mask >> (j + 1)) & 1 and (j + 1) // 8 == i // 8:
                j += 1
            name = lambda k: 'sp' if k == 15 else regs[k]
            parts.append(name(i) if i == j else '%s-%s' % (name(i), name(j)))
            i = j + 1
        else:
            i += 1
    return '/'.join(parts)
