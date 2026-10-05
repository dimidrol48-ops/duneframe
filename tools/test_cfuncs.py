#!/usr/bin/env python3
"""Build one ROM per C function (only that function replaced by its C version)
and compare each with the base ROM on given scenarios."""
import sys, os, re, shutil, subprocess, glob
from multiprocessing import Pool
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, 'emu'))
import shifttest

def build_only(fn, out):
    if os.path.exists(out): shutil.rmtree(out)
    shutil.copytree(os.path.join(ROOT, 'src'), os.path.join(out, 'src'))
    for f in glob.glob(os.path.join(out, 'src', '*.s')):
        t = open(f).read()
        t2 = re.sub(r'\.if NONMATCHING(\t\| replaced by the C version in src/c/\n\tjmp\t\((\w+)_c\)\.l)',
                    lambda m: ('.if 1' if m.group(2) == fn else '.if 0') + m.group(1), t)
        if t2 != t: open(f, 'w').write(t2)
    os.makedirs(os.path.join(out, 'build', 'obj'))
    shutil.copytree(os.path.join(ROOT, 'build', 'assets'), os.path.join(out, 'build', 'assets'))
    subprocess.run(['m68k-linux-gnu-as', '-m68000', '--register-prefix-optional', '-I', 'src', '-I', '.', '-o', 'm.o', 'src/main.s'], cwd=out, check=True)
    objs = [os.path.join(ROOT, 'build', 'mod', 'c', x) for x in os.listdir(os.path.join(ROOT, 'build', 'mod', 'c'))]
    subprocess.run(['m68k-linux-gnu-ld', '-T', os.path.join(ROOT, 'rom.ld'), '-o', 'r.elf', 'm.o'] + objs, cwd=out, check=True, capture_output=True)
    subprocess.run(['m68k-linux-gnu-objcopy', '-O', 'binary', '-j', '.text', 'r.elf', 'r.gen'], cwd=out, check=True)
    return os.path.join(out, 'r.gen')

def job(args):
    fn, scen = args
    rom = os.path.join(ROOT, 'build', 'ctest', fn, 'r.gen')
    first, n, audio = shifttest.compare(os.path.join(ROOT, 'baserom.gen'), rom, scen)
    return fn, scen, first, audio

if __name__ == '__main__':
    fns = sys.argv[1].split(',')
    scens = sys.argv[2].split(',')
    for fn in fns: build_only(fn, os.path.join(ROOT, 'build', 'ctest', fn))
    with Pool(4) as p:
        for fn, scen, first, audio in p.imap_unordered(job, [(f, s) for f in fns for s in scens]):
            print('%-22s %-14s %s' % (fn, scen, 'identical' if first is None and audio else 'differs at %s%s' % (None if first is None else first * 10, '' if audio else ' (audio)')), flush=True)
