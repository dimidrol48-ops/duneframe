"""Headless Genesis emulator harness (libretro Genesis Plus GX core via ctypes).

Used for: automated testing of rebuilt ROMs (screenshots, frame hashes),
input scripting, and collecting execution/data-read traces from the
patched core (see tools/emu/gpgx_trace.patch).
"""
import ctypes as C
import os, hashlib, tempfile
import numpy as np

# Genesis pad buttons -> RetroPad bits (as mapped by the GPGX libretro core, 6-button pad)
BTN = {
    'B': 0, 'A': 1, 'MODE': 2, 'START': 3, 'UP': 4, 'DOWN': 5, 'LEFT': 6, 'RIGHT': 7,
    'C': 8, 'Y': 9, 'X': 10, 'Z': 11,
}

class retro_game_info(C.Structure):
    _fields_ = [('path', C.c_char_p), ('data', C.c_void_p), ('size', C.c_size_t), ('meta', C.c_char_p)]

class retro_variable(C.Structure):
    _fields_ = [('key', C.c_char_p), ('value', C.c_char_p)]

ENV_CB = C.CFUNCTYPE(C.c_bool, C.c_uint, C.c_void_p)
VIDEO_CB = C.CFUNCTYPE(None, C.c_void_p, C.c_uint, C.c_uint, C.c_size_t)
AUDIO_CB = C.CFUNCTYPE(None, C.c_int16, C.c_int16)
AUDIOB_CB = C.CFUNCTYPE(C.c_size_t, C.POINTER(C.c_int16), C.c_size_t)
POLL_CB = C.CFUNCTYPE(None)
STATE_CB = C.CFUNCTYPE(C.c_int16, C.c_uint, C.c_uint, C.c_uint, C.c_uint)

DEFAULT_CORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'build', 'genesis_plus_gx_libretro.so')

