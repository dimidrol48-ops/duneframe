#!/usr/bin/env python3
"""showfunc.py ADDR [ADDR...] : print generated assembly of functions."""
import sys, os, re, glob
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
src = {}
for f in glob.glob(os.path.join(ROOT, 'src', '*.s')):
    src[f] = open(f).read().split('\n')
maxl = int(os.environ.get('MAXL', 60))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from names import NAMES
for arg in sys.argv[1:]:
    a = int(arg, 16)
    pat = re.compile(r'^(\w+_%06X|\w+):' % a)
    for f, lines in src.items():
        for i, l in enumerate(lines):
            if re.match(r'^\w*%06X:' % a, l) or l.startswith('sub_%06X:' % a) or (a in NAMES and l == NAMES[a] + ':'):
                out = [l]
                for l2 in lines[i + 1:i + maxl]:
                    if re.match(r'^sub_[0-9A-F]{6}:', l2) or (l2.endswith(':') and l2[:-1] in NAMES.values()): break
                    out.append(l2)
                print('\n'.join(out)); print('-' * 40)
                break
