"""Manual knowledge for the disassembler (addresses are base-ROM offsets)."""

# extra code entry points not found automatically
CODE_SEEDS = []

# ranges that must be treated as data
DATA_RANGES = []

# data longwords that look like pointers but are not / must be pointers
# 00E39E/00E3DA: disproved by the 480x464 build (values not relocated there)
NOT_PTRS = [0x00E39E, 0x00E3DA]
# pointers the heuristics missed, proven by the 480x464 build (their values
# moved exactly like their targets; tools/variant_ptrcheck.py)
DATA_PTRS = {
    0x0042D8: 'L',
    0x0042E4: 'L',
    0x004AB2: 'L',
    0x004ABA: 'L',
    0x004AC2: 'L',
    0x004ACA: 'L',
    0x004AD2: 'L',
    0x004ADA: 'L',
    0x004AE2: 'L',
    0x004AEA: 'L',
    0x004AF2: 'L',
    0x004AFA: 'L',
    0x005D50: 'L',
    0x005D5C: 'L',
    0x020524: 'L',
    0x020534: 'L',
    0x020548: 'L',
    0x020550: 'L',
    0x020558: 'L',
    0x020560: 'L',
    0x020564: 'L',
    0x020568: 'L',
    0x02056C: 'L',
    0x020B26: 'L',
    0x020B32: 'L',
    0x020B3E: 'L',
    0x020B4A: 'L',
    0x020B56: 'L',
    0x020B62: 'L',
    0x020B6E: 'L',
    0x020B7A: 'L',
    0x020B86: 'L',
    0x020B92: 'L',
    0x020B9E: 'L',
    0x020BAA: 'L',
    0x020BB6: 'L',
    0x020BC2: 'L',
    0x0211A4: 'L',
    0x021230: 'L',
    # found later: refined variant check (0042E8.., 0205.., 020A9x), and whole
    # tables of routine addresses where only some entries had been proven:
    # behaviour routines 0211C8-0212D8, GEMS driver API table 02402C-024078
    0x0042E8: 'L',
    0x0042EC: 'L',
    0x0042F0: 'L',
    0x020570: 'L',
    0x020580: 'L',
    0x020A90: 'L',
    0x020A94: 'L',
    0x0211CC: 'L',
    0x0211E4: 'L',
    0x021208: 'L',
    0x021228: 'L',
    0x02123C: 'L',
    0x021250: 'L',
    0x021254: 'L',
    0x021258: 'L',
    0x021288: 'L',
    0x021294: 'L',
    0x0212AC: 'L',
    0x0212B0: 'L',
    0x0212C0: 'L',
    0x0212D8: 'L',
    0x02402C: 'L',
    0x024030: 'L',
    0x024034: 'L',
    0x024038: 'L',
    0x024040: 'L',
    0x024044: 'L',
    0x024048: 'L',
    0x02404C: 'L',
    0x024050: 'L',
    0x024054: 'L',
    0x024058: 'L',
    0x02405C: 'L',
    0x024060: 'L',
    0x024064: 'L',
    0x024068: 'L',
    0x024070: 'L',
    0x024074: 'L',
    0x024078: 'L',
}

# ranges excluded from the automatic pointer scan (graphics, sound ...)
NO_PTR_SCAN = []

# instructions whose 32-bit immediate is / is not a ROM pointer
# immediates proven to be pointers by the 480x464 build (tools/variant_ptrcheck.py)
IMM_PTR = [0x01F492, 0x01F498, 0x00BB76, 0x005A78, 0x002768, 0x0027B6]
IMM_NOPTR = []
ABS_NOPTR = []

# instruction addresses to always emit as raw words
RAW_INSNS = []

# file boundaries: start address -> file name (header is implicit at 0)
FILE_SPLITS = {
    0x01FA82: 'data_01FA82',      # C library tables (ctype), misc tables
    0x020FC2: 'code_020FC2',      # graphics set loader
    0x021148: 'data_021148',      # text
    0x023480: 'code_023480',      # exception / debug screen
    0x024000: 'data_024000',      # hack service vector table, graphics
    0x082000: 'data_082000',      # unit / sprite tables
    0x08547E: 'data_08547E',      # Z80 sound driver + GEMS data
    0x1B0000: 'data_1B0000',      # rebuild additions (data, sound)
    0x1BF980: 'code_1BF980',      # rebuild additions (code)
    0x1BFC6C: 'data_1BFC6C',
    0x1C0000: 'data_1C0000',      # graphics
    0x1FD000: 'data_1FD000',      # maps / missions
}

