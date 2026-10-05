#!/usr/bin/env python3
"""Build a test variant of the ROM into its own directory, without touching
build/: any combination of the build switches, and C replacements switched
off one by one (for bisecting a C routine that misbehaves).

usage: buildvariant.py OUTDIR [--wide] [--mods] [--no-c] [--testhw]
                       [--autoplay DIR] [--disable L1,L2,..] [--only L1,L2,..]

  --no-c        NONMATCHING=0 (original code; with --autoplay/--testhw: the
                original ROM plus test hooks)
  --autoplay D  AUTOPLAY=1 with D/autoplay.bin (tools/autoplay.py)
  --testhw      the 480x464 build passes its emulator check on stock
                emulators (logic tests only)
  --disable     keep these C-replaced routines in assembly
  --only        replace only these routines with C

Writes OUTDIR/rom.gen and OUTDIR/dune2.elf (OUTDIR/src is a patched copy of
src/).  Prints the routines that use their C version."""
import sys, os, shutil, subprocess, glob, argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFLAGS = ('-m68000 -mstrict-align -fno-store-merging -fno-strict-aliasing -fno-delete-null-pointer-checks '
          '-O2 -fomit-frame-pointer -fcall-used-d2 -fno-ivopts -fno-pic -ffreestanding -fno-builtin '
          '-fno-common -nostdlib -Wall').split()
MARK = '.if NONMATCHING\t| replaced by the C version'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('out')
    ap.add_argument('--wide', action='store_true')
    ap.add_argument('--mods', action='store_true')
    ap.add_argument('--no-c', action='store_true')
    ap.add_argument('--testhw', action='store_true')
    ap.add_argument('--autoplay')
    ap.add_argument('--disable', default='')
    ap.add_argument('--only', default='')
    a = ap.parse_args()
    os.chdir(ROOT)
    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    src = os.path.join(out, 'src')
    if os.path.exists(src):
        shutil.rmtree(src)
    shutil.copytree('src', src)
    disable = {x for x in a.disable.split(',') if x}
    only = {x for x in a.only.split(',') if x}
    used = []
    for f in sorted(glob.glob(os.path.join(src, 'code_*.s'))):
        L = open(f).read().split('\n')
        changed = False
        for i, l in enumerate(L):
            if l.startswith(MARK):
                name = L[i - 1].rstrip(':')
                if name in disable or (only and name not in only):
                    L[i] = '.if 0\t| C version switched off (buildvariant.py)'
                    changed = True
                else:
                    used.append(name)
        if changed:
            open(f, 'w').write('\n'.join(L))
    nm = '0' if a.no_c else '1'
    syms = {'NONMATCHING': nm, 'MODS': '1' if a.mods else '0', 'WIDE': '1' if a.wide else '0',
            'AUTOPLAY': '1' if a.autoplay else '0', 'TESTHW': '1' if a.testhw else '0'}
    cmd = ['m68k-linux-gnu-as', '-m68000', '--register-prefix-optional', '-I', src, '-I', ROOT]
    if a.autoplay:
        cmd += ['-I', os.path.abspath(a.autoplay)]
    for k, v in syms.items():
        cmd += ['--defsym', '%s=%s' % (k, v)]
    if not os.path.exists('build/assets/.stamp'):
        subprocess.check_call(['make', 'build/assets/.stamp'])
    objs = [os.path.join(out, 'main.o')]
    subprocess.check_call(cmd + ['-o', objs[0], os.path.join(src, 'main.s')])
    if nm == '1' or a.mods:
        for c in sorted(glob.glob('src/c/*.c')):
            o = os.path.join(out, os.path.basename(c)[:-2] + '.o')
            subprocess.check_call(['m68k-linux-gnu-gcc'] + CFLAGS + ['-Isrc/c', '-DMODS=' + syms['MODS'],
                                  '-DWIDE=' + syms['WIDE'], '-DAUTOPLAY=' + syms['AUTOPLAY'], '-c', '-o', o, c])
            objs.append(o)
    r = subprocess.run(['m68k-linux-gnu-ld', '-T', 'rom.ld', '-o', os.path.join(out, 'dune2.elf')] + objs,
                       capture_output=True, text=True)
    errs = [l for l in r.stderr.split('\n') if l and 'GNU-stack' not in l and 'NOTE' not in l]
    if r.returncode:
        sys.exit('\n'.join(errs))
    subprocess.check_call(['m68k-linux-gnu-objcopy', '-O', 'binary', '-j', '.text',
                           os.path.join(out, 'dune2.elf'), os.path.join(out, 'rom.gen')])
    if nm == '1' or a.mods:
        subprocess.run([sys.executable, 'tools/fixheader.py', os.path.join(out, 'rom.gen')], capture_output=True)
    print('%s: %d routines in C%s' % (os.path.join(a.out, 'rom.gen'), len(used) if nm == '1' else 0,
                                      (': ' + ' '.join(used)) if nm == '1' and (disable or only) else ''))


if __name__ == '__main__':
    main()
