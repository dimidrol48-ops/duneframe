/*
 * Multi-select (MODS build).
 *
 * The game only knows one selected unit (g_selectedObject).  A group keeps
 * that one as its "primary" and remembers the others; when the player gives
 * an order, the game's own order code (Order_Frame) runs once for every
 * member, so each unit gets exactly the order it would get on its own
 * (harvesters harvest, attackers attack ...).  Move orders get a small
 * formation so the units do not all queue for one cell.
 *
 * Selecting a group:
 *   - drag a box with the mouse (left button), or hold Y on the pad, move the
 *     cursor and release Y
 *   - tap A twice on a unit: all of your units of that type on screen
 *   - tap A three times: all combat units (or all harvesters/MCVs) on screen
 * Clicking one of your units while a group is selected selects just that
 * unit; B (or anything that deselects) drops the group.
 */
#include "dune2.h"
#include "mods.h"

#define GROUP_MAX   24
#define TAP_FRAMES  24          /* max frames between taps */
#define BOX_MIN     12          /* pixels of drag before it becomes a box */

enum { BOX_NONE, BOX_MOUSE_PENDING, BOX_MOUSE, BOX_PAD };

typedef struct GroupState {
    u8    count;
    u8    taps;
    u8    box;
    u8    boxPending;
    Unit *unit[GROUP_MAX];      /* unit[0] is the primary (g_selectedObject) */
    Unit *tapUnit;
    u16   tapFrame;
    s16   bx0, by0, bx1, by1;   /* box corners, world pixels */
    u8    prevExt;
    u8    selecting;            /* inside our own simulated click */
} GroupState;

static GroupState G;

extern volatile s16 g_playerHouse RAM(g_playerHouse);
extern volatile u8  g_soundEnabled RAM(g_soundEnabled);

/* sub_00233C: register call, d0 = cell -> d0 = 1 if the cell is not fogged */
static s16 cell_visible(u16 cell)
{
    register u32 d0 __asm__("d0") = cell;
    __asm__ volatile("jsr Map_IsCellVisible_asm" : "+d"(d0) : : "a0", "cc", "memory");
    return (s16)d0;
}

static int is_unit(Unit *u)
{
    return u && u->handle < UNIT_SLOTS && k_unitPtrs[u->handle] == u;
}

static int selectable_type(u8 t)
{
    return t >= 2 && t <= 17;       /* infantry, vehicles, harvester, MCV */
}

static int own_unit(Unit *u)
{
    return is_unit(u) && UNIT_ALIVE(u) && u->house == g_playerHouse && selectable_type(u->type);
}

static u8 unit_class(u8 t)
{
    return t >= 16 ? 2 : 1;         /* 2: harvester / MCV, 1: combat */
}

static int on_screen(Unit *u)
{
    s16 x = UNIT_PX(u) - g_scrollX, y = UNIT_PY(u) - g_scrollY;
    return x >= g_cursor.xmin - 24 && x < g_cursor.xmax + 24 &&
           y >= g_cursor.ymin - 24 && y < g_cursor.ymax + 24 && cell_visible(UNIT_CELL(u));
}

static void group_clear(void)
{
    G.count = 0;
}

/* Select u the way a click on it would (sounds, side panel ...). */
static Unit *click_select(Unit *u)
{
    u8 ev = g_inputEvent;
    u16 cell = g_cursorPos;
    Unit *cur = (Unit *)g_selectedObject;

    if (cur) {
        cur->uiFlags &= ~(UF_SELECTED | UF_PLAYER_SEL);
        g_selectedObject = 0;
        Selection_Clear();
    }
    G.selecting = 1;
    g_cursorPos = UNIT_CELL(u);
    g_inputEvent = 'A';
    Order_Frame();
    g_inputEvent = ev;
    g_cursorPos = cell;
    G.selecting = 0;
    return (Unit *)g_selectedObject;
}

/* list[0..n) -> the selection; list[0] becomes the primary */
static void select_list(Unit **list, u8 n)
{
    Unit *prim;
    u8 i;

    if (!n)
        return;
    prim = click_select(list[0]);
    group_clear();
    if (!own_unit(prim))
        return;
    G.unit[G.count++] = prim;
    for (i = 0; i < n && G.count < GROUP_MAX; i++)
        if (list[i] != prim && own_unit(list[i]))
            G.unit[G.count++] = list[i];
    if (G.count < 2)
        group_clear();
}

