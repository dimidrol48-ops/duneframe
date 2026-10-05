"""Westwood LCW ("format80") codec as used by the game's decompressor (sub_000F8C).

Commands (positions are little-endian, 'absolute' ones are relative to the
start of the output buffer):
  0cccpppp pppppppp      copy (c+3) bytes from (out - p)            [p: 12 bits]
  10cccccc               copy c literal bytes; 0x80 = end of stream
  11cccccc pppp          copy (c+3) bytes from out_start + p         [c < 0x3E]
  11111110 cccc vv       fill c bytes with v
  11111111 cccc pppp     copy c bytes from out_start + p
"""


def decompress(src, pos=0):
    """Decode an LCW stream starting at src[pos].  Returns (data, consumed)."""
    out = bytearray()
    p = pos
    while True:
        c = src[p]; p += 1
        if c & 0x80 == 0:
            n = ((c >> 4) & 7) + 3
            rel = ((c & 0x0F) << 8) | src[p]; p += 1
            s = len(out) - rel
            for i in range(n):
                out.append(out[s + i])
        elif c & 0x40 == 0:
            n = c & 0x3F
            if n == 0:
                break
            out += src[p:p + n]; p += n
        elif c == 0xFE:
            n = src[p] | (src[p + 1] << 8); v = src[p + 2]; p += 3
            out += bytes([v]) * n
        elif c == 0xFF:
            n = src[p] | (src[p + 1] << 8); s = src[p + 2] | (src[p + 3] << 8); p += 4
            for i in range(n):
                out.append(out[s + i])
        else:
            n = (c & 0x3F) + 3
            s = src[p] | (src[p + 1] << 8); p += 2
            for i in range(n):
                out.append(out[s + i])
    return bytes(out), p - pos


def compress(data):
    """Simple greedy LCW encoder (valid for the game's decoder; not byte-identical
    to Westwood's tool, which is why unmodified assets keep their original bytes)."""
    data = bytes(data)
    out = bytearray()
    lit = bytearray()
    i, n = 0, len(data)
    index = {}

    def flush():
        while lit:
            k = min(len(lit), 0x3F)
            out.append(0x80 | k); out.extend(lit[:k]); del lit[:k]

    while i < n:
        # run fill
        run = 1
        while i + run < n and data[i + run] == data[i] and run < 0xFFFF:
            run += 1
        best_len, best_pos = 0, 0
        key = data[i:i + 3]
        if len(key) == 3:
            for s in reversed(index.get(key, [])[-64:]):
                l = 0
                while i + l < n and data[s + l] == data[i + l] and l < 0xFFFF:
                    l += 1
                if l > best_len:
                    best_len, best_pos = l, s
        if run >= 5 and run >= best_len:
            flush()
            out += bytes([0xFE, run & 0xFF, run >> 8, data[i]])
            adv = run
        elif best_len >= 3:
            flush()
            rel = i - best_pos
            if best_len <= 10 and rel <= 0xFFF:
                out += bytes([((best_len - 3) << 4) | (rel >> 8), rel & 0xFF])
            elif best_len <= 0x3F + 3 - 2 and best_pos <= 0xFFFF:
                out += bytes([0xC0 | (best_len - 3), best_pos & 0xFF, best_pos >> 8])
            elif best_pos <= 0xFFFF:
                out += bytes([0xFF, best_len & 0xFF, best_len >> 8, best_pos & 0xFF, best_pos >> 8])
            else:
                lit.append(data[i]); best_len = 1
            adv = best_len
        else:
            lit.append(data[i])
            adv = 1
        for j in range(i, min(i + adv, n - 2)):
            index.setdefault(data[j:j + 3], []).append(j)
        i += adv
    flush()
    out.append(0x80)
    return bytes(out)


if __name__ == '__main__':
    import os
    buf = os.urandom(300) + bytes(500) + b'abcabcabc' * 40
    c = compress(buf)
    d, _ = decompress(c)
    assert d == buf, 'roundtrip failed'
    print('lcw roundtrip ok', len(buf), '->', len(c))
