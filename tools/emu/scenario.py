"""Deterministic input scenarios used for regression / shift tests.

A scenario is a list of (buttons, frames).  run_scenario() plays it on an
Emu and returns per-sample frame hashes (+ an audio hash) so two ROM builds
can be compared.
"""
import hashlib, random


def boot_to_mission(house_moves=0):
    """Boot, title, house select, mentat briefing, into mission 1."""
    s = [((), 700), (('START',), 4), ((), 120), (('START',), 4), ((), 120), (('START',), 4), ((), 120),
         (('START',), 4), ((), 120)]
    for _ in range(house_moves):
        s += [(('RIGHT',), 4), ((), 20)]
    for _ in range(5):
        s += [(('C',), 4), ((), 200)]
    for _ in range(10):
        s += [(('C',), 4), ((), 150)]
    s += [(('A',), 4), ((), 1200)]
    return s


GRID = ['ABCDEFGHIJ', 'KLMNOPQRST', 'UVWXYZ<>E']


def enter_password(pw):
    """From boot: title -> OPTIONS -> ENTER PASSWORD, type pw, END, then
    click through the briefing into the mission."""
    s = [((), 700), (('START',), 4), ((), 120), (('START',), 4), ((), 120), (('START',), 4), ((), 120),
         (('DOWN',), 4), ((), 30), (('C',), 4), ((), 120)]
    s += [(('DOWN',), 4), ((), 10)] * 6 + [(('C',), 4), ((), 90)]
    r, c = 0, 0
    def goto(tr, tc):
        out = []
        nonlocal r, c
        while r < tr: out += [(('DOWN',), 4), ((), 6)]; r += 1
        while r > tr: out += [(('UP',), 4), ((), 6)]; r -= 1
        while c < tc: out += [(('RIGHT',), 4), ((), 6)]; c += 1
        while c > tc: out += [(('LEFT',), 4), ((), 6)]; c -= 1
        return out
    for ch in pw:
        tr = next(i for i, row in enumerate(GRID) if ch in row)
        s += goto(tr, GRID[tr].index(ch)) + [(('C',), 4), ((), 10)]
    # after the 10th letter the cursor jumps to END by itself
    s += [((), 20), (('C',), 4), ((), 300)]
    for _ in range(14):
        s += [(('C',), 4), ((), 150)]
    s += [(('A',), 4), ((), 1200)]
    return s


PASSWORDS = ('DEMOLITION DIPLOMATIC DOMINATION SPICESATYR SPICEDANCE SPICESABRE BURNINGSUN ETERNALSUN '
             'ARRAKISSUN DARKHUNTER DEFTHUNTER COLDHUNTER EVILMENTAT FAIRMENTAT WILYMENTAT ITSJOEBWAN '
             'ASHLIKENNY SLYMELANIE DEVASTATOR SONICBLAST STEALTHWAR DEATHRULER DUNERUNNER POWERCRUSH '
             'DUNEFINALE SANDIMPACT SPICEMAKER HEATINGSUN FATEHUNTER FREEMENTAT LIBERATION FREMENRUSH '
             'GREATJIHAD REINFORCES SPICESOLAR KILLINGSUN STARHUNTER KINGMENTAT BURSEGDUTY SARDAUKARS '
             'TOTALCHAOS').split()


def monkey(frames, seed):
    rng = random.Random(seed)
    names = ['A', 'B', 'C', 'X', 'Y', 'Z', 'UP', 'DOWN', 'LEFT', 'RIGHT', 'START', 'MODE']
    weights = [8, 5, 8, 3, 3, 2, 6, 6, 6, 6, 0.3, 0.5]
    s, f = [], 0
    while f < frames:
        btns = rng.choices(names, weights, k=rng.choice([1, 1, 1, 2]))
        if 'START' in btns and rng.random() < 0.5:
            btns.remove('START')
        hold = rng.choice([2, 4, 8, 20, 60])
        rel = rng.choice([2, 10, 30])
        s += [(tuple(btns), hold), ((), rel)]
        f += hold + rel
    return s


SCENARIOS = {
    'boot': lambda: [((), 3000)],
    'mission1': lambda: boot_to_mission() + monkey(20000, 1),
    'menus': lambda: [((), 700)] + monkey(20000, 2),
    'ordos': lambda: boot_to_mission(1) + monkey(20000, 3),
    'long': lambda: boot_to_mission(2) + monkey(60000, 4),
    'pw_late': lambda: enter_password('POWERCRUSH') + monkey(20000, 5),
}
for _i, _pw in enumerate(PASSWORDS):
    SCENARIOS['pw_' + _pw.lower()] = (lambda pw=_pw, i=_i: enter_password(pw) + monkey(15000, 100 + i))


def run_scenario(emu, scen, every=10, shots=None):
    """Returns (list of frame hashes, audio hash)."""
    emu.record_audio = True
    emu.audio_hash = hashlib.sha1()
    hashes = []
    f = 0
    for btns, n in scen:
        emu.set_buttons(*btns)
        for _ in range(n):
            emu.run(1)
            f += 1
            if f % every == 0:
                hashes.append(emu.frame_hash())
            if shots is not None and f in shots:
                emu.screenshot(shots[f])
    ah = emu.audio_hash.hexdigest()[:16]
    return hashes, ah
