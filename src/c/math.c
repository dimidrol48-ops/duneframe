/* Small math helpers (decompiled from the original 68000 code). */
#include "dune2.h"

/* sub_0009DA: approximate distance  max(dx,dy) + min(dx,dy)/2 */
s16 Math_Distance(s16 x1, s16 y1, s16 x2, s16 y2) C_IMPL(Math_Distance);
s16 Math_Distance(s16 x1, s16 y1, s16 x2, s16 y2)
{
    u16 dx = x1 - x2;
    u16 dy = y1 - y2;

    /* the original negates when x1 < x2 (sub.w / bge), i.e. by the signed
     * comparison of the operands, not by the sign of the 16-bit result */
    if (x1 < x2) dx = -dx;
    if (y1 < y2) dy = -dy;
    if ((s16)dx < (s16)dy)
        dx >>= 1;
    else
        dy >>= 1;
    return dx + dy;
}

/* sub_0009B2: (a * b + 0x50) / 256, rounded percentage-style scaling */
u32 Math_MulShr8(u16 a, u16 b) C_IMPL(Math_MulShr8);
u32 Math_MulShr8(u16 a, u16 b)
{
    return ((u32)a * b + 0x50) >> 8;
}

/* sub_00E7B8: (num * 256) / den, both scaled down until the dividend fits
 * in 16 bits; 0xFFFF if den reaches 0. */
u32 Math_Ratio(u16 den, u16 num) C_IMPL(Math_Ratio);
u32 Math_Ratio(u16 den, u16 num)
{
    u32 n = (u32)num << 8;

    while (n > 0xFFFF) {
        n = (n + 1) >> 1;
        den = (u16)(den + 1) >> 1;
    }
    if (den == 0)
        return 0xFFFF;
    return divu16(n, den);
}

/* sub_00AFC0: distance between two map cells in cells, max + min/2.  The
 * row difference is taken on the sign-extended cell values as longs, as in
 * the original (it only matters for out-of-range cells). */
s16 Cell_Distance(u16 a, u16 b) C_IMPL(Cell_Distance);
s16 Cell_Distance(u16 a, u16 b)
{
    s16 dx = (s16)((a & 63) - (b & 63));
    s32 ya = ((s32)(s16)a & ~0xFFFFL) | ((a >> 6) & 63);
    s32 yb = ((s32)(s16)b & ~0xFFFFL) | ((b >> 6) & 63);
    s32 d = yb - ya;
    s16 dy = (s16)d;

    if (dx < 0)
        dx = -dx;
    if (d < 0)
        dy = -dy;
    if (dx < dy)
        dx >>= 1;
    else
        dy >>= 1;
    return dx + dy;
}
