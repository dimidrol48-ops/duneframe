/* Small routines: VDP mode setters, UI state, effect objects, unit helpers
 * (batch 5).  Each was compiled C in the original. */
#include "dune2.h"

extern void WaitDmaQueue(void) ASM(WaitDmaQueue);
extern void sub_0029E6(void) ASM(sub_0029E6);          /* redraw the radar / minimap rows */
extern void sub_002D42(void) ASM(sub_002D42);
extern const u16 k_slotTable[] ASM(dat_0101B8);         /* 9 words per row, 3 per column */
extern const u16 k_buildTime[] ASM(dat_025F12);         /* per house: min (+0), max (+0xA) */
extern const u8 *const k_unitTypes[] ASM(dat_0831B0);
extern const u8 k_panelFont[] ASM(gfx_057F04);
/* C versions elsewhere */
extern void Anim_Start(void *a, const void *script) C_IMPL(Anim_Start);
extern void *Anim_SetFrame(void *a, s16 n) C_IMPL(Anim_SetFrame);
extern Unit *Unit_GetLinked(Unit *u) C_IMPL(Unit_GetLinked);
extern void Unit_SetDestCell(Unit *u, u16 cell) C_IMPL(Unit_SetDestCell);

/* RandomRange: register call, d0 = lo, d1 = hi (bytes) -> d0 in [lo, hi] */
static inline u16 random_range(u8 lo, u8 hi)
{
    register u32 d0 __asm__("d0") = lo;
    register u32 d1 __asm__("d1") = hi;
    __asm__ volatile("jsr RandomRange_asm" : "+d"(d0), "+d"(d1) : : "a0", "cc", "memory");
    return (u16)d0;
}

/* sub_006AEE: register call, a0 = list entry: move it from the D2FC list
 * to the D2F8 list */
static inline void list_release(void *e)
{
    register void *a0 __asm__("a0") = e;
    __asm__ volatile("jsr sub_006AEE_asm" : "+a"(a0) : : "d0", "d1", "a1", "cc", "memory");
}

/* reg 0x0C: H40 (and the screen width the game uses) or H32 */
void VDP_SetMode(u16 h40) C_IMPL(VDP_SetMode);
void VDP_SetMode(u16 h40)
{
    if (h40) {
        RAM16(0xFFFFE00A) = SCREEN_W;
        return;
    }
    RAM16(0xFFFFE00A) = 0x100;
    VDP_CTRL_W = 0x8C00;
}

/* regs 0x11 / 0x12: window plane position */
void VDP_SetWindow(u16 h, u16 v) C_IMPL(VDP_SetWindow);
void VDP_SetWindow(u16 h, u16 v)
{
    VDP_CTRL_W = 0x9100 | h;
    VDP_CTRL_W = 0x9200 | v;
}

/* sub_002186: set E010, return the old value */
u16 sub_002186(u16 v) C_IMPL(sub_002186);
u16 sub_002186(u16 v)
{
    u16 old = RAM16(0xFFFFE010);
    RAM16(0xFFFFE010) = v;
    return old;
}

/* sub_002192: clear bit 7 of byte +7 of a sprite object (short pointer) */
void sub_002192(u16 obj) C_IMPL(sub_002192);
void sub_002192(u16 obj)
{
    if (obj)
        SHORTPTR(u8, obj)[7] &= ~0x80;
}

/* sub_002656 */
void sub_002656(u32 v) C_IMPL(sub_002656);
void sub_002656(u32 v)
{
    RAM32(0xFFFFBF0E) = v;
}

/* sub_002AD2: set the radar mode byte and redraw */
void sub_002AD2(u8 mode) C_IMPL(sub_002AD2);
void sub_002AD2(u8 mode)
{
    RAM8(0xFFFFBF51) = mode;
    sub_0029E6();
    RAM8(0xFFFFBF6C) = 0;
    sub_002D42();
    WaitDmaQueue();
}

