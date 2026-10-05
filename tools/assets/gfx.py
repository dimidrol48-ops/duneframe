"""4bpp Mega Drive tiles <-> indexed PNG sheets (tiles in row-major order;
the sheet width in tiles is free, 16 by default)."""
import struct, zlib

TILES_PER_ROW = 16
# neutral grey ramp for graphics whose in-game palette is unknown
DEFAULT_PAL = [((i * 0xE // 15) & 0xE) * 0x111 for i in range(16)]


def md_to_rgb(w):
    r = (w >> 1) & 7; g = (w >> 5) & 7; b = (w >> 9) & 7
    return (r * 255 // 7, g * 255 // 7, b * 255 // 7)


def _chunk(tag, data):
    return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', zlib.crc32(tag + data) & 0xFFFFFFFF)


def tiles_to_pixels(data, tpr=TILES_PER_ROW):
    ntiles = len(data) // 32
    rows = (ntiles + tpr - 1) // tpr
    w, h = tpr * 8, rows * 8
    pix = bytearray(w * h)
    for t in range(ntiles):
        tx, ty = (t % tpr) * 8, (t // tpr) * 8
        for y in range(8):
            row = data[t * 32 + y * 4:t * 32 + y * 4 + 4]
            for x in range(8):
                b = row[x >> 1]
                pix[(ty + y) * w + tx + x] = (b >> 4) if x % 2 == 0 else (b & 15)
    return w, h, pix


def pixels_to_tiles(w, h, pix, ntiles):
    tpr = w // 8
    out = bytearray()
    for t in range(ntiles):
        tx, ty = (t % tpr) * 8, (t // tpr) * 8
        for y in range(8):
            for x in range(0, 8, 2):
                a = pix[(ty + y) * w + tx + x] & 15
                b = pix[(ty + y) * w + tx + x + 1] & 15
                out.append((a << 4) | b)
    return bytes(out)


def write_png(path, data, md_colors, tpr=TILES_PER_ROW):
    """Write tiles as a 4-bit indexed PNG; the tile count is stored in a tEXt
    chunk so that trailing blank tiles of the last row are not added back."""
    w, h, pix = tiles_to_pixels(data, tpr)
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        for x in range(0, w, 2):
            raw.append((pix[y * w + x] << 4) | pix[y * w + x + 1])
    plte = b''.join(bytes(md_to_rgb(c)) for c in md_colors[:16])
    text = b'tiles\0' + str(len(data) // 32).encode() + b'\0' + b''.join(b'%04X' % c for c in md_colors[:16])
    png = b'\x89PNG\r\n\x1a\n' + _chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 4, 3, 0, 0, 0)) + \
        _chunk(b'PLTE', plte) + _chunk(b'tEXt', text) + _chunk(b'IDAT', zlib.compress(bytes(raw), 9)) + _chunk(b'IEND', b'')
    open(path, 'wb').write(png)


def read_png(path):
    """Return tile bytes from an indexed PNG (any bit depth <= 8, colour type 3).
    Pixel values are used as palette indices (only the low 4 bits)."""
    d = open(path, 'rb').read()
    assert d[:8] == b'\x89PNG\r\n\x1a\n', path
    p = 8; idat = b''; ntiles = None
    while p < len(d):
        ln, tag = struct.unpack('>I4s', d[p:p + 8]); body = d[p + 8:p + 8 + ln]; p += 12 + ln
        if tag == b'IHDR':
            w, h, depth, ctype = struct.unpack('>IIBB', body[:10])
            assert ctype == 3, '%s: must be an indexed (palette) PNG' % path
        elif tag == b'IDAT':
            idat += body
        elif tag == b'tEXt' and body.startswith(b'tiles\0'):
            ntiles = int(body[6:].split(b'\0')[0])
    raw = zlib.decompress(idat)
    bpp = depth
    stride = (w * bpp + 7) // 8
    pix = bytearray(w * h)
    prev = bytearray(stride)
    pos = 0
    for y in range(h):
        ft = raw[pos]; line = bytearray(raw[pos + 1:pos + 1 + stride]); pos += 1 + stride
        bpp_bytes = 1
        for i in range(stride):
            a = line[i - bpp_bytes] if i >= bpp_bytes else 0
            b = prev[i]; c = prev[i - bpp_bytes] if i >= bpp_bytes else 0
            if ft == 1: line[i] = (line[i] + a) & 255
            elif ft == 2: line[i] = (line[i] + b) & 255
            elif ft == 3: line[i] = (line[i] + ((a + b) >> 1)) & 255
            elif ft == 4:
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        prev = line
        for x in range(w):
            if bpp == 8: v = line[x]
            elif bpp == 4: v = (line[x >> 1] >> (4 * (1 - (x & 1)))) & 15
            elif bpp == 2: v = (line[x >> 2] >> (2 * (3 - (x & 3)))) & 3
            else: v = (line[x >> 3] >> (7 - (x & 7))) & 1
            pix[y * w + x] = v
    if ntiles is None:
        ntiles = (w // 8) * (h // 8)
    assert w % 8 == 0 and h % 8 == 0, '%s: size must be a multiple of 8' % path
    return pixels_to_tiles(w, h, pix, ntiles)
