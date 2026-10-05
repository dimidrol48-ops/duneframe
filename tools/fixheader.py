#!/usr/bin/env python3
"""Update the cartridge header of a built ROM: ROM end address and checksum."""
import sys, struct
p = sys.argv[1]
d = bytearray(open(p, 'rb').read())
if len(d) & 1:
    d.append(0xFF)
struct.pack_into('>I', d, 0x1A4, max(len(d) - 1, struct.unpack_from('>I', d, 0x1A4)[0]))
s = sum(struct.unpack('>%dH' % ((len(d) - 0x200) // 2), d[0x200:])) & 0xFFFF
struct.pack_into('>H', d, 0x18E, s)
open(p, 'wb').write(d)
print('%s: %d bytes, checksum %04X' % (p, len(d), s))