/* sub_005516: reload the 6 panel-font tiles at VRAM F6C0 and forget the
 * text cache (C85A) */
void sub_005516(void) C_IMPL(sub_005516);
void sub_005516(void)
{
    u16 i, vram = 0xF6C0;

    for (i = 0; i < 6; i++, vram += 0x20)
        VDP_QueueDma(2, ((u32)vram << 16) | 0x0010, k_panelFont);
    RAM32(0xFFFFC85A) = 0;
    RAM32(0xFFFFC85E) = 0;
}

/* sub_010180: table entry (row, column), or 0 when count + 1 exceeds it */
u16 sub_010180(u16 row, u16 col, u16 count) C_IMPL(sub_010180);
u16 sub_010180(u16 row, u16 col, u16 count)
{
    const u16 *t = (const u16 *)((const u8 *)k_slotTable + (s16)(row * 0x12) + (s16)(col * 6));
    u16 v = *t;
    if (v && (s16)(count + 1) > (s16)v)
        v = 0;
    return v;
}

/* sub_016D10: a random time between the player house's min and max (two
 * dice), scaled by pct / 100 */
u16 sub_016D10(u16 pct) C_IMPL(sub_016D10);
u16 sub_016D10(u16 pct)
{
    const u16 *t = k_buildTime + g_playerHouse;
    u16 half = (u16)(t[5] - t[0]) >> 1;
    u16 sum = random_range(0, (u8)half);
    u32 prod;

    sum += random_range(0, (u8)half);
    sum += t[0];
    prod = (u32)sum * pct;
    return (u16)divs32((s32)prod, 100);
}

/* sub_019180: take one of the 7 effect slots (FF7A04, 0x54 bytes each) and
 * start its animation; returns the slot or 0 */
u8 *sub_019180(u16 kind, u16 frame, u16 x, u16 y, u16 z) C_IMPL(sub_019180);
u8 *sub_019180(u16 kind, u16 frame, u16 x, u16 y, u16 z)
{
    u8 *p = (u8 *)0x00FF7A04;       /* as the original (lea ...&0xFFFFFF): callers get 00FF7A04 */
    u16 i;

    for (i = 0; i < 7; i++, p += 0x54) {
        if (*(u16 *)(p + 2) == 0)
            break;
    }
    if (i == 7)
        return 0;
    *(u16 *)(p + 2) = 1;
    RAM16(0xFFFFC890)++;
    *(u16 *)p = i;
    {
        u32 *q = (u32 *)(p + 4);
        u16 k;
        for (k = 0; k < 0x14; k++)
            *q++ = 0;
    }
    *(u16 *)(p + 2) = 1;
    *(u16 *)(p + 0x10) = kind;
    *(u16 *)(p + 0xC) = frame;
    *(u16 *)(p + 0xE) = frame;
    *(u16 *)(p + 0xA) = x;
    *(u16 *)(p + 6) = y;
    *(u16 *)(p + 8) = z;
    Anim_Start(p + 0x1E, (const void *)0xFFFFC1E0);
    Anim_SetFrame(p + 0x1E, frame);
    *(u16 *)(p + 0x1C) = 0;
    return p;
}

/* sub_0137E0: a unit that can wait (type flag 4) and is not linked to
 * another stops at its current cell */
void sub_0137E0(Unit *u) C_IMPL(sub_0137E0);
void sub_0137E0(Unit *u)
{
    u8 *p = (u8 *)u;

    if (!u)
        return;
    *(u16 *)(p + 0x2A) = 0;
    if (*(u16 *)(p + 6) & 1)
        return;
    if (!(*(const u16 *)(k_unitTypes[(s8)p[2]] + 0xC) & 0x10))
        return;
    if (Unit_GetLinked(u))
        return;
    Unit_SetDestCell(u, 0);
}

/* sub_006D78: release every D2FC list entry whose position matches pos
 * (ignoring the low byte of each coordinate) */
