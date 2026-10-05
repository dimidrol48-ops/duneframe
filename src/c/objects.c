/* Small object / unit helpers. */
#include "dune2.h"

extern u16 g_spritePalAttr[] RAM(g_spritePalAttr);
extern void sub_00969A(void *unit) ASM(sub_00969A);
void *sub_01242C(u8 *cur) C_IMPL(sub_01242C);

/* palette / priority bits (13-14) of a sprite object given by short pointer */
void Sprite_SetPaletteBits(u16 obj, u16 idx) C_IMPL(Sprite_SetPaletteBits);
void Sprite_SetPaletteBits(u16 obj, u16 idx)
{
    u16 *f = (u16 *)((u8 *)SHORTPTR(void, obj) + 6);
    *f = (*f & 0x9FFF) | g_spritePalAttr[idx];
}

void Unit_SetDestCell(Unit *u, u16 cell) C_IMPL(Unit_SetDestCell);
void Unit_SetDestCell(Unit *u, u16 cell)
{
    if (!u)
        return;
    *(u16 *)((u8 *)u + 0x5C) = cell;
    sub_00969A(u);
}

/* anim state: both its frame and script pointers set */
typedef struct AnimPtrs { const void *frame, *script; } AnimPtrs;
u32 Anim_IsPlaying(AnimPtrs *a) C_IMPL(Anim_IsPlaying);
u32 Anim_IsPlaying(AnimPtrs *a)
{
    if (!a || !a->frame || !a->script)
        return 0;
    return 1;
}

/* restart a list cursor; returns its first entry (the original tail-calls
 * sub_01242C, and callers use the result) */
void *sub_01240E(void *obj) C_IMPL(sub_01240E);
void *sub_01240E(void *obj)
{
    if (!obj)
        obj = (void *)0xFFFFBEDA;
    *(u16 *)((u8 *)obj + 4) = 0xFFFF;
    return sub_01242C(obj);
}

/* the unit / structure an object is linked to (byte +3, 0xFF = none) */
Unit *Unit_GetLinked(Unit *u) C_IMPL(Unit_GetLinked);
Unit *Unit_GetLinked(Unit *u)
{
    if (!u || u->link == 0xFF)
        return 0;
    return Unit_GetByIndex((s8)u->link);
}

void *Unit_GetLinkedStructure(Unit *u) C_IMPL(Unit_GetLinkedStructure);
void *Unit_GetLinkedStructure(Unit *u)
{
    if (!u || u->link == 0xFF)
        return 0;
    return Structure_GetByIndex((s8)u->link);
}

/* one of 7 records of 0x54 bytes at FF7A04 */
void *sub_0191DE(s16 i) C_IMPL(sub_0191DE);
void *sub_0191DE(s16 i)
{
    if (i < 0 || i >= 7)
        return 0;
    return (void *)(0xFF7A04 + (u32)((u16)i * 0x54));
}

/* ---- batch 2 */
void *sub_0191DE(s16 i) C_IMPL(sub_0191DE);
extern void Sound_PlayFx(s16 fx) C_IMPL(Sound_PlayFx);
extern void Unit_SetAction(Unit *u, s16 action) ASM(Unit_SetAction);

/* start an effect on an object's sprite and play its sound */
void sub_005ED6(u8 *obj, s16 frames, s16 attr, s16 fx) C_IMPL(sub_005ED6);
void sub_005ED6(u8 *obj, s16 frames, s16 attr, s16 fx)
{
    u8 *spr;
    if (!obj)
        return;
    obj[5] = (u8)attr;
    spr = SHORTPTR(u8, *(u16 *)(obj + 6));
    spr[4] = (u8)frames;
    spr[5] = (u8)frames;
    spr[7] |= 0x20;
    spr[0] = (u8)fx;
    Sound_PlayFx(fx);
}

/* step a list cursor ({.., +4 index} ; count at BEE2, entries at BEE4) */
void *sub_01242C(u8 *cur) C_IMPL(sub_01242C);
void *sub_01242C(u8 *cur)
{
    s16 i;
    if (!cur)
        cur = (u8 *)0xFFFFBEDA;
    i = *(s16 *)(cur + 4);
    if (i < (s16)RAM16(0xFFFFBEE2))
        i++;
    *(s16 *)(cur + 4) = i;
    if (i < (s16)RAM16(0xFFFFBEE2))
        return ((void **)0xFFFFBEE4)[i];
    return 0;
}

/* the team record a unit belongs to (byte +0x75, 1-based) */
void *sub_019E42(u8 *u) C_IMPL(sub_019E42);
void *sub_019E42(u8 *u)
{
    if (!u || !u[0x75])
        return 0;
    return sub_0191DE((s8)u[0x75] - 1);
}

