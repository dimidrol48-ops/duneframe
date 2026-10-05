"""Interactive exploration helpers (import from a python session / script)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'emu'))
from harness import Emu

VARS = {'cursor': (0xC240, 8), 'sel': (0xC25C, 4), 'mode': (0xC264, 6), 'scroll': (0xE3BE, 4)}

def load(rom='baserom.gen', state='build/states/mission1.st'):
    e = Emu(rom)
    e.run(1)
    e.load_state(open(state, 'rb').read())
    return e

def tap(e, *btns, hold=4, wait=12):
    e.set_buttons(*btns); e.run(hold); e.set_buttons(); e.run(wait)

def show(e, tag=''):
    r = e.ram()
    print(tag, ' '.join('%s=%s' % (k, r[a:a + n].hex()) for k, (a, n) in VARS.items()))