/* all own units on screen like u (same type, or same class when wide) */
static void select_similar(Unit *u, int wide)
{
    Unit *list[GROUP_MAX];
    u8 n = 0;
    u16 i;

    list[n++] = u;
    for (i = 0; i < UNIT_SLOTS && n < GROUP_MAX; i++) {
        Unit *v = k_unitPtrs[i];
        if (v == u || !own_unit(v) || !on_screen(v))
            continue;
        if (wide ? unit_class(v->type) == unit_class(u->type) : v->type == u->type)
            list[n++] = v;
    }
    select_list(list, n);
}

static void box_select(void)
{
    Unit *list[GROUP_MAX];
    s16 x0 = G.bx0, x1 = G.bx1, y0 = G.by0, y1 = G.by1, t;
    u8 n = 0;
    u16 i;

    if (x0 > x1) { t = x0; x0 = x1; x1 = t; }
    if (y0 > y1) { t = y0; y0 = y1; y1 = t; }
    for (i = 0; i < UNIT_SLOTS && n < GROUP_MAX; i++) {
        Unit *v = k_unitPtrs[i];
        s16 x, y;
        if (!own_unit(v) || !cell_visible(UNIT_CELL(v)))
            continue;
        x = UNIT_PX(v); y = UNIT_PY(v);
        if (x >= x0 && x <= x1 && y >= y0 && y <= y1)
            list[n++] = v;
    }
    select_list(list, n);
}

/* ring positions around the clicked cell for move orders */
static const s8 k_formation[][2] = {
    { 0, 0}, { 1, 0}, { 0, 1}, {-1, 0}, { 0,-1}, { 1, 1}, {-1, 1}, { 1,-1}, {-1,-1},
    { 2, 0}, { 0, 2}, {-2, 0}, { 0,-2}, { 2, 1}, {-2, 1}, { 2,-1}, {-2,-1},
    { 1, 2}, {-1, 2}, { 1,-2}, {-1,-2}, { 2, 2}, {-2, 2}, { 2,-2},
};

static u16 formation_cell(u16 cell, u8 k)
{
    s16 x = (cell & 63) + k_formation[k][0];
    s16 y = (cell >> 6) + k_formation[k][1];
    if (x < 0) x = 0;
    if (x > 63) x = 63;
    if (y < 0) y = 0;
    if (y > 63) y = 63;
    return (u16)(y << 6 | x);
}

/* The primary already took the click; give the same order to the rest. */
static void group_order(Unit *prim)
{
    u16 cell = g_cursorPos;
    Unit *hit = Map_GetUnitAt(cell);
    int spread = !hit && !Map_GetStructureAt(cell);   /* plain ground: move */
    u8 sticky = g_noCancel, snd = g_soundEnabled;
    u8 i, k = 0;

    g_noCancel = 1;                 /* 'No Cancel' control: keep the selection */
    Order_Frame();
    if (g_selectedObject != prim) { /* the click did something else */
        g_noCancel = sticky;
        group_clear();
        return;
    }
    g_soundEnabled = 0;             /* one acknowledgement is enough */
    for (i = 1; i < G.count; i++) {
        Unit *u = G.unit[i];
        if (!own_unit(u))
            continue;
        u->uiFlags |= UF_SELECTED | UF_PLAYER_SEL;
        g_selectedObject = u;
        g_cursorPos = cell;
        g_orderCellOverride = spread ? formation_cell(cell, ++k) : 0;
        Order_Frame();
        g_orderCellOverride = 0;
        u->uiFlags &= ~(UF_SELECTED | UF_PLAYER_SEL);
    }
    g_soundEnabled = snd;
    g_selectedObject = prim;
    prim->uiFlags |= UF_SELECTED | UF_PLAYER_SEL;
    g_cursorPos = cell;
    g_noCancel = sticky;
}

/* drop dead members; follow the game when it changes the selection */
static void group_validate(void)
{
    Unit *prim = (Unit *)g_selectedObject;
    u8 i, n = 0;

    if (!G.count)
        return;
    if (prim != G.unit[0]) {
        if (!prim && !own_unit(G.unit[0])) {
            /* the primary died: promote the next living member */
            for (i = 1; i < G.count; i++)
                if (own_unit(G.unit[i])) {
                    Unit *list[GROUP_MAX];
                    u8 j, m = 0;
                    for (j = i; j < G.count; j++)
                        list[m++] = G.unit[j];
                    select_list(list, m);
                    return;
                }
        }
        group_clear();
        return;
    }
    for (i = 0; i < G.count; i++)
        if (own_unit(G.unit[i]))
            G.unit[n++] = G.unit[i];
    G.count = n < 2 ? 0 : n;
}

