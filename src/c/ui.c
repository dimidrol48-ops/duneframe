/* UI flag bytes: read-and-reset helpers. */
#include "dune2.h"

extern u8 g_uiFlags[] RAM(g_uiFlags);
extern void sub_016062(void) ASM(sub_016062);
extern void sub_015E00(void) ASM(sub_015E00);
extern void sub_00C4D4(s16 a, s16 b) ASM(sub_00C4D4);
extern void Sound_PlayHouseVoice(s16 voice) C_IMPL(Sound_PlayHouseVoice);
extern u16 g_uiNesting RAM(g_uiNesting);
void sub_015DCA(s16 a, s16 b) C_IMPL(sub_015DCA);

u32 Ui_TakeFlag(u16 i) C_IMPL(Ui_TakeFlag);
u32 Ui_TakeFlag(u16 i)
{
    u8 v = g_uiFlags[i];
    g_uiFlags[i] = 0;
    return v;
}

u32 Ui_TakeFlagSet(u16 i) C_IMPL(Ui_TakeFlagSet);
u32 Ui_TakeFlagSet(u16 i)
{
    u8 v = g_uiFlags[i];
    g_uiFlags[i] = 0xFF;
    return v;
}

u16 Ui_TakeFlag2(s16 set) C_IMPL(Ui_TakeFlag2);
u16 Ui_TakeFlag2(s16 set)
{
    return set ? Ui_TakeFlagSet(2) : Ui_TakeFlag(2);
}

u16 Ui_TakeFlag1(s16 set) C_IMPL(Ui_TakeFlag1);
u16 Ui_TakeFlag1(s16 set)
{
    return set ? Ui_TakeFlagSet(1) : Ui_TakeFlag(1);
}

void sub_015DCA(s16 a, s16 b) C_IMPL(sub_015DCA);
void sub_015DCA(s16 a, s16 b)
{
    Sound_PlayHouseVoice(-2);
    sub_016062();
    g_uiNesting++;
    sub_00C4D4(b, a);
    sub_015E00();
    g_uiNesting--;
}

/* start mission (a, b); an invalid b restarts the game */
extern void sub_00BAD6(s16 a) ASM(sub_00BAD6);
extern void sub_00F8FE(s16 a, u16 b) ASM(sub_00F8FE);
extern void EntryPoint(void) ASM(EntryPoint);
extern const u8 dat_02591F ASM(dat_02591F);

void sub_015D78(s16 a, u16 b) C_IMPL(sub_015D78);
void sub_015D78(s16 a, u16 b)
{
    if (b > 9) {
        sub_00BAD6(a);
        EntryPoint();
    }
    VDP_CTRL_W = 0x9001;
    if (dat_02591F >= 5)
        sub_00F8FE(a, b);
    sub_015DCA(a, b);
}
