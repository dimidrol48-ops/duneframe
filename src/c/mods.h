/* State shared by the MODS=1 features (mouse, multi-select).  Lives in the
 * free RAM block the linker script reserves for .bss (see rom.ld). */
#ifndef MODS_H
#define MODS_H

#define MB_LEFT   0x01
#define MB_RIGHT  0x02
#define MB_MIDDLE 0x04
#define MB_START  0x08

typedef struct MouseState {
    u8  present;          /* a mouse answered on port 2 */
    u8  buttons;          /* MB_* held */
    u8  prevButtons;
    u8  pressed;          /* MB_* newly pressed / released, accumulated until */
    u8  released;         /* the cursor hook consumes them */
    u8  wasInGame;        /* last Input_PadHook saw the free-cursor game view */
    s16 dx, dy;           /* accumulated motion in screen pixels */
    u16 cursorFrame;      /* g_vblankCount when the free cursor last ran */
    u16 readFrame;        /* g_vblankCount of the last packet */
} MouseState;
extern MouseState g_mouse;

u16  Input_PadHook(u16 pressed);
u16  Cursor_Hook(void);
s16  Group_OrderFrame(void);
void Group_DrawMarkers(void);

#endif