/* replaces the call of Order_Frame in Ui_Frame (once per game frame) */
s16 Group_OrderFrame(void)
{
    Unit *prim, *hit;
    u16 now = g_vblankCount;

    group_validate();
    if (G.boxPending) {
        G.boxPending = 0;
        box_select();
        return 1;
    }
    if (g_inputEvent != 'A')
        return Order_Frame();

    prim = (Unit *)g_selectedObject;
    /* look at the unit under the cursor only when a group or a second tap is
     * possible: otherwise the game runs exactly as without the mod */
    if (G.count >= 2 || (G.tapUnit && (u16)(now - G.tapFrame) <= TAP_FRAMES)) {
        hit = Map_GetUnitAt(g_cursorPos);
        if (!own_unit(hit))
            hit = 0;

        /* second / third tap on the selected unit */
        if (hit && hit == prim && hit == G.tapUnit && (u16)(now - G.tapFrame) <= TAP_FRAMES) {
            G.tapFrame = now;
            if (G.taps < 3)
                G.taps++;
            select_similar(hit, G.taps >= 3);
            G.tapUnit = (Unit *)g_selectedObject;
            return 1;
        }
        if (G.count >= 2 && prim == G.unit[0]) {
            if (hit) {              /* click on one of our units: select it alone */
                group_clear();
                click_select(hit);
            } else {
                group_order(prim);
            }
            G.tapUnit = (Unit *)g_selectedObject == hit ? hit : 0;
            G.tapFrame = now;
            G.taps = 1;
            return 1;
        }
    }
    {
        s16 r = Order_Frame();
        Unit *sel = (Unit *)g_selectedObject;
        if (sel != prim && own_unit(sel)) {
            G.tapUnit = sel;        /* a plain selection: first tap */
            G.tapFrame = now;
            G.taps = 1;
        } else {
            G.tapUnit = 0;
        }
        return r;
    }
}

/* ---------------------------------------------------------------- VBlank */

static s16 iabs(s16 v) { return v < 0 ? -v : v; }

/* In the free-cursor update, before the cursor cell is computed.  Returns
 * pad bits to add to this frame's buttons (a mouse click). */
u16 Cursor_Hook(void)
{
    s16 wx, wy;
    u8 ext = g_padExtHeld, click = 0;

    g_mouse.cursorFrame = g_vblankCount;
    if (g_mouse.dx || g_mouse.dy) {
        s16 x = g_cursor.x + g_mouse.dx, y = g_cursor.y + g_mouse.dy;
        g_mouse.dx = g_mouse.dy = 0;
        if (x < g_cursor.xmin) x = g_cursor.xmin;
        if (x > g_cursor.xmax) x = g_cursor.xmax;
        if (y < g_cursor.ymin) y = g_cursor.ymin;
        if (y > g_cursor.ymax) y = g_cursor.ymax;
        g_cursor.x = x;
        g_cursor.y = y;
    }
    /* the cursor position is the centre of its bracket: the game takes the
     * cell there (Cursor_UpdateCell) */
    wx = g_cursor.x + g_scrollX;
    wy = g_cursor.y + g_scrollY;

    /* mouse: click on release, box when dragged */
    if ((g_mouse.pressed & MB_LEFT) && G.box == BOX_NONE) {
        G.box = BOX_MOUSE_PENDING;
        G.bx0 = G.bx1 = wx;
        G.by0 = G.by1 = wy;
    }
    if (G.box == BOX_MOUSE_PENDING || G.box == BOX_MOUSE) {
        G.bx1 = wx;
        G.by1 = wy;
        if (iabs(wx - G.bx0) > BOX_MIN || iabs(wy - G.by0) > BOX_MIN)
            G.box = BOX_MOUSE;
        if (g_mouse.released & MB_LEFT) {
            if (G.box == BOX_MOUSE)
                G.boxPending = 1;
            else
                click = PAD_A;
            G.box = BOX_NONE;
        }
    }
    g_mouse.pressed = g_mouse.released = 0;

    /* pad: hold Y, move, release Y (Y+A / Y+B keep their meaning) */
    if ((ext & PADX_Y) && !(G.prevExt & PADX_Y) && G.box == BOX_NONE) {
        G.box = BOX_PAD;
        G.bx0 = G.bx1 = wx;
        G.by0 = G.by1 = wy;
    }
    if (G.box == BOX_PAD) {
        G.bx1 = wx;
        G.by1 = wy;
        if (g_padHeld & (PAD_A | PAD_B))
            G.box = BOX_NONE;
        else if (!(ext & PADX_Y)) {
            if (iabs(wx - G.bx0) > BOX_MIN || iabs(wy - G.by0) > BOX_MIN)
                G.boxPending = 1;
            G.box = BOX_NONE;
        }
    }
    G.prevExt = ext;
    return click;
}

