/*
 * Sega Mouse (Mega Mouse) support - MODS build only.
 *
 * The mouse is read on controller port 2 at the end of every Input_ReadPad
 * (the pad stays on port 1).  Buttons act like pad buttons:
 *   left   = A    (in the game view: a click on release, or a drag box)
 *   right  = B
 *   middle = C    (on emulators this is often the wheel)
 *   start  = START
 * In the game view the mouse moves the cursor directly (Cursor_Hook); in
 * menus and in building placement mode its motion is turned into d-pad
 * presses.
 */
#include "dune2.h"
#include "mods.h"

#define IO_DATA2 (*(volatile u8 *)0xA10005)
#define IO_CTRL2 (*(volatile u8 *)0xA1000B)

MouseState g_mouse;

/* wait until TL (bit 4) equals want; the mouse needs a moment per nibble */
static int wait_tl(u8 want)
{
    u16 n;
    for (n = 0; n < 200; n++)
        if ((IO_DATA2 & 0x10) == want)
            return 1;
    return 0;
}

/* Read one packet: 9 nibbles, handshaked on TR/TL.  Returns 0 when no mouse
 * answers (nothing connected, or a pad). */
static int mouse_packet(u8 nib[9])
{
    u16 i;

    IO_CTRL2 = 0x60;            /* TH, TR outputs */
    IO_DATA2 = 0x60;            /* idle */
    IO_DATA2 = 0x20;            /* TH low: start */
    if (!wait_tl(0x10))
        goto fail;
    nib[0] = IO_DATA2 & 0x0F;   /* 0x0B: mouse id */
    if (nib[0] != 0x0B)
        goto fail;              /* a pad or nothing: stop right away */
    for (i = 1; i < 9; i++) {
        u8 tr = (i & 1) ? 0x00 : 0x20;
        IO_DATA2 = tr;
        if (!wait_tl(tr >> 1))
            goto fail;
        nib[i] = IO_DATA2 & 0x0F;
    }
    IO_DATA2 = 0x60;
    return nib[0] == 0x0B && nib[1] == 0x0F && nib[2] == 0x0F;
fail:
    IO_DATA2 = 0x60;
    return 0;
}

#if AUTOPLAY
/* test builds: the mouse comes from the input script (src/autoplay.inc):
 * bytes 4-6 of the current record are dx, dy (screen pixels) and buttons */
static void mouse_read(void)
{
    const s8 *rec = *(const s8 *volatile *)0xFFFFC362;
    if (g_mouse.readFrame == g_vblankCount && g_mouse.present)
        return;
    g_mouse.readFrame = g_vblankCount;
    g_mouse.present = 1;
    if (*(const u16 *)rec == 0) {
        g_mouse.buttons = 0;
        return;
    }
    g_mouse.dx += rec[4];
    g_mouse.dy += rec[5];
    g_mouse.buttons = (u8)rec[6];
}
#else
static void mouse_read(void)
{
    u8 nib[9];
    s16 dx, dy;

    /* without a mouse, only probe about once a second */
    if (!g_mouse.present && (g_vblankCount & 63))
        return;
    /* one packet per frame: some screens read the pad twice in a frame, and
     * emulators report the frame's whole motion on every read */
    if (g_mouse.present && g_mouse.readFrame == g_vblankCount)
        return;
    g_mouse.readFrame = g_vblankCount;
    if (!mouse_packet(nib)) {
        g_mouse.present = 0;
        g_mouse.buttons = 0;
        return;
    }
    g_mouse.present = 1;
    dx = (nib[5] << 4) | nib[6];
    dy = (nib[7] << 4) | nib[8];
    if (nib[3] & 1) dx -= 256;       /* sign bits */
    if (nib[3] & 2) dy -= 256;
    if (nib[3] & 4) dx = (nib[3] & 1) ? -255 : 255;   /* overflow */
    if (nib[3] & 8) dy = (nib[3] & 2) ? -255 : 255;
    g_mouse.dx += dx;
    g_mouse.dy -= dy;                /* the mouse counts up = away from you */
    g_mouse.buttons = nib[4];
}
#endif

/* d-pad presses from mouse motion (menus, placement mode): one step per
 * MENU_STEP pixels of travel.  At most one step is queued: without the cap a
 * fast swipe banks dozens of presses that keep coming after the mouse has
 * stopped (the cursor / placement box runs away and the view scrolls). */
#define MENU_STEP 24
#define MENU_BANK (MENU_STEP * 2 - 1)
static s16 clamp_bank(s16 v)
{
    return v > MENU_BANK ? MENU_BANK : v < -MENU_BANK ? -MENU_BANK : v;
}

static u8 motion_to_dirs(void)
{
    u8 d = 0;
    g_mouse.dx = clamp_bank(g_mouse.dx);
    g_mouse.dy = clamp_bank(g_mouse.dy);
    if (g_mouse.dx >= MENU_STEP)       { d |= PAD_RIGHT; g_mouse.dx -= MENU_STEP; }
    else if (g_mouse.dx <= -MENU_STEP) { d |= PAD_LEFT;  g_mouse.dx += MENU_STEP; }
    if (g_mouse.dy >= MENU_STEP)       { d |= PAD_DOWN;  g_mouse.dy -= MENU_STEP; }
    else if (g_mouse.dy <= -MENU_STEP) { d |= PAD_UP;    g_mouse.dy += MENU_STEP; }
    return d;
}

/* Called at the end of Input_ReadPad with the pad's 'pressed' byte (already
 * stored in g_padPressed); returns the byte the caller should see. */
u16 Input_PadHook(u16 pressed)
{
    u8 held, prev, press = 0, hold = 0, in_game;

    mouse_read();
    if (!g_mouse.present)
        return pressed & 0xFF;

    held = g_mouse.buttons;
    prev = g_mouse.prevButtons;
    g_mouse.prevButtons = held;
    /* the free cursor ran during the last frames: the game view is active */
    in_game = (u16)(g_vblankCount - g_mouse.cursorFrame) < 3;
    if (in_game != g_mouse.wasInGame) {
        /* switching between the free cursor and d-pad mode: drop the motion
         * banked for the other one */
        g_mouse.wasInGame = in_game;
        g_mouse.dx = g_mouse.dy = 0;
    }

    if (held & MB_RIGHT) { hold |= PAD_B; if (!(prev & MB_RIGHT)) press |= PAD_B; }
    if (held & MB_MIDDLE) { hold |= PAD_C; if (!(prev & MB_MIDDLE)) press |= PAD_C; }
    if (held & MB_START) { hold |= PAD_START; if (!(prev & MB_START)) press |= PAD_START; }
    g_mouse.pressed |= held & ~prev;
    g_mouse.released |= prev & ~held;

    if (!in_game) {
        /* menus / placement mode: left is A, motion steps the d-pad (in the
         * game view Cursor_Hook handles both) */
        if (held & MB_LEFT) { hold |= PAD_A; if (!(prev & MB_LEFT)) press |= PAD_A; }
        {
            u8 d = motion_to_dirs();
            press |= d;
            hold |= d;
        }
    }
    g_padHeld |= hold;
    pressed |= press;
    g_padPressed = pressed;
    return pressed & 0xFF;
}