class Emu:
    def __init__(self, rom_path, core_path=None, options=None, record_audio=False, mouse=False):
        core_path = core_path or os.environ.get('GPGX_CORE', DEFAULT_CORE)
        # each instance gets its own copy of the .so so globals (trace buffers) are separate
        tmp = tempfile.NamedTemporaryFile(suffix='.so', delete=False)
        tmp.write(open(core_path, 'rb').read()); tmp.close()
        self._sopath = tmp.name
        self.lib = C.CDLL(tmp.name)
        self.options = {
            b'genesis_plus_gx_system_hw': b'mega drive / genesis',
            b'genesis_plus_gx_region_detect': b'ntsc-u',
            b'genesis_plus_gx_bram': b'per game',
        }
        if options:
            self.options.update({k.encode(): v.encode() for k, v in options.items()})
        self._vals = {}
        self.sysdir = tempfile.mkdtemp()
        self._sysdir_c = C.c_char_p(self.sysdir.encode())
        self.pad = 0
        self.frame = None
        self.width = self.height = 0
        self.record_audio = record_audio
        self.audio = []
        self.audio_hash = None
        self._keep = [ENV_CB(self._env), VIDEO_CB(self._video), AUDIO_CB(lambda l, r: None),
                      AUDIOB_CB(self._audio), POLL_CB(lambda: None), STATE_CB(self._state)]
        L = self.lib
        L.retro_set_environment(self._keep[0])
        L.retro_init()
        L.retro_set_video_refresh(self._keep[1])
        L.retro_set_audio_sample(self._keep[2])
        L.retro_set_audio_sample_batch(self._keep[3])
        L.retro_set_input_poll(self._keep[4])
        L.retro_set_input_state(self._keep[5])
        self.rom = open(rom_path, 'rb').read()
        self._romdata = C.create_string_buffer(self.rom, len(self.rom))
        gi = retro_game_info(rom_path.encode(), C.cast(self._romdata, C.c_void_p), len(self.rom), None)
        if not L.retro_load_game(C.byref(gi)):
            raise RuntimeError('load failed')
        L.retro_set_controller_port_device(0, 0x201)  # 6-button pad
        self.mouse_state = [0, 0, 0]                   # dx, dy, buttons (1 L, 2 R, 4 middle, 8 start)
        if mouse:
            L.retro_set_controller_port_device(1, 2)   # Sega Mouse on port 2
        L.retro_get_memory_data.restype = C.c_void_p
        L.retro_get_memory_size.restype = C.c_size_t
        L.retro_serialize_size.restype = C.c_size_t
        try:
            L.retro_trace_get.restype = C.c_void_p
            self.has_trace = True
        except AttributeError:
            self.has_trace = False

    # --- callbacks
    def _env(self, cmd, data):
        cmd &= 0xFFFF
        if cmd == 10:  # SET_PIXEL_FORMAT
            return C.cast(data, C.POINTER(C.c_int))[0] in (1, 2)
        if cmd in (9, 31):  # system / save dir
            C.cast(data, C.POINTER(C.c_char_p))[0] = self._sysdir_c.value
            return True
        if cmd == 15:  # GET_VARIABLE
            v = C.cast(data, C.POINTER(retro_variable))[0]
            key = v.key
            if key in self.options:
                buf = self._vals.setdefault(key, C.c_char_p(self.options[key]))
                C.cast(data, C.POINTER(retro_variable))[0].value = buf.value
                return True
            return False
        if cmd == 3:  # GET_CAN_DUPE
            C.cast(data, C.POINTER(C.c_bool))[0] = True
            return True
        return False

    def _video(self, data, w, h, pitch):
        if not data:
            return
        buf = C.string_at(data, pitch * h)
        a = np.frombuffer(buf, dtype='<u2').reshape(h, pitch // 2)[:, :w]
        self.frame = a.copy()
        self.width, self.height = w, h

    def _audio(self, data, frames):
        if self.record_audio:
            b = C.string_at(data, frames * 4)
            if self.audio_hash is not None:
                self.audio_hash.update(b)
            else:
                self.audio.append(b)
        return frames

    def _state(self, port, device, index, id):
        if port == 1 and (device & 0xFF) == 2:
            dx, dy, b = self.mouse_state
            return {0: dx, 1: dy, 2: b & 1, 3: (b >> 1) & 1, 5: (b >> 2) & 1, 6: (b >> 3) & 1}.get(id, 0)
        if port != 0:
            return 0
        if id == 256:
            return self.pad
        return 1 if (self.pad >> id) & 1 else 0

    # --- API
    def set_buttons(self, *names):
        m = 0
        for n in names:
            m |= 1 << BTN[n]
        self.pad = m

    def run(self, frames=1):
        for _ in range(frames):
            self.lib.retro_run()
            self.mouse_state[0] = self.mouse_state[1] = 0   # motion is per frame

    def mouse(self, dx=0, dy=0, buttons=None):
        """Mouse input for the next frame: motion in pixels (y down), buttons
        bit 0 left, 1 right, 2 middle (C), 3 start; None keeps the buttons."""
        self.mouse_state[0], self.mouse_state[1] = dx, dy
        if buttons is not None:
            self.mouse_state[2] = buttons

    def press(self, *names, hold=4, release=4):
        self.set_buttons(*names); self.run(hold)
        self.set_buttons(); self.run(release)

    def rgb(self):
        f = self.frame.astype(np.uint32)
        r = ((f >> 11) & 31) * 255 // 31
        g = ((f >> 5) & 63) * 255 // 63
        b = (f & 31) * 255 // 31
        return np.stack([r, g, b], -1).astype(np.uint8)

    def screenshot(self, path):
        from PIL import Image
        Image.fromarray(self.rgb()).save(path)

    def frame_hash(self):
        return hashlib.sha1(self.frame.tobytes()).hexdigest()[:16]

    def ram(self):
        """68k work RAM as big-endian bytes (0xFF0000-0xFFFFFF)."""
        p = self.lib.retro_get_memory_data(2)
        n = self.lib.retro_get_memory_size(2)
        raw = np.frombuffer(C.string_at(p, n), dtype='<u2')
        return raw.astype('>u2').tobytes()

    def poke(self, addr, data):
        """Write bytes into 68k work RAM (addr 0xFFxxxx; RAM is stored as
        little-endian words, so byte addresses are swapped within a word)."""
        p = self.lib.retro_get_memory_data(2)
        for i, b in enumerate(bytes(data)):
            a = ((addr + i) & 0xFFFF) ^ 1
            C.memset(p + a, b, 1)

    def save_state(self):
        n = self.lib.retro_serialize_size()
        buf = C.create_string_buffer(n)
        assert self.lib.retro_serialize(buf, n)
        return buf.raw

    def load_state(self, data):
        buf = C.create_string_buffer(data, len(data))
        assert self.lib.retro_unserialize(buf, len(data))

    def trace(self):
        """Return (exec, read, reader, ramexec) numpy views of the trace buffers."""
        g = self.lib.retro_trace_get
        n = 0x400000
        ex = np.ctypeslib.as_array(C.cast(g(0), C.POINTER(C.c_uint8)), (n,))
        rd = np.ctypeslib.as_array(C.cast(g(1), C.POINTER(C.c_uint8)), (n,))
        who = np.ctypeslib.as_array(C.cast(g(2), C.POINTER(C.c_uint32)), (n // 2,))
        rx = np.ctypeslib.as_array(C.cast(g(3), C.POINTER(C.c_uint8)), (0x10000,))
        return ex, rd, who, rx

    def rclass(self):
        """Per-address classes of 32-bit ROM reads: 1 movea.l, 2 push, 4 move.l->Dn, 8 other."""
        return np.ctypeslib.as_array(C.cast(self.lib.retro_trace_get(5), C.POINTER(C.c_uint8)), (0x400000,))

    def watch(self, lo, hi):
        """Log CPU writes to [lo,hi) (24-bit addresses): see watch_log()."""
        g = self.lib.retro_trace_get
        C.cast(g(7), C.POINTER(C.c_uint32))[0] = lo & 0xFFFFFF
        C.cast(g(8), C.POINTER(C.c_uint32))[0] = hi & 0xFFFFFF
        C.cast(g(9), C.POINTER(C.c_uint32))[0] = 0

    def watch_log(self):
        g = self.lib.retro_trace_get
        n = C.cast(g(9), C.POINTER(C.c_uint32))[0]
        a = np.ctypeslib.as_array(C.cast(g(10), C.POINTER(C.c_uint32)), (4096 * 3,))
        return [(int(a[i*3]), int(a[i*3+1]), int(a[i*3+2])) for i in range(n)]

    def hist(self, on=None):
        """Per-PC instruction execution counts (index = pc>>1). hist(True) clears+enables."""
        g = self.lib.retro_trace_get
        h = np.ctypeslib.as_array(C.cast(g(11), C.POINTER(C.c_uint32)), (0x200000,))
        if on is not None:
            h[:] = 0
            C.cast(g(12), C.POINTER(C.c_int))[0] = 1 if on else 0
        return h

    def pclog(self, on=None):
        """Instruction log: pclog(True) clears+starts; pclog() returns (pcs, cycles) arrays."""
        g = self.lib.retro_trace_get
        if on is not None:
            C.cast(g(14), C.POINTER(C.c_uint32))[0] = 0
            C.cast(g(15), C.POINTER(C.c_int))[0] = 1 if on else 0
            return None
        n = C.cast(g(14), C.POINTER(C.c_uint32))[0]
        a = np.ctypeslib.as_array(C.cast(g(13), C.POINTER(C.c_uint32)), ((1 << 21) * 2,))[:2 * n].copy()
        return a[0::2], a[1::2]

    def rwatch(self, pc):
        """Log data reads made by the instruction at pc (see rwatch_log())."""
        g = self.lib.retro_trace_get
        C.cast(g(16), C.POINTER(C.c_uint32))[0] = pc
        C.cast(g(17), C.POINTER(C.c_uint32))[0] = 0

    def rwatch_log(self):
        g = self.lib.retro_trace_get
        n = C.cast(g(17), C.POINTER(C.c_uint32))[0]
        a = np.ctypeslib.as_array(C.cast(g(18), C.POINTER(C.c_uint32)), ((1 << 20) * 3,))
        return [(int(a[i*3]), int(a[i*3+1]), int(a[i*3+2])) for i in range(n)]

    def reglog(self, i0=None, i1=None):
        """Register log for instruction indices [i0,i1) of the current pclog
        run: reglog(i0,i1) arms it (call before pclog(True)); reglog() returns
        an (n,17) array: pc, d0-d7, a0-a7."""
        g = self.lib.retro_trace_get
        if i0 is not None:
            C.cast(g(20), C.POINTER(C.c_uint32))[0] = 0
            C.cast(g(21), C.POINTER(C.c_uint32))[0] = i0
            C.cast(g(22), C.POINTER(C.c_uint32))[0] = i1
            return None
        n = C.cast(g(20), C.POINTER(C.c_uint32))[0]
        a = np.ctypeslib.as_array(C.cast(g(19), C.POINTER(C.c_uint32)), ((1 << 18) * 17,))
        return a[:n * 17].reshape(n, 17).copy()

    def callwatch(self, pcs):
        """Log all registers whenever execution reaches one of pcs (max 16)."""
        g = self.lib.retro_trace_get
        arr = C.cast(g(23), C.POINTER(C.c_uint32))
        for i in range(16):
            arr[i] = pcs[i] if i < len(pcs) else 0xFFFFFFFF
        C.cast(g(24), C.POINTER(C.c_uint32))[0] = 0

    def callwatch_log(self):
        """(n,17) array: pc, d0-d7, a0-a7 at each hit."""
        g = self.lib.retro_trace_get
        n = C.cast(g(24), C.POINTER(C.c_uint32))[0]
        a = np.ctypeslib.as_array(C.cast(g(25), C.POINTER(C.c_uint32)), ((1 << 16) * 17,))
        return a[:n * 17].reshape(n, 17).copy()

    def snapwatch(self, pcs, max_n=32, stride=1):
        """Record registers + all of work RAM whenever execution reaches one
        of pcs (up to 16; every stride-th hit per pc, up to max_n per pc):
        see snapshots()."""
        if isinstance(pcs, int):
            pcs = [pcs]
        g = self.lib.retro_trace_get
        u = lambda i: C.cast(g(i), C.POINTER(C.c_uint32))
        u(31)[0] = 0
        for k in range(16):
            u(30)[k] = (pcs[k] & 0xFFFFFF) if k < len(pcs) else 0xFFFFFFFF
            u(35)[k] = 0
            u(36)[k] = 0
        u(32)[0] = max_n; u(33)[0] = max(1, stride)
        u(37)[0] = min(pcs) & 0xFFFFFF if pcs else 0xFFFFFFFF
        u(38)[0] = max(pcs) & 0xFFFFFF if pcs else 0

    def snapshots(self):
        """[(pc, regs d0-a7 (16 ints), sr, ram as big-endian bytes)]"""
        g = self.lib.retro_trace_get
        n = C.cast(g(31), C.POINTER(C.c_uint32))[0]
        size = 18 * 4 + 0x10000
        buf = C.string_at(g(34), n * size)
        out = []
        for i in range(n):
            b = buf[i * size:(i + 1) * size]
            w = np.frombuffer(b[:72], '<u4')
            ram = np.frombuffer(b[72:], '<u2').astype('>u2').tobytes()
            out.append((int(w[17]), [int(x) for x in w[:16]], int(w[16]), ram))
        return out

    def vdp(self):
        """Snapshot of VDP memories: (vram bytes big-endian, cram words (9-bit BGR), vsram, regs)."""
        g = self.lib.retro_trace_get
        vr = np.ctypeslib.as_array(C.cast(g(26), C.POINTER(C.c_uint16)), (0x8000,)).astype('>u2').tobytes()
        cr = np.ctypeslib.as_array(C.cast(g(27), C.POINTER(C.c_uint16)), (0x40,)).copy()
        vs = np.ctypeslib.as_array(C.cast(g(28), C.POINTER(C.c_uint16)), (0x40,)).copy()
        rg = bytes(np.ctypeslib.as_array(C.cast(g(29), C.POINTER(C.c_uint8)), (0x20,)))
        return vr, cr, vs, rg

    def free_ranges(self, ranges):
        """Instructions at PCs in these [lo, hi) ranges take no CPU time
        (lockstep --equal-timing)."""
        g = self.lib.retro_trace_get
        rs = sorted(ranges)[:512]
        arr = C.cast(g(39), C.POINTER(C.c_uint32))
        for i, (lo, hi) in enumerate(rs):
            arr[2 * i], arr[2 * i + 1] = lo, hi
        C.cast(g(40), C.POINTER(C.c_uint32))[0] = len(rs)

    def rclass_ram(self):
        """Classes of later uses of ROM longs that were copied to RAM (taint)."""
        return np.ctypeslib.as_array(C.cast(self.lib.retro_trace_get(6), C.POINTER(C.c_uint8)), (0x400000,))

    def close(self):
        try:
            self.lib.retro_unload_game(); self.lib.retro_deinit()
        finally:
            os.unlink(self._sopath)