/* object in a map cell: a unit or a structure (byte +2 flags, +3 index+1) */
void *sub_00F180(u16 cell) C_IMPL(sub_00F180);
void *sub_00F180(u16 cell)
{
    u8 *c;
    s16 i;
    if (cell >= 0x1000)
        return 0;
    c = (u8 *)g_map + ((u32)cell << 2);
    i = (s16)c[3] - 1;
    if (i < 0)
        return 0;
    if (c[2] & 0x10)
        return Unit_GetByIndex(i);
    if (c[2] & 0x20)
        return Structure_GetByIndex(i);
    return 0;
}

/* take a unit out of its team; returns the team's free places */
s16 sub_01930C(u8 *u) C_IMPL(sub_01930C);
s16 sub_01930C(u8 *u)
{
    u8 *t;
    if (!u || !u[0x75])
        return 0;
    t = sub_0191DE((s8)u[0x75] - 1);
    (*(s16 *)(t + 4))--;
    u[0x75] = 0;
    return *(s16 *)(t + 8) - *(s16 *)(t + 4);
}

/* put a unit into a team and set it to action 3 */
s16 sub_0192D0(u8 *t, Unit *u) C_IMPL(sub_0192D0);
s16 sub_0192D0(u8 *t, Unit *u)
{
    s16 free;
    if (!t || !u)
        return 0;
    ((u8 *)u)[0x75] = (u8)(*(u16 *)t + 1);
    (*(s16 *)(t + 4))++;
    free = *(s16 *)(t + 8) - *(s16 *)(t + 4);
    Unit_SetAction(u, 3);
    return free;
}

/* reveal the map around a unit (with a flag set while doing it) and restart
 * its animation; the unit is then parked off the map */
extern void Unit_RevealAround(s16 radius, void *obj) ASM(Unit_RevealAround);
extern void Anim_Start(void *a, const void *script) C_IMPL(Anim_Start);

void sub_01E212(u8 *u) C_IMPL(sub_01E212);
void sub_01E212(u8 *u)
{
    REG_OUT(g_cRegIn);          /* the caller's d3, unless sub_012EE2 changes it */
    if (!u)
        return;
    u[5] |= 0x40;
    Unit_RevealAround(0, u);
    u[5] &= ~0x40;
    Anim_Start(u + 0x16, (const void *)0xFFFFC1B0);
    {   /* sub_01EAD6 takes the unit in d0 */
        register u8 *d0 __asm__("d0") = u;
        __asm__ volatile("jsr sub_01EAD6_asm" : "+d"(d0) : : "d1", "d2", "a0", "a1", "cc", "memory");
    }
    u[5] |= 0x04;
    {   /* sub_012EE2 takes the unit in a2 and borrows d3, leaving
         * (9,a2) & 0xE0 in bits 16-23; the original passes that on to the
         * callers of this routine, which use d3 (e.g. as an effect's
         * position): kept for fidelity */
        register u8 *a2 __asm__("a2") = u;
        __asm__ volatile("move.l %%d3,-(%%sp)\n\tmove.l g_cRegIn,%%d3\n\tjsr sub_012EE2_asm\n\t"
                         "move.l %%d3,g_cRegOut\n\tmove.l (%%sp)+,%%d3"
                         : : "a"(a2) : "d0", "d1", "d2", "a0", "a1", "cc", "memory");
    }
    SHORTPTR(u8, *(u16 *)(u + 0x10))[7] |= 0x80;
    *(u32 *)(u + 0xA) = 0xFFFFFFFF;
}

/* clear the +6 word of every entry of the BEDA list, then count the
 * structures (7F slots of 0x62 bytes at FF4574) whose +5 bit 0 is set */
void sub_006DB6(void) C_IMPL(sub_006DB6);
void sub_006DB6(void)
{
    u8 *p;
    u16 i, n = 0;

    for (p = sub_01240E(0); p; p = sub_01242C(0))
        *(u16 *)(p + 6) = 0;
    for (i = 0; i < 0x7F; i++)
        if (((u8 *)0xFF4579)[(u32)i * 0x62] & 1)
            n++;
    RAM16(0xFFFFD318) = n;
}

/* a structure is removed: stop its animation, update the per-house counts */
extern u8 *const k_houseCounts[] ASM(dat_01FF10);
extern void sub_008B28(void *s) ASM(sub_008B28);
extern void sub_0105B8(u16 v) ASM(sub_0105B8);

void sub_006EEE(u8 *s) C_IMPL(sub_006EEE);
void sub_006EEE(u8 *s)
{
    Anim_Start(s + 0x16, (const void *)0xFFFFC1C8);
    k_houseCounts[(s8)s[8]][(s8)s[2]]--;
    sub_008B28(s);
    sub_0105B8(*(u16 *)(s + 0x60));
    *(u16 *)(s + 0x60) = 0;
    *(u16 *)(s + 4) = 4;
    RAM16(0xFFFFD318)--;
}

