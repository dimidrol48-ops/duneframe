/* Map cell helpers. */
#include "dune2.h"

extern void Map_UpdateCell(u16 cell, u32 flags) ASM(Map_UpdateCell);
extern void Map_RedrawCell(u16 cell) ASM(Map_RedrawCell);
extern const u16 dat_025F2A ASM(dat_025F2A);              /* spice tile */
extern const s16 k_neighbourSteps[16] ASM(dat_021164);    /* 8 steps as pairs */

/* sub_00F78A: grow spice on a cell of terrain class 0x0B; 1 if it did */
s16 sub_00F78A(u16 cell) C_IMPL(sub_00F78A);
s16 sub_00F78A(u16 cell)
{
    u16 *w;
    if (Map_GetCell(cell) != 0xB)
        return 0;
    w = (u16 *)((u8 *)g_map + (u16)(cell << 2));
    w[0] = (w[0] & 0xFE00) + dat_025F2A;
    w[1] &= 0xC800;
    Map_UpdateCell(cell, 0);
    return 1;
}

/* sub_016D62: on spice (class 8), a neighbouring thick-spice cell (class 9)
 * if there is one, else the cell itself */
u16 sub_016D62(u16 cell) C_IMPL(sub_016D62);
u16 sub_016D62(u16 cell)
{
    const s16 *d = k_neighbourSteps;
    u16 cls = Map_GetCell(cell);
    s16 k;

    for (k = 8; k; k--) {
        u16 c = cell + d[0] + d[1];
        d += 2;
        if (Map_IsPosValid(c) && cls == 8 && Map_GetCell(c) == 9)
            return c;
    }
    return cell;
}
