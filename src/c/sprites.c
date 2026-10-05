/* Sprite objects attached to units/structures, palette selection. */
#include "dune2.h"

extern const void *const dat_084282 ASM(dat_084282);
extern const void *const dat_0842EA[] ASM(dat_0842EA);
extern const void *const dat_0842CE[] ASM(dat_0842CE);
extern const u8 dat_08457E[] ASM(dat_08457E);
extern const u16 k_housePalBits[4] ASM(dat_005814);   /* 4000 2000 6000 0000 */

/* attach (or re-shape) an object's marker sprite; bit in D497[slot] */
static void attach(u8 *obj, const void *shape, u32 attr, u8 bit)
{
    u8 *flag = (u8 *)0xFFFFD497 + *(u16 *)obj;
    u16 spr = *(u16 *)(obj + 0x10);

    if (spr) {
        *(const void **)(SHORTPTR(u8, spr) + 8) = shape;
    } else {
        obj[0xE] = 3;
        spr = Sprite_CreateObj(obj + 0xA, attr, shape, SPRITE_POOL);
        *(u16 *)(obj + 0x10) = spr;
        if (!spr)
            return;
    }
    *flag |= bit;
}

void sub_005978(u8 *obj) C_IMPL(sub_005978);
void sub_005978(u8 *obj)
{
    attach(obj, dat_084282, 0x3030000, 1);
}

void sub_005920(u8 *obj, u16 i) C_IMPL(sub_005920);
void sub_005920(u8 *obj, u16 i)
{
    attach(obj, dat_0842EA[(s16)i], 0x6060000, 2);
}

void sub_0059C6(u8 *obj, u16 i) C_IMPL(sub_0059C6);
void sub_0059C6(u8 *obj, u16 i)
{
    attach(obj, dat_0842CE[(s16)i], 0x7070000, 4);
}

/* switch a panel sprite to picture n (house palette + tiles by DMA) */
static void panel_picture(s16 n, u16 *cur, u16 sprv, u32 cmd)
{
    u8 *o;
    if (n <= 0)
        return;
    if ((s16)*cur != n) {
        const u8 *rec;
        *cur = n;
        rec = dat_08457E + (u16)(n << 3);
        o = SHORTPTR(u8, sprv);
        *(u16 *)(o + 6) = (*(u16 *)(o + 6) & 0x9FFF) | k_housePalBits[(u8)(rec[4] + 3) & 3];
        VDP_QueueDma(2, cmd, *(const void *const *)rec);
    }
    o = SHORTPTR(u8, sprv);
    o[7] &= ~0x80;
}

void sub_0057BC(s16 n) C_IMPL(sub_0057BC);
void sub_0057BC(s16 n)
{
    panel_picture(n, &RAM16(0xFFFFC734), RAM16(0xFFFFC732), 0xF28000C0);
}

void sub_00581C(s16 n) C_IMPL(sub_00581C);
void sub_00581C(s16 n)
{
    panel_picture(n, &RAM16(0xFFFFC73E), RAM16(0xFFFFC73C), 0xF4C000C0);
}

/* sub_005E56: show a text in the panel font (tiles at F6C0), writing only
 * the characters that changed since the last call (kept at C85A) */
extern const u8 k_panelFont[] ASM(gfx_057F04);

void sub_005E56(const u8 *str) C_IMPL(sub_005E56);
void sub_005E56(const u8 *str)
{
    u8 *cur = (u8 *)0xFFFFC85A;
    u32 dst = 0x10F6C0;
    u8 c;

    for (;;) {
        c = *str++;
        if (!c)
            return;
        if (c != *cur++)
            break;
        dst = (dst & 0xFFFF0000) | (u16)(dst + 0x20);
    }
    str--;
    cur--;
    while ((c = *str++) != 0) {
        u16 off;
        *cur++ = c;
        off = c - 0x20;
        if (off)
            off = (u16)((u16)(off - 0xF) << 5);
        VDP_QueueDma(2, dst << 16 | dst >> 16, k_panelFont + off);
        dst = (dst & 0xFFFF0000) | (u16)(dst + 0x20);
    }
}
