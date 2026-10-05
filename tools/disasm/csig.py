#!/usr/bin/env python3
"""C prototypes of the functions shared between C and the original code.

The original compiler used 16-bit int: every stack argument is a word
(char / short / int) or a long (long / pointer), and the caller pops.
The C code is compiled with normal 32-bit int, where every argument takes a
4-byte slot.  The generator builds adapters in both directions from these
prototypes:
    ret name(args) C_IMPL(label);        C replacing an original routine
    extern ret name(args) ASM(label);    original routine called from C
Only the argument sizes matter: 'w' (word) or 'l' (long)."""
import os, re, glob

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

WORD = {'s8', 'u8', 's16', 'u16', 'char', 'short', 'int', 'unsigned', 'signed', 'bool'}
LONG = {'s32', 'u32', 'long'}

DECL = re.compile(r'([A-Za-z_][\w\s\*]*?)\b(\w+)\s*\(([^;{)]*)\)\s*(C_IMPL|ASM)\((\w+)\)\s*;', re.S)


def arg_size(a):
    a = a.strip()
    if not a or a == 'void':
        return None
    if '*' in a or '(' in a:
        return 'l'
    words = set(re.findall(r'\w+', a))
    if words & LONG:
        return 'l'
    if words & WORD:
        return 'w'
    return 'l'          # typedef'd pointers / structs by pointer


def ret_kind(t):
    t = t.replace('extern', '').replace('static', '').replace('inline', '').strip()
    if '*' in t:
        return 'p'
    w = set(re.findall(r'\w+', t))
    if 'void' in w:
        return 'v'
    if w & LONG:
        return 'l'
    if w & {'s8', 'u8', 'char'}:
        return 'b'
    return 'w'


def load(srcdir=None):
    """label -> (kind 'C_IMPL'|'ASM', ret kind, [arg sizes])"""
    srcdir = srcdir or os.path.join(ROOT, 'src', 'c')
    out = {}
    for f in sorted(glob.glob(os.path.join(srcdir, '*.[ch]'))):
        txt = open(f).read()
        txt = re.sub(r'/\*.*?\*/', '', txt, flags=re.S)
        txt = re.sub(r'//[^\n]*', '', txt)
        for m in DECL.finditer(txt):
            ret, name, args, kind, label = m.groups()
            if 'typedef' in ret or '#define' in ret:
                continue
            sizes = [s for s in (arg_size(a) for a in args.split(',')) if s]
            out.setdefault((kind, label), (ret_kind(ret), sizes))
    return out


if __name__ == '__main__':
    for (k, lab), (r, a) in sorted(load().items()):
        print('%-7s %-28s %s %s' % (k, lab, r, ''.join(a)))
