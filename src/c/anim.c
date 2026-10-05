/* Sprite animation state helpers. */
#include "dune2.h"

/* Animation state as used by these helpers (other fields are untouched). */
typedef struct Anim {
    const u8 *frame;      /* +00 current frame data */
    const u8 *script;     /* +04 animation script (see below) */
    u8        pad08[2];
    u8        timer;      /* +0A */
    u8        attr;       /* +0B */
    u8        pad0C[0x34 - 0x0C];
    u8        flags;      /* +34 */
} Anim;

/* Script header: +04 frame data base, +08 pointer to s16 frame offset table
 * (offsets are in words from the base). */
typedef struct AnimScript {
    u32        unused;
    const u8  *base;
    const s16 *offsets;
} AnimScript;

static void anim_reset(Anim *a)
{
    a->frame = 0;
    a->flags = 0;
    a->timer = 0x11;
    a->attr  = 0x0F;
}

/* sub_00CF3E */
void Anim_Start(Anim *a, const u8 *script) C_IMPL(Anim_Start);
void Anim_Start(Anim *a, const u8 *script)
{
    if (!a)
        return;
    anim_reset(a);
    a->script = script;
}

/* sub_00CF62: jump to frame n of the current script.  Returns the Anim
 * pointer (in a0): the original leaves it there and callers use it. */
Anim *Anim_SetFrame(Anim *a, s16 n) C_IMPL(Anim_SetFrame);
Anim *Anim_SetFrame(Anim *a, s16 n)
{
    const AnimScript *s;

    if (!a || !a->script)
        return a;
    s = (const AnimScript *)a->script;
    anim_reset(a);
    /* 32-bit address arithmetic: with -mshort, pointer offsets are 16-bit */
    a->frame = (const u8 *)((u32)s->base + 2 * (s32)s->offsets[n]);
    return a;
}

/* sub_00CFA2: like Anim_SetFrame, with the frame number mapped through a
 * byte table (dat_025E3C) */
extern const u8 k_animFrameMap[] ASM(dat_025E3C);

Anim *Anim_SetFrameMapped(Anim *a, s16 n) C_IMPL(Anim_SetFrameMapped);
Anim *Anim_SetFrameMapped(Anim *a, s16 n)
{
    const AnimScript *s;
    u16 idx;

    if (!a || !a->script)
        return a;
    s = (const AnimScript *)a->script;
    anim_reset(a);
    idx = (u16)(n & 0xFF00) | k_animFrameMap[n];
    a->frame = s->base + 2 * (s32)s->offsets[(s16)idx];
    return a;
}