# addresses that always get a label (object boundaries)
FORCE_LABELS = [0x1FA82]

from names import NAMES, RAM_NAMES   # noqa: E402

# functions that have a C implementation in src/c/ (used when NONMATCHING=1):
#   address: (bytes of stack arguments, notes)  - the stub is generated from
#   the C prototype and preserves d1-d2/a0-a1 (a0 is the result for pointers)
# The original routines are partly hand-written and their callers rely on
# registers the routine happens not to touch, even ones the C ABI treats as
# scratch (d1/d2/a0/a1).  The NONMATCHING stub saves those around the C call;
# the lists are what tools/ctest/equiv.py observes the original leaving intact.
# C-replaced routines whose original leaves a second result in a register
# that some caller uses (found by tools/check_regouts.py).  The C version
# stores it in g_cRegOut (src/c/dune2.h) and the stub loads it.
C_REGOUT = {
    0x0021EE: ['d1.w'],     # VDP_SetPlaneA: d1 = register write; WIDE code ORs in the 128K-VRAM bit
    0x00220C: ['d1.w'],     # VDP_SetPlaneB: same
    0x01E212: ['d3.l'],     # sub_01E212: sub_012EE2 leaves bits in d3's upper word; callers use d3
}
# ... and the registers such a C version needs from its caller (g_cRegIn)
C_REGIN = {
    0x01E212: ['d3'],
}

