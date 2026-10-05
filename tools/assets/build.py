#!/usr/bin/env python3
"""Build binary asset blobs from the editable files in assets/.

usage: build.py [outdir]     (default build/assets)

For every entry of assets/manifest.json writes <outdir>/<name>.bin, which the
assembly includes with .incbin.  Unmodified assets reproduce the original ROM
bytes exactly; modified ones are re-encoded (LCW graphics are recompressed,
GEMS sample headers are rewritten if sample sizes changed).
"""
import sys, os, json, struct, wave
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import lcw
from gfx import read_png


def read_pal(path):
    words = []
    for line in open(path):
        line = line.split(';')[0].strip()
        if line:
            words += [int(x, 16) for x in line.split()]
    assert len(words) == 64, '%s: need 64 colour words' % path
    return struct.pack('>64H', *words)


def read_wav(path):
    with wave.open(path, 'rb') as w:
        assert w.getsampwidth() == 1 and w.getnchannels() == 1, '%s: must be 8-bit mono' % path
        return w.readframes(w.getnframes())


def gems_samples(m, adir):
    header = bytearray(open(os.path.join(adir, m['header']), 'rb').read())
    body = bytearray(header)
    moved = {}
    for seg in m['segments']:
        data = read_wav(os.path.join(adir, seg['file']))
        new_off = len(body)
        if new_off != seg['offset'] or len(data) != seg['size']:
            moved[seg['offset']] = (new_off, len(data) - seg['size'])
        body += data
    if moved:
        # rewrite start positions (and lengths of samples whose segment was resized)
        for i in range(m['count']):
            o = i * 12
            fl, slsb, smsb, skip, ln, loop, endv = struct.unpack('<BHBHHHH', header[o:o + 12])
            st = (smsb << 16) | slsb
            if st in moved:
                nst, dl = moved[st]
                ln = max(0, min(0xFFFF, ln + dl))
                struct.pack_into('<BHBHHHH', body, o, fl, nst & 0xFFFF, nst >> 16, skip, ln, loop, endv)
    return bytes(body)


def build_one(m, adir):
    k = m['kind']
    if k == 'bin':
        return open(os.path.join(adir, m['file']), 'rb').read()
    if k == 'palette':
        return read_pal(os.path.join(adir, m['file']))
    if k == 'tiles':
        return read_png(os.path.join(adir, m['file']))
    if k == 'lcw_tiles':
        tiles = read_png(os.path.join(adir, m['file']))
        orig = open(os.path.join(adir, m['orig']), 'rb').read()
        if lcw.decompress(orig)[0] == tiles:
            return orig
        return lcw.compress(tiles)
    if k == 'gems_samples':
        return gems_samples(m, adir)
    raise ValueError(k)


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'build', 'assets')
    adir = os.path.join(ROOT, 'assets')
    os.makedirs(out, exist_ok=True)
    man = json.load(open(os.path.join(adir, 'manifest.json')))
    changed = 0
    for m in man:
        data = build_one(m, adir)
        if len(data) != m['end'] - m['start']:
            changed += 1
            print('note: %s is now %d bytes (was %d)' % (m['name'], len(data), m['end'] - m['start']))
        fn = os.path.join(out, m['name'] + '.bin')
        if not os.path.exists(fn) or open(fn, 'rb').read() != data:
            open(fn, 'wb').write(data)
    print('built %d assets%s' % (len(man), (', %d resized' % changed) if changed else ''))


if __name__ == '__main__':
    main()
