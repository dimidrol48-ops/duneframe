/* VDP register setters.  Each remembers the new table address in RAM and
 * returns the previous one. */
#include "dune2.h"

u32 g_cRegOut, g_cRegIn;      /* see REG_OUT in dune2.h */

extern u16 g_vdpSpriteTable RAM(g_vdpSpriteTable);
extern u16 g_vdpPlaneA      RAM(g_vdpPlaneA);
extern u16 g_vdpPlaneB      RAM(g_vdpPlaneB);
extern u16 g_vdpHScroll     RAM(g_vdpHScroll);

/* reg 0x10: plane size (h, w as the register's 2-bit codes) */
void VDP_SetPlaneSize(u16 h, u16 w) C_IMPL(VDP_SetPlaneSize);
void VDP_SetPlaneSize(u16 h, u16 w)
{
    VDP_CTRL_W = 0x9000 | (u16)(h << 4) | w;
}

/* reg 0x02: plane A name table (VRAM address, 8KB units) */
u16 VDP_SetPlaneA(u16 vram) C_IMPL(VDP_SetPlaneA);
u16 VDP_SetPlaneA(u16 vram)
{
    u16 old = g_vdpPlaneA;
    u16 reg = 0x8200 | (u16)((vram & 0xE000) >> 10);
    g_vdpPlaneA = vram;
    VDP_CTRL_W = reg;
    REG_OUT(reg);       /* the WIDE build ORs in the 128K-VRAM bit and writes d1 again */
    return old;
}

/* reg 0x04: plane B name table */
u16 VDP_SetPlaneB(u16 vram) C_IMPL(VDP_SetPlaneB);
u16 VDP_SetPlaneB(u16 vram)
{
    u16 old = g_vdpPlaneB;
    u16 reg = 0x8400 | (u16)((vram & 0xE000) >> 13);
    g_vdpPlaneB = vram;
    VDP_CTRL_W = reg;
    REG_OUT(reg);
    return old;
}

/* reg 0x0D: horizontal scroll table (1KB units) */
u16 VDP_SetHScrollTable(u16 vram) C_IMPL(VDP_SetHScrollTable);
u16 VDP_SetHScrollTable(u16 vram)
{
    u16 old = g_vdpHScroll;
    g_vdpHScroll = vram;
    VDP_CTRL_W = 0x8D00 | (u16)((vram & 0xFC00) >> 10);
    return old;
}

/* reg 0x05: sprite attribute table (512-byte units) */
u16 VDP_SetSpriteTable(u16 vram) C_IMPL(VDP_SetSpriteTable);
u16 VDP_SetSpriteTable(u16 vram)
{
    u16 old = g_vdpSpriteTable;
    g_vdpSpriteTable = vram;
    VDP_CTRL_W = 0x8500 | (u16)((vram & 0xFE00) >> 9);
    return old;
}