/* ---- batch 4 */
extern const u8 *const k_objTypeInfo[] ASM(dat_0831B0);
extern const u8 *const k_unitTypeInfo[] ASM(k_unitTypeInfo);
extern const s32 k_weaponOffsets[] ASM(dat_020504);
extern void sub_00EB24(u32 pos, s16 v) ASM(sub_00EB24);
extern s16 loc_01D350(u8 *obj, u8 *u) ASM(loc_01D350);
extern void *memcpy_game(void *d, const void *s, u32 n) ASM(memcpy);
extern void Selection_Set(s16 mode) ASM(Selection_Set);
extern void *volatile g_orderUnit RAM(g_orderUnit);
extern volatile s16 g_orderAction RAM(g_orderAction);
extern volatile s16 g_playerHouse RAM(g_playerHouse);
s16 sub_01930C(u8 *u) C_IMPL(sub_01930C);

/* sub_00A9F6: for a player unit, start an effect at its weapon position */
void sub_00A9F6(u8 *u) C_IMPL(sub_00A9F6);
void sub_00A9F6(u8 *u)
{
    const u8 *ti;
    u32 pos;
    if (!u || (s8)u[8] != g_playerHouse)
        return;
    pos = *(u32 *)(u + 0xA);
    ti = k_objTypeInfo[(s8)u[2]];
    pos += k_weaponOffsets[*(s16 *)(ti + 0x3C)];
    sub_00EB24(pos, *(s16 *)(k_objTypeInfo[(s8)u[2]] + 0x12));
}

/* sub_01D42A: the unit (not flagged +5 bit 2) that scores best for obj */
u8 *sub_01D42A(u8 *obj) C_IMPL(sub_01D42A);
u8 *sub_01D42A(u8 *obj)
{
    u8 *u = (u8 *)0xFF0000, *best = 0;
    s16 bs = 0;
    u16 n = RAM16(0xFFFFC226);

    do {
        if (!(u[5] & 4)) {
            s16 sc = loc_01D350(obj, u);
            if (sc >= bs) {
                best = u;
                bs = sc;
            }
        }
        u += 0x8C;
    } while (n-- != 0);
    return bs ? best : 0;
}

/* sub_019AA0: clear the BEDA list marks, count living units per team */
void sub_019AA0(void) C_IMPL(sub_019AA0);
void sub_019AA0(void)
{
    u8 *p, *u = (u8 *)0xFF0005;
    u16 i, n = 0;

    for (p = sub_01240E(0); p; p = sub_01242C(0))
        *(u16 *)(p + 6) = 0;
    for (i = 0; i < 0x7F; i++, u += 0x8C)
        if (*u & 1) {
            (*(u16 *)(Team_Get((s8)u[3]) + 6))++;
            n++;
        }
    RAM16(0xFFFFC892) = n;
}

/* sub_0123B8: remove obj from the list at BEE4 (count at BEE2) */
void sub_0123B8(u8 *obj) C_IMPL(sub_0123B8);
void sub_0123B8(u8 *obj)
{
    u8 **e = (u8 **)0xFFFFBEE4;
    s16 i;

    for (i = 0; i < (s16)RAM16(0xFFFFBEE2); i++, e++) {
        if (*e != obj)
            continue;
        RAM16(0xFFFFBEE2)--;
        *(u16 *)(obj + 4) = 0;
        if (i < (s16)RAM16(0xFFFFBEE2))
            memcpy_game(e, e + 1, ((s32)(s16)RAM16(0xFFFFBEE2) - i) << 2);
    }
}

/* sub_01DB7A: set a unit's countdown (+0x71) and its step (+0x70/+0x6E)
 * from its type's speed (+0x42 of the type info) */
void sub_01DB7A(u8 *u, u16 v) C_IMPL(sub_01DB7A);
void sub_01DB7A(u8 *u, u16 v)
{
    const u8 *ti;
    u16 d1, d0;

    u[0x70] = 0;
    *(u16 *)(u + 0x6E) = 0;
    if (v == 0 || v >= 0x100) {
        u[0x71] = 0;
        return;
    }
    u[0x71] = (u8)v;
    ti = k_unitTypeInfo[(s8)u[2]];
    d1 = (u16)((u16)((u32)v * *(u16 *)(ti + 0x42)) + 0x50) >> 8;
    d0 = (u16)(d1 << 4);
    d1 >>= 4;
    if (d1)
        d0 = 0xFF;
    else
        d1 = 1;
    u[0x70] = (u8)d1;
    u[0x6E] = (u8)d0;
}

/* sub_01EB8C: a player unit leaves its team; cancels a pending order if
 * it is the selected unit.  1 if it was in a team. */
s16 sub_01EB8C(u8 *u) C_IMPL(sub_01EB8C);
s16 sub_01EB8C(u8 *u)
{
    if (!u || (s8)u[8] != g_playerHouse)
        return 0;
    if (!(*(u16 *)(u + 4) & 2))
        return 0;
    u[5] &= ~2;
    sub_01930C(u);
    if ((void *)u == g_selectedObject && g_uiMode == 1) {
        g_orderUnit = 0;
        g_orderAction = -1;
        Selection_Set(4);
    }
    return 1;
}
