/*
 * Dune II: The Battle for Arrakis (Genesis) - shared declarations for C code.
 *
 * The C code is plain C with 32-bit int.  The original code was built with a
 * 16-bit-int compiler: stack arguments are words (char/short/int) or longs
 * (long/pointer), the caller pops, results in d0 (pointers in a0), and
 * d0-d2/a0-a1 are scratch.  The generator builds adapters from the C
 * prototypes (tools/disasm/csig.py), so nothing here needs to care:
 *   - C_IMPL(label): a C replacement of an original routine; with
 *     NONMATCHING=1 the routine jumps to a stub that repacks its arguments
 *     and preserves the registers its callers rely on (C_FUNCS in
 *     tools/disasm/config.py)
 *   - ASM(label): an original routine called from C, through a thunk
 *     <label>_asm that repacks the arguments (C_EXPORTS)
 *   - data and register-argument helpers are plain aliases <label>_asm
 * Use exact-width types (s16/u16 ...) for anything shared with the game.
 */
#ifndef DUNE2_H
#define DUNE2_H

typedef signed char    s8;
typedef unsigned char  u8;
typedef signed short   s16;
typedef unsigned short u16;
typedef signed long    s32;
typedef unsigned long  u32;

#define ASM(label)      __asm__(#label "_asm")   /* assembly label */
#define RAM(name)       __asm__(#name)           /* RAM variable (absolute symbol) */

/* A second result that the original routine leaves in a register and some
 * caller uses (config.C_REGOUT): the C version stores it here and the
 * generated stub loads it into that register. */
extern u32 g_cRegOut;
#define REG_OUT(v)      (g_cRegOut = (v))
/* ... and a register value from the caller that it needs (config.C_REGIN) */
extern u32 g_cRegIn;
#define C_IMPL(label)   __asm__(#label "_c")     /* C replacement of an assembly routine */

/* ---- RAM variables (see src/symbols.inc) */
extern volatile u8  g_soundEnabled RAM(g_soundEnabled);
extern volatile u8  g_lastVoice    RAM(g_lastVoice);
extern volatile s16 g_playerHouse  RAM(g_playerHouse);

/* ---- ROM data */
extern const u8 k_fxToSequence[] ASM(k_fxToSequence);          /* sound effect id -> GEMS sequence (0xFF = none) */
extern const u8 *const k_houseVoiceTables[] ASM(k_houseVoiceTables); /* per house: voice id -> GEMS sequence */

/* ---- assembly routines callable from C */
extern void Gems_StartSequence(s32 seq) ASM(Gems_StartSequence);
extern void Gems_StopSequence(s32 seq) ASM(Gems_StopSequence);

/* ---- units: 128 slots of 0x8C bytes in RAM (k_unitPtrs holds their addresses).
 * Type ids follow PC Dune II (2..6 infantry, 7..15 vehicles, 16 harvester,
 * 17 MCV, 25 sandworm; 0/1 aircraft, 18..24 projectiles). */
typedef struct Unit {
    u16 handle;          /* +00 slot index */
    u8  type;            /* +02 */
    u8  link;            /* +03 linked unit / structure slot, 0xFF = none */
    u8  status4;         /* +04 */
    u8  status5;         /* +05 bit 1: alive */
    u16 uiFlags;         /* +06 bit 15: selected, bit 13: selected by the player */
    s8  house;           /* +08 */
    u8  pad09;
    u16 y;               /* +0A world position in 1/8 pixels: cell row = y >> 8 */
    u16 x;               /* +0C                               cell col = x >> 8 */
} Unit;
#define UNIT_SLOTS      128
#define UNIT_ALIVE(u)   ((u)->status5 & 2)
#define UNIT_PX(u)      ((s16)((u)->x >> 3))           /* world pixels */
#define UNIT_PY(u)      ((s16)((u)->y >> 3))
#define UNIT_CELL(u)    ((u16)(((u)->y & 0xFF00) >> 2 | (u)->x >> 8))
#define UF_SELECTED     0x8000
#define UF_PLAYER_SEL   0x2000
extern Unit *const k_unitPtrs[] ASM(k_unitPtrs);

/* map: 64 cells per row, 4 bytes per cell */
typedef struct MapCell { u8 tile; u8 flags; u16 object; } MapCell;
extern MapCell g_map[] RAM(g_map);

/* cursor (free mode): screen position of its 32x32 bracket + clamp bounds */
typedef struct Cursor { s16 x, y; s16 pad[2]; s16 xmin, ymin, xmax, ymax; } Cursor;
extern Cursor g_cursor RAM(g_cursor);

extern volatile u16 g_vblankCount  RAM(g_vblankCount);
extern volatile s16 g_scrollX      RAM(g_scrollX);
extern volatile s16 g_scrollY      RAM(g_scrollY);
extern volatile u16 g_cursorPos    RAM(g_cursorPos);      /* cell under the cursor */
extern void *volatile g_selectedObject RAM(g_selectedObject);
extern void *volatile g_selectedStructure RAM(g_selectedStructure);
extern volatile u8  g_inputEvent   RAM(g_inputEvent);     /* 'A' 'B' ... this frame */
extern volatile u8  g_inputEventNext RAM(g_inputEventNext);
extern volatile u16 g_orderCellOverride RAM(g_orderCellOverride);
extern volatile s16 g_uiMode       RAM(g_uiMode);
extern volatile u8  g_noCancel     RAM(g_noCancel);
extern volatile u8  g_padPressed   RAM(g_padPressed);
extern volatile u8  g_padHeld      RAM(g_padHeld);
extern volatile u8  g_padExtPressed RAM(g_padExtPressed);
extern volatile u8  g_padExtHeld   RAM(g_padExtHeld);
extern volatile u16 g_spriteCount4 RAM(g_spriteCount4);   /* sprites in the table * 4 */
extern u8 g_spriteTable[]          RAM(g_spriteTable);     /* 80 x 8 bytes, DMAed to the VDP */

