/* Sound effect / voice helpers on top of the GEMS driver interface. */
#include "dune2.h"

/* sub_005F5C: play a sound effect by game id */
void Sound_PlayFx(s16 id) C_IMPL(Sound_PlayFx);
void Sound_PlayFx(s16 id)
{
    u8 seq;

    if (!g_soundEnabled)
        return;
    seq = k_fxToSequence[id];
    if (seq != 0xFF)
        Gems_StartSequence(seq);
}

/* sub_00616C: play a voice line in the player's house voice set; a new
 * voice stops the previous one first. */
void Sound_PlayHouseVoice(s16 id) C_IMPL(Sound_PlayHouseVoice);
void Sound_PlayHouseVoice(s16 id)
{
    u8 seq;

    if (!g_soundEnabled)
        return;
    seq = k_houseVoiceTables[g_playerHouse][id];
    if (seq == 0xFF)
        return;
    if (g_lastVoice != seq) {
        Gems_StopSequence(g_lastVoice);
        g_lastVoice = seq;
    }
    Gems_StartSequence(seq);
}

/* ---- sound driver start-up (GEMS API through the table at 0x24000) */
extern const void *const k_gemsInit ASM(dat_024020);        /* bank setup */
extern const void *const k_gemsReset ASM(dat_02403C);
extern const u8 k_gemsNoBank[] ASM(dat_019066);             /* FF FF FF FF */
extern const void *const k_gemsBank1[4] ASM(dat_02407C);
extern const void *const k_gemsBank2[4] ASM(dat_02408C);
typedef void (*GemsBankFn)(const void *, const void *, const void *, const void *);

/* the original pushes the 4 table pointers in order, so the callee sees
 * them reversed */
static void gems_bank(const void *const *t)
{
    GemsBankFn f = (GemsBankFn)k_gemsInit;
    f(t[3], t[2], t[1], t[0]);
}

static void gems_no_bank(void)
{
    GemsBankFn f = (GemsBankFn)k_gemsInit;
    f(k_gemsNoBank, k_gemsNoBank, k_gemsNoBank, k_gemsNoBank);
}

/* sub_01901C */
void Sound_Init(void) C_IMPL(Sound_Init);
void Sound_Init(void)
{
    ((void (*)(void))k_gemsReset)();
    gems_no_bank();
    gems_bank(k_gemsBank1);
    g_inputEventNext = 0;
    g_inputEvent = 0;
    *(volatile u16 *)&g_padPressed = 0;
}

/* sub_01906A */
void Sound_InitBank2(void) C_IMPL(Sound_InitBank2);
void Sound_InitBank2(void)
{
    gems_no_bank();
    gems_bank(k_gemsBank2);
}
