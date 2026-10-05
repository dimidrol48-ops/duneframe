/* C library routines linked into the original game.  Unlike the game code,
 * these were compiled with 32-bit int (long arguments / results). */
#include "dune2.h"

s32 strlen_(const char *s) C_IMPL(strlen);
s32 strlen_(const char *s)
{
    const char *p = s;

    while (*p)
        p++;
    return p - s;
}

s32 strcmp_(const char *a, const char *b) C_IMPL(strcmp);
s32 strcmp_(const char *a, const char *b)
{
    for (;;) {
        u8 c = *b++;
        if (c == 0)
            return (s8)*a;
        if ((u8)*a != c)
            return (s8)(*a - c);
        a++;
    }
}