#define PAD_UP 0x01
#define PAD_DOWN 0x02
#define PAD_LEFT 0x04
#define PAD_RIGHT 0x08
#define PAD_B 0x10
#define PAD_C 0x20
#define PAD_A 0x40
#define PAD_START 0x80
#define PADX_Z 0x01
#define PADX_Y 0x02
#define PADX_X 0x04
#define PADX_MODE 0x08

/* stack-argument assembly routines */
extern s16   Order_Frame(void) ASM(Order_Frame);
extern Unit *Map_GetUnitAt(u16 cell) ASM(Map_GetUnitAt);
extern void *Map_GetStructureAt(u16 cell) ASM(Map_GetStructureAt);
extern void  Sound_PlayFx(s16 fx) C_IMPL(Sound_PlayFx);
extern void  Selection_Clear(void) ASM(Selection_Clear);

/* RAM that has no name yet, by address */
#define RAM8(a)   (*(u8  *)(a))
#define RAM16(a)  (*(u16 *)(a))
#define RAM32(a)  (*(u32 *)(a))
/* 16-bit "short pointers": RAM addresses stored as words, sign-extended */
#define SHORTPTR(T, w)  ((T *)(s32)(s16)(w))

#define VDP_CTRL_W  (*(volatile u16 *)0xC00004)

/* hand-written lookups with register arguments (d0 in, a0 out; they clobber d0/a0) */
static inline Unit *Unit_GetByIndex(s16 i)
{
    register s16 d0 __asm__("d0") = i;
    register Unit *a0 __asm__("a0");
    __asm__ volatile("jsr Unit_GetByIndex_asm" : "=a"(a0), "+d"(d0) : : "cc");
    return a0;
}
static inline void *Structure_GetByIndex(s16 i)
{
    register s16 d0 __asm__("d0") = i;
    register void *a0 __asm__("a0");
    __asm__ volatile("jsr Structure_GetByIndex_asm" : "=a"(a0), "+d"(d0) : : "cc");
    return a0;
}

/* Sprite_Create: d0 = position, d1 = attributes, a0 = shape, a1 = pool
 * -> d0.w short pointer to the new sprite object (0 if the pool is full) */
static inline u16 Sprite_CreateObj(const void *pos, u32 attr, const void *shape, u32 pool)
{
    register const void *d0 __asm__("d0") = pos;
    register u32 d1 __asm__("d1") = attr;
    register const void *a0 __asm__("a0") = shape;
    register u32 a1 __asm__("a1") = pool;
    __asm__ volatile("jsr Sprite_Create_asm" : "+d"(d0), "+d"(d1), "+a"(a0), "+a"(a1) : : "d2", "cc", "memory");
    return (u16)(u32)d0;
}
/* VDP_QueueDma: d0 = kind, d1 = VDP command / length, a0 = source */
static inline void VDP_QueueDma(u16 kind, u32 cmd, const void *src)
{
    register u32 d0 __asm__("d0") = kind;
    register u32 d1 __asm__("d1") = cmd;
    register const void *a0 __asm__("a0") = src;
    __asm__ volatile("jsr VDP_QueueDma_asm" : "+d"(d0), "+d"(d1), "+a"(a0) : : "a1", "cc", "memory");
}
#define SPRITE_POOL 0xFFFFF3A8

/* map helpers with a register argument (d0 = cell) */
static inline u16 Map_GetCell(u16 cell)          /* terrain class; clobbers d1/a1 */
{
    register u32 d0 __asm__("d0") = cell;
    __asm__ volatile("jsr Map_GetCell_asm" : "+d"(d0) : : "d1", "a1", "cc", "memory");
    return (u16)d0;
}
static inline u16 Map_IsPosValid(u16 cell)       /* inside the playable map; clobbers d1 */
{
    register u32 d0 __asm__("d0") = cell;
    __asm__ volatile("jsr Map_IsPosValid_asm" : "+d"(d0) : : "d1", "cc", "memory");
    return (u16)d0;
}
static inline u8 *Team_Get(s16 house)            /* d0 -> a0 */
{
    register s32 d0 __asm__("d0") = house;
    register u8 *a0 __asm__("a0");
    __asm__ volatile("jsr Team_Get_asm" : "=a"(a0), "+d"(d0) : : "cc", "memory");
    return a0;
}

#if WIDE
#define SCREEN_W 480
#define SCREEN_H 464
#else
#define SCREEN_W 320
#define SCREEN_H 224
#endif

/* 32/16 -> 16 bit unsigned division without pulling in libgcc */
static inline u16 divu16(u32 num, u16 den)
{
    __asm__("divu.w %1,%0" : "+d"(num) : "dm"(den) : "cc");
    return (u16)num;
}

/* 32/16 -> 32 bit unsigned division (two divu.w steps, never overflows) */
static inline u32 divu32(u32 num, u16 den)
{
    u32 hi = num >> 16, t;
    u16 qh, ql;
    __asm__("divu.w %1,%0" : "+d"(hi) : "dm"(den) : "cc");   /* hi = rem:quot */
    qh = (u16)hi;
    t = (hi & 0xFFFF0000) | (num & 0xFFFF);
    __asm__("divu.w %1,%0" : "+d"(t) : "dm"(den) : "cc");
    ql = (u16)t;
    return ((u32)qh << 16) | ql;
}

/* signed 32-bit / positive 16-bit, truncating like the original's __divsi3 */
static inline s32 divs32(s32 num, u16 den)
{
    return num < 0 ? -(s32)divu32((u32)-num, den) : (s32)divu32((u32)num, den);
}

#endif
