#!/usr/bin/env python3
"""Delta-debug a set of candidate data pointers: find which ones, when
treated as pointers, make the shift test fail.
usage: bisect_ptrs.py candidates.txt scenario at_list pad_list"""
import sys, os, subprocess, tempfile
cands = open(sys.argv[1]).read().split()
scen, ats, pads = sys.argv[2], sys.argv[3], sys.argv[4]
def test(disabled):
    fn = os.path.abspath('build/notptrs.txt')
    open(fn, 'w').write('\n'.join(disabled))
    env = dict(os.environ, DIS_NOT_PTRS=fn)
    subprocess.run(['python3', 'tools/disasm/generate.py', 'baserom.gen', 'traces/merged.npz', 'src'], env=env, check=True, capture_output=True)
    r = subprocess.run(['python3', 'tools/shifttest.py', '--at', ats, '--pad', pads, '--data', '--scenario', scen], capture_output=True, text=True)
    ok = 'PASS' in r.stdout
    print('  disable %d -> %s %s' % (len(disabled), 'PASS' if ok else 'FAIL', r.stdout.strip().split('\n')[-1][:60]), flush=True)
    return ok
# find minimal set to disable (bad = set whose removal makes test pass)
if not test(cands):
    print('even disabling all candidates fails'); sys.exit(1)
bad = []
rest = list(cands)
while True:
    if test(bad):
        break
    # binary search for one culprit in rest: smallest prefix whose disabling (with bad) passes
    lo, hi = 0, len(rest)
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if test(bad + rest[:mid]):
            hi = mid
        else:
            lo = mid
    culprit = rest[hi - 1]
    print('culprit', culprit, flush=True)
    bad.append(culprit)
    rest = rest[hi:]
print('BAD:', ' '.join(bad))