C_FUNCS = {
    0x0009B2: (4, 'd2/a0-a1'),       # Math_MulShr8
    0x0009DA: (8, 'd1-d2/a0-a1'),    # Math_Distance (callers keep data in d1's upper word)
    0x005F5C: (2, 'd2'),             # Sound_PlayFx
    0x00616C: (2, 'd1-d2'),          # Sound_PlayHouseVoice
    0x00CF3E: (8, 'd1-d2/a1'),       # Anim_Start
    0x00CF62: (6, 'd2'),             # Anim_SetFrame
    0x00E7B8: (4, 'd1-d2/a1'),       # Math_Ratio (writes only d1.w)
    0x01F318: (4, 'd1-d2'),          # strlen
    0x01F374: (8, 'd2'),             # strcmp
    # batch 1
    0x002842: (8, ''),               # Cursor_SetBounds
    0x0021D6: (4, ''),               # VDP_SetPlaneSize
    0x0021EE: (2, ''),               # VDP_SetPlaneA
    0x00220C: (2, ''),               # VDP_SetPlaneB
    0x00222A: (2, ''),               # VDP_SetHScrollTable
    0x002248: (2, ''),               # VDP_SetSpriteTable
    0x00246E: (4, ''),               # Sprite_SetPaletteBits
    0x0025DE: (2, ''),               # Ui_TakeFlag
    0x0025F2: (2, ''),               # Ui_TakeFlagSet
    0x00308A: (2, ''),               # Cursor_RememberScroll
    0x009FAE: (6, ''),               # Unit_SetDestCell
    0x00CFEA: (4, ''),               # Anim_IsPlaying
    0x01240E: (4, ''),               # sub_01240E
    0x01E9BA: (4, ''),               # Unit_GetLinked
    0x01E9D6: (4, ''),               # Unit_GetLinkedStructure
    0x002858: (2, ''),               # Cursor_MoveToCell
    0x0191DE: (2, ''),               # sub_0191DE
    0x0042B0: (2, ''),               # Cursor_SetShape
    0x01030E: (2, ''),               # Ui_TakeFlag2
    0x010332: (2, ''),               # Ui_TakeFlag1
    0x015DCA: (4, ''),               # sub_015DCA
    0x0192A8: (2, ''),               # Pos_ToCell
    # batch 2
    0x005ED6: (10, ''),              # sub_005ED6
    0x01242C: (4, ''),               # sub_01242C
    0x01906A: (0, ''),               # sub_01906A
    0x019E42: (4, ''),               # sub_019E42
    0x00F180: (2, ''),               # sub_00F180
    0x01930C: (4, ''),               # sub_01930C
    0x0192D0: (8, ''),               # sub_0192D0
    0x005874: (2, ''),               # sub_005874
    # batch 3
    0x00AFC0: (4, ''),               # Cell_Distance
    0x00CFA2: (6, ''),               # Anim_SetFrameMapped
    0x01901C: (0, ''),               # Sound_Init
    0x015D78: (4, ''),               # sub_015D78
    0x01E212: (4, ''),               # sub_01E212
    0x006DB6: (0, ''),               # sub_006DB6
    0x006EEE: (4, ''),               # sub_006EEE
    0x005978: (4, ''),               # sub_005978
    0x005920: (6, ''),               # sub_005920
    0x0059C6: (6, ''),               # sub_0059C6
    0x0057BC: (2, ''),               # sub_0057BC
    0x00581C: (2, ''),               # sub_00581C
    # batch 4
    0x00F78A: (2, ''),               # sub_00F78A
    # not reached by any scenario yet: 0x016D62: (2, ''),               # sub_016D62
    0x00A9F6: (4, ''),               # sub_00A9F6
    0x01D42A: (4, ''),               # sub_01D42A
    0x019AA0: (0, ''),               # sub_019AA0
    0x0123B8: (4, ''),               # sub_0123B8
    0x01DB7A: (6, ''),               # sub_01DB7A
    0x01EB8C: (4, ''),               # sub_01EB8C
    0x005E56: (4, ''),               # sub_005E56
    # batch 5 (src/c/misc.c)
    0x002166: (2, ''),               # VDP_SetMode
    0x02112C: (4, ''),               # VDP_SetWindow
    0x002186: (2, ''),               # sub_002186
    0x002192: (2, ''),               # sub_002192
    0x002656: (4, ''),               # sub_002656
    0x002AD2: (2, ''),               # sub_002AD2
    0x005516: (0, ''),               # sub_005516
    0x010180: (6, ''),               # sub_010180
    0x016D10: (2, ''),               # sub_016D10
    0x019180: (10, ''),              # sub_019180
    0x0137E0: (4, ''),               # sub_0137E0
    0x006D78: (4, ''),               # sub_006D78
    # batch 6 (src/c/misc.c)
    0x0104CE: (4, ''),               # sub_0104CE
    0x01043C: (4, ''),               # sub_01043C
    0x0153D4: (6, ''),               # sub_0153D4
}
# assembly labels the C code refers to (exported as <name>_asm)
C_EXPORTS = [
    0x0012CA, 0x0029E6, 0x002D42, 0x000F54, 0x006AEE,   # batch 5: WaitDmaQueue, radar, RandomRange, list release
    0x0101B8, 0x025F12,                                # batch 5 tables
    0x00058E, 0x0104AE, 0x010428,                      # batch 6: House_AreEnemies, list tables
    0x01909E, 0x0190E4,   # Gems_StartSequence / Gems_StopSequence
    0x0253BA,             # k_fxToSequence
    0x0061B8,             # k_houseVoiceTables
    0x008C12,             # Order_Frame
    0x00062A, 0x0005BA,   # Map_GetUnitAt / Map_GetStructureAt
    0x002718,             # Selection_Clear
    0x00233C,             # Map_IsCellVisible (register call)
    0x01FD10,             # k_unitPtrs
    0x00969A, 0x01242C, 0x0042D8, 0x000662, 0x0005F2, 0x016062, 0x015E00, 0x00C4D4,
    0x019E6C, 0x024020, 0x019066, 0x02408C,
    0x084282, 0x0842EA, 0x0842CE, 0x08457E, 0x005814, 0x025E3C, 0x00E8E6, 0x012EE2, 0x01EAD6,
    0x01FF10, 0x008B28, 0x0105B8, 0x02403C, 0x02407C, 0x00BAD6, 0x00F8FE, 0x000468, 0x02591F,
    0x0012E6, 0x000A06,
    0x025F2A, 0x021164, 0x00E7FE, 0x003192, 0x000230, 0x002E76, 0x00056C, 0x0831B0, 0x020504,
    0x00EB24, 0x01D350, 0x01F5A4, 0x010356, 0x057F04, 0x082490,
]