void sub_006D78(u32 pos) C_IMPL(sub_006D78);
void sub_006D78(u32 pos)
{
    u16 e;

again:
    for (e = RAM16(0xFFFFD2FC); e; e = *(u16 *)(SHORTPTR(u8, e) + 0xE)) {
        u32 p = *(u32 *)SHORTPTR(u8, e);
        p = (p & 0xFF00FF00) | 0x00800080;
        if (p == pos) {
            list_release(SHORTPTR(u8, e));
            goto again;
        }
    }
}

/* ---------------------------------------------------------------- batch 6 */

extern const u8 k_listedStructs[] ASM(dat_0104AE);     /* structure types kept in the BEBE / BEC2 lists */
extern const u8 k_listedUnits[] ASM(dat_010428);       /* unit types kept in the BEB2 / BEB6 lists */

/* House_AreEnemies: register call, d0 = house, d1 = house -> d0 = 1 if enemies */
static inline u16 house_enemies(s16 a, s16 b)
{
    register u32 d0 __asm__("d0") = (u16)a;
    register u32 d1 __asm__("d1") = (u16)b;
    __asm__ volatile("jsr House_AreEnemies_asm" : "+d"(d0) : "d"(d1) : "a1", "cc");
    return (u16)d0;
}

/* take an entry from the BEAA free list (8-byte entries linked by short
 * pointers at +4, back links at +2) for object handle h, and push it onto
 * *own or *enemy depending on the object's house */
static u8 *list_add(const u8 *obj, u8 **own, u8 **enemy)
{
    u8 *e = *(u8 **)0xFFFFBEAA, *next = SHORTPTR(u8, *(u16 *)(e + 4)), *head;
    u8 **list;

    *(u16 *)(next + 2) = 0;
    *(u8 **)0xFFFFBEAA = next;
    *(u32 *)(e + 2) = 0;
    *(u16 *)e = *(const u16 *)obj;
    list = house_enemies((s8)obj[8], g_playerHouse) ? enemy : own;
    head = *list;
    *(u16 *)(e + 4) = (u16)(u32)head;
    if (head)
        *(u16 *)(head + 2) = (u16)(u32)e;
    *list = e;
    return e;
}

/* sub_0104CE: list a new structure (own: BEBE, enemy: BEC2) */
u32 sub_0104CE(const u8 *s) C_IMPL(sub_0104CE);
u32 sub_0104CE(const u8 *s)
{
    if (!k_listedStructs[s[2]])
        return 0;
    return (u32)list_add(s, (u8 **)0xFFFFBEBE, (u8 **)0xFFFFBEC2);
}

/* sub_01043C: list a new unit (own: BEB2, enemy: BEB6); BEA2 counts them
 * down.  Unlisted types return their type number, as the original does */
u32 sub_01043C(const u8 *u) C_IMPL(sub_01043C);
u32 sub_01043C(const u8 *u)
{
    if (!k_listedUnits[u[2]])
        return u[2];
    RAM16(0xFFFFBEA2)--;
    return (u32)list_add(u, (u8 **)0xFFFFBEB2, (u8 **)0xFFFFBEB6);
}

/* sub_0153D4: queue the DMA of one frame of a mentat / briefing animation
 * (kind 0: 0x240-byte frames from FF1000 to VRAM B120, kind 1: 0x460-byte
 * frames from FF1B40 to VRAM B360) */
void sub_0153D4(u16 unused, u16 kind, u16 frame) C_IMPL(sub_0153D4);
void sub_0153D4(u16 unused, u16 kind, u16 frame)
{
    (void)unused;
    if (kind == 0)
        VDP_QueueDma(2, (0xB120UL << 16) | 0x120, (const u8 *)0xFFFF1000 + (s16)(frame * 0x240));
    else if (kind == 1)
        VDP_QueueDma(2, (0xB360UL << 16) | 0x230, (const u8 *)0xFFFF1B40 + (s16)(frame * 0x460));
}
