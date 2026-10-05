#!/usr/bin/env python3
"""Relocatability test.

Builds a copy of the sources with N padding bytes inserted before the label
at (or after) ADDR, then runs the original and the shifted ROM through the
same input scenario and compares video frame hashes and audio.

usage: shifttest.py [--at 0x1234] [--pad 64] [--scenario mission1] [--ref rom]
"""
import argparse, os, re, shutil, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, 'emu'))


INSERTED = []


def build_shifted(ats, pads, outdir, data_flags):
    src = os.path.join(ROOT, 'src')
    if os.path.exists(outdir):
        shutil.rmtree(outdir)
    shutil.copytree(src, os.path.join(outdir, 'src'))
    files = open(os.path.join(src, 'files.txt')).read().split()
    for at, pad, data_ok in zip(ats, pads, data_flags):
        done = False
        for f in files:
            p = os.path.join(outdir, 'src', f + '.s')
            lines = open(p).read().split('\n')
            prev = ''
            for i, l in enumerate(lines):
                m = re.match(r'^(sub|loc|dat|jtbl)_([0-9A-F]{6}):', l)
                if m and int(m.group(2), 16) >= at and ((m.group(1) == 'sub' and
                        re.match(r'\s+(rts|rte|bra\.[sw]|jmp)\b', prev)) or (data_ok and m.group(1) == 'dat')):
                    lines.insert(i, '\t.fill\t%d,1,0xFF\t| shift test padding' % pad)
                    print('padding %d bytes before %s (%s:%d)' % (pad, l.strip(), f, i + 1))
                    INSERTED.append((int(m.group(2), 16), pad))
                    done = True
                    break
                if l.strip() and not l.startswith('\t.globl') and not l.strip().endswith(':'):
                    prev = l
            if done:
                open(p, 'w').write('\n'.join(lines))
                break
        assert done, 'no insertion point'
    os.makedirs(os.path.join(outdir, 'build', 'obj'), exist_ok=True)
    if os.path.isdir(os.path.join(ROOT, 'build', 'assets')):
        shutil.copytree(os.path.join(ROOT, 'build', 'assets'), os.path.join(outdir, 'build', 'assets'), dirs_exist_ok=True)
    ld = open(os.path.join(ROOT, 'rom.ld')).read()
    open(os.path.join(outdir, 'rom.ld'), 'w').write(ld)
    subprocess.run(['m68k-linux-gnu-as', '-m68000', '--register-prefix-optional', '-I', 'src', '-o',
                    'build/obj/main.o', 'src/main.s'], cwd=outdir, check=True)
    subprocess.run(['m68k-linux-gnu-ld', '-T', 'rom.ld', '-o', 'rom.elf', 'build/obj/main.o'], cwd=outdir, check=True)
    subprocess.run(['m68k-linux-gnu-objcopy', '-O', 'binary', '-j', '.text', 'rom.elf', 'rom.gen'], cwd=outdir, check=True)
    return os.path.join(outdir, 'rom.gen')


def compare(rom_a, rom_b, scen_name, every=10):
    from harness import Emu
    from scenario import SCENARIOS, run_scenario
    res = []
    for r in (rom_a, rom_b):
        e = Emu(r)
        res.append(run_scenario(e, SCENARIOS[scen_name](), every))
        last = e
        e.close()
    (ha, aa), (hb, ab) = res
    first = next((i for i, (x, y) in enumerate(zip(ha, hb)) if x != y), None)
    return first, len(ha), aa == ab


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--at', default='0x200', help='comma list of insertion addresses')
    ap.add_argument('--pad', default='64', help='comma list of pad sizes')
    ap.add_argument('--scenario', default='mission1')
    ap.add_argument('--ref', default=os.path.join(ROOT, 'baserom.gen'))
    ap.add_argument('--data', action='store_true', help='allow inserting before a data label')
    ap.add_argument('--out', default=os.path.join(ROOT, 'build', 'shift'))
    a = ap.parse_args()
    ats = [int(x, 0) for x in a.at.split(',')]
    pads = [int(x, 0) for x in a.pad.split(',')]
    rom = build_shifted(ats, pads, a.out, [a.data or at >= 0x24000 for at in ats])
    import json
    json.dump(INSERTED, open(os.path.join(a.out, 'inserted.json'), 'w'))
    print('shifted rom size %d' % os.path.getsize(rom))
    first, n, audio_ok = compare(a.ref, rom, a.scenario)
    if first is None and audio_ok:
        print('PASS: %d samples identical, audio identical' % n)
    else:
        print('FAIL: first video mismatch at sample %s (frame %s), audio %s' %
              (first, None if first is None else first * 10, 'ok' if audio_ok else 'DIFFERS'))
        sys.exit(1)


if __name__ == '__main__':
    main()
