/* Map cursor helpers. */
#include "dune2.h"

extern u32 g_scrollCopy   RAM(g_scrollCopy);     /* scroll x:y copied every frame */
extern u32 g_savedScroll  RAM(g_savedScroll);
extern u16 g_savedScrollArg RAM(g_savedScrollArg);
extern u16 g_cursorSprite RAM(g_cursorSprite);   /* short pointer to the cursor's sprite */
extern void *const k_cursorShapes[] ASM(k_cursorShapes);

/* clamp area of the free cursor (screen pixels) */
void Cursor_SetBounds(s16 xmin, s16 ymin, s16 xmax, s16 ymax) C_IMPL(Cursor_SetBounds);
void Cursor_SetBounds(s16 xmin, s16 ymin, s16 xmax, s16 ymax)
{
    g_cursor.xmin = xmin;
    g_cursor.ymin = ymin;
    g_cursor.xmax = xmax;
    g_cursor.ymax = ymax;
}

/* put the cursor on a map cell (the x:y pair is one long in the original,
 * so a borrow from y carries into x) */
void Cursor_MoveToCell(u16 cell) C_IMPL(Cursor_MoveToCell);
void Cursor_MoveToCell(u16 cell)
{
    u32 xy = (u32)((cell & 0x3F) << 5) << 16 | (u16)((cell & 0xFC0) >> 1);
    *(u32 *)&g_cursor.x = xy - g_scrollCopy;
}

/* remember the scroll position unless the player is scrolling (C / Z held) */
void Cursor_RememberScroll(u16 arg) C_IMPL(Cursor_RememberScroll);
void Cursor_RememberScroll(u16 arg)
{
    if (g_padHeld & PAD_C)
        return;
    if (g_padExtHeld & PADX_Z)
        return;
    if (RAM8(0xFFC019) & 8)
        return;
    g_savedScroll = *(u32 *)&g_scrollX;
    g_savedScrollArg = arg;
}

/* cursor sprite shape; negative hides it */
typedef struct SpriteObj { u8 pad[7]; u8 flags; const void *shape; } SpriteObj;

void Cursor_SetShape(s16 shape) C_IMPL(Cursor_SetShape);
void Cursor_SetShape(s16 shape)
{
    SpriteObj *s;
    if (!g_cursorSprite)
        return;
    s = SHORTPTR(SpriteObj, g_cursorSprite);
    if (shape < 0) {
        s->flags |= 0x80;
        return;
    }
    s->shape = k_cursorShapes[shape];
    s->flags &= ~0x80;
}

/* packed map position (0xC000 | row<<8 | col<<1) or a cell index -> cell */
u16 Pos_ToCell(u16 p) C_IMPL(Pos_ToCell);
u16 Pos_ToCell(u16 p)
{
    if ((p & 0xC000) == 0xC000)
        return (u16)((p & 0x3F00) >> 2) | (u16)((p & 0x7E) >> 1);
    return p & 0x3FFF;
}

/* blinking of the object at C862 (flag on: count down C866 / C864 by the
 * frame step at FFFE) */
void sub_005874(s16 on) C_IMPL(sub_005874);
void sub_005874(s16 on)
{
    u8 *o = SHORTPTR(u8, RAM16(0xFFFFC862));
    s16 step;
    if (!on) {
        RAM16(0xFFFFC864) = 0x5A;
        RAM16(0xFFFFC866) = 0;
        o[7] |= 0x81;
        return;
    }
    if (!(o[7] & 1))
        return;
    step = (s16)RAM16(0xFFFFFFFE);
    if ((s16)RAM16(0xFFFFC866) >= 0) {
        RAM16(0xFFFFC866) -= step;
        return;
    }
    RAM16(0xFFFFC864) -= step;
    if ((s16)RAM16(0xFFFFC864) < 0) {
        RAM16(0xFFFFC866) = 0x384;
        RAM16(0xFFFFC864) = 0x3C;
        o[7] |= 0x80;
    } else {
        o[7] &= ~0x80;
    }
}