# Visible modifications for the MODS=1 build (make mod).  Each entry replaces
# one generated line; string lengths change on purpose, which moves every
# following label (the pause menu string sits in the middle of the code).
# Keep length deltas even so code stays word aligned.
# visible text edits (TEXTMODS=1): they move everything after them in high
# ROM, which tests that the build relocates; not used in the playable builds
MOD_PATCHES = [
    ('\t.asciz\t"Restart mission"', ['\t.asciz\t"Restart the mission"']),         # pause menu, +4 bytes
    ('\t.ascii\t"OPTIONS REBUILD R82c"', ['\t.ascii\t"OPTIONS - DECOMP BUILD"']),  # options title, +2 bytes
    ('\t.asciz\t"SELECT HOUSE"', ['\t.asciz\t"SELECT A HOUSE"']),                 # title menu, +2 bytes
]

# Code hooks for the MODS=1 build.  Low ROM is layout-sensitive (the game
# reads garbage through null / short pointers there), so a hook overwrites
# instructions with same-size code - a jmp/jsr to a trampoline linked with
# the C code - and the trampoline replays what it overwrote.
#   address: size (bytes overwritten), code (same size), tramp (out of line)
MOD_HOOKS = {
    # test builds only: replace the pad hardware read with a frame-indexed
    # input script, so a test plays back identically on any emulator
    0x0011CA: {'what': 'Input_ReadPad: scripted input (tools/autoplay.py)', 'size': 6,
               'flag': 'AUTOPLAY', 'label': 'autoplay',
               'code': ['\tjmp\t(Autoplay_ReadPad).l'],
               'tramp': ['\t.include\t"autoplay.inc"']},
    # test builds only: pass the 480x464 build's emulator check (prefetch and
    # 128K-VRAM probes) on a stock emulator, so its game logic can run in the
    # test harness (graphics will be wrong without 128K VRAM)
    0x01F7E8: {'what': 'MegaCD_Detect: ignore the prefetch probe', 'size': 2, 'flag': 'TESTHW',
               'label': 'testhw1', 'code': ['\tnop']},
    0x01F802: {'what': 'MegaCD_Detect: ignore the VRAM-size probe', 'size': 2, 'flag': 'TESTHW',
               'label': 'testhw2', 'code': ['\tnop']},
    0x001242: {'what': 'end of Input_ReadPad: merge the Sega Mouse (port 2)', 'size': 6,
               'code': ['\tjmp\t(Hook_ReadPad).l'],
               'tramp': ['Hook_ReadPad:',
                         '\tand.b\td1,d0',
                         '\tmove.b\td0,-(a1)',
                         '\tmovem.l\td0-d2/a0-a1,-(sp)',
                         '\tmove.l\td0,-(sp)\t\t| C argument slot (value in the low word)',
                         '\tjsr\t(Input_PadHook).l\t\t| returns the new pressed byte',
                         '\taddq.l\t#4,sp',
                         '\tmove.b\td0,3(sp)\t\t| low byte of the saved d0',
                         '\tmovem.l\t(sp)+,d0-d2/a0-a1',
                         '\trts']},
    0x00274A: {'what': 'Ui_Frame: group orders / multi-select', 'size': 6,
               'code': ['\tjsr\t(Group_OrderFrame).l']},
    0x003E78: {'what': 'cursor update (VBlank): mouse movement, drag box', 'size': 8,
               'code': ['\tjsr\t(Hook_Cursor).l', '\tnop'],
               'tramp': ['Hook_Cursor:',
                         '\tmovem.l\td0-d2/a0-a1,-(sp)',
                         '\tjsr\t(Cursor_Hook).l\t\t| returns pad bits (a mouse click)',
                         '\tor.b\td0,d5\t\t| d5: this frame\'s buttons for sub_0037F0',
                         '\tmovem.l\t(sp)+,d0-d2/a0-a1',
                         '\tjsr\t(Cursor_UpdateCell).l',
                         '\tjmp\t(sub_0037F0).l']},
    0x004002: {'what': 'after the sprite table is built (VBlank): selection markers', 'size': 8,
               'code': ['\tjmp\t(Hook_Sprites).l', '\tnop'],
               'tramp': ['Hook_Sprites:',
                         '\tjsr\t(Sprite_BuildTable).l',
                         '\tmovem.l\td0-d2/a0-a1,-(sp)',
                         '\tjsr\t(Group_DrawMarkers).l',
                         '\tmovem.l\t(sp)+,d0-d2/a0-a1',
                         '\tjmp\t(loc_002D70).l']},
}