/* ---- sprites appended to the game's sprite table */
#define SPR_MAX       80
#define TILE_CORNER   0x07FA          /* free tile at VRAM FF40 (after the UI sprites) */
#define ATTR_CORNER   (0x8000 | TILE_CORNER)
#define VDP_DATA      (*(volatile u16 *)0xC00000)
#define VDP_CTRL_L    (*(volatile u32 *)0xC00004)

/* corner bracket, 4bpp: 9 = yellow, C = black in every in-game palette */
static const u32 k_cornerTile[8] = {
    0x999999C0, 0x999999C0, 0x99CCCC00, 0x99C00000,
    0x99C00000, 0x99C00000, 0xCC000000, 0x00000000,
};

static void upload_corner_tile(void)
{
    u16 sr, i;
    __asm__ volatile("move.w %%sr,%0; move.w #0x2700,%%sr" : "=d"(sr) : : "memory");
    /* 32-bit maths: with -mshort, int is 16 bits and 0x7FA*32 would overflow */
    VDP_CTRL_L = 0x40000000UL | (((u32)TILE_CORNER * 32 & 0x3FFF) << 16) | ((u32)TILE_CORNER * 32 >> 14);
    for (i = 0; i < 8; i++) {
        VDP_DATA = (u16)(k_cornerTile[i] >> 16);
        VDP_DATA = (u16)k_cornerTile[i];
    }
    __asm__ volatile("move.w %0,%%sr" : : "d"(sr) : "memory");
}
#define HFLIP         0x0800
#define VFLIP         0x1000

static u16 spr_n;

static void spr_put(s16 x, s16 y, u16 attr)
{
    u8 *e;
    if (spr_n >= SPR_MAX || x <= -8 || y <= -8 || x >= SCREEN_W || y >= SCREEN_H)
        return;
    e = g_spriteTable + (spr_n << 3);
    *(u16 *)e = (u16)(y + 128);
    e[2] = 0;                           /* 1x1 tile */
    e[3] = (u8)(spr_n + 1);
    *(u16 *)(e + 4) = attr;
    *(u16 *)(e + 6) = (u16)(x + 128);
    spr_n++;
}

void Group_DrawMarkers(void)
{
    u16 first = g_spriteCount4 >> 2;
    s16 sx = g_scrollX, sy = g_scrollY;
    u8 i;

    if (!first || first >= SPR_MAX)
        return;
    spr_n = first;
    if (G.box == BOX_MOUSE || G.box == BOX_PAD) {
        s16 x0 = G.bx0 - sx, x1 = G.bx1 - sx, y0 = G.by0 - sy, y1 = G.by1 - sy, t;
        if (x0 > x1) { t = x0; x0 = x1; x1 = t; }
        if (y0 > y1) { t = y0; y0 = y1; y1 = t; }
        spr_put(x0, y0, ATTR_CORNER);
        spr_put(x1 - 8, y0, ATTR_CORNER | HFLIP);
        spr_put(x0, y1 - 8, ATTR_CORNER | VFLIP);
        spr_put(x1 - 8, y1 - 8, ATTR_CORNER | HFLIP | VFLIP);
    }
    for (i = 0; i < G.count; i++) {
        Unit *u = G.unit[i];
        s16 cx, cy;
        if (!own_unit(u))
            continue;
        cx = UNIT_PX(u) - sx;
        cy = UNIT_PY(u) - sy;
        if (cx < g_cursor.xmin - 24 || cx >= g_cursor.xmax + 24 || cy < g_cursor.ymin - 24 || cy >= g_cursor.ymax + 24)
            continue;
        spr_put(cx - 11, cy - 11, ATTR_CORNER);
        spr_put(cx + 3, cy + 3, ATTR_CORNER | HFLIP | VFLIP);
    }
    if (spr_n != first) {
        upload_corner_tile();
        g_spriteTable[((first - 1) << 3) + 3] = (u8)first;   /* link the old last entry */
        g_spriteTable[((spr_n - 1) << 3) + 3] = 0;
        g_spriteCount4 = spr_n << 2;
    }
}
