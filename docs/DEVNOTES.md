# Handoff: Dune II (Mega Drive) disassembly → C → Windows

Read this first if you are picking the project up (human or agent). It covers:

- what exists and how it was built;
- how to continue;
- what went wrong and why;
- what to watch out for;
- where it could go: more C, then a native Windows build.

`docs/TECHNICAL.md` has the reference material (layout, switches, C interface, tool list). `CLAUDE.md` has the short working rules.

---

## 1. Goal and inputs

- **Target:** *Dune II: The Battle for Arrakis* for the Sega Mega Drive, in the **"Full Version R82c"** ROM hack by M3tro, which is based on Ti_'s *Rebuild*. The hack is distributed as a 7z with readme files and several ROMs:

  | file | use |
  |---|---|
  | `DuneII_-_The_Battle_For_Arrakis_Full_Version_(R82c).gen` | `baserom.gen` (sha1 `1c5ea483885774ec6649aeb9f5d5a587253557a9`, 2466626 bytes) |
  | `..._(R82c)_480x464.gen` | `variants/wide.gen` (sha1 `b0168348bcdc642f0f4f8d31433f6c4659a81911`, same size) |
  | `..._[T+Rus_wip].gen`, `DuneHack_r82c_x128_S0N!CBLAST.gen` (and 480x464 versions) | not used yet: a Russian translation and a 128x128-map variant (3 MB), likely more builds of the same source |

- **Aims, as set by the user:**
  1. A fully rebuildable disassembly: C where the original was compiled C, assembly elsewhere.
  2. Assets as files.
  3. Quality-of-life mods: mouse, multi-select.
  4. Eventually a native Windows build.
- **Constraint:** the repository must never contain the ROM or anything extracted from it. `make setup` regenerates `src/` and `assets/` from the user's own ROMs. Keep it that way: generated files are gitignored.

## 2. Current state (October 2026)

- `make check` / `make check-wide` rebuild both original ROMs byte for byte from generated sources.
- **Relocatable:** inserting 128 KB of padding into code and data plays identically (`tools/shiftsuite.py`, 47/47 scenarios).
- **Assets:** graphics as 138 indexed PNGs, palettes as text, GEMS sound banks and per-sample WAVs, and the Z80 driver. All are rebuilt into the ROM at build time; LCW-compressed sheets are recompressed.
- **480x464** is a build flag (`WIDE=1`), not a second tree: 90 `.if WIDE` blocks.
- **C:** 74 of 278 compiler-generated routines run as C in `NONMATCHING=1` builds. They are linked at the end of the ROM, with generated ABI adapters. The other ~427 routines (15.5k instructions) are hand-written assembly.
- **Mods** (`MODS=1`):
  - Sega Mouse on port 2.
  - Multi-select: drag box, double / triple click, group orders with formations, corner markers.
  - The mods don't touch the game until used: lockstep with pad input matches the original exactly.
- **Tested** in the test harness (Genesis Plus GX, 320x224) and in the hack's patched Mednafen (480x464, real Sega Mouse protocol).
- **Released to the user:** `build/dist/Dune2_R82c_mouse_multiselect{,_480x464}.gen` from `make mod [WIDE=1]`. The user plays on Windows 10: RetroArch with the hack's patched Genesis Plus GX core, or the patched Mednafen.

## 3. History (what was done, in order)

The development history (with the generated sources committed) is kept in a private repository; the public repository starts from a single fresh commit.

1. **Tracing emulator harness.** Genesis Plus GX libretro, patched (`tools/emu/gpgx_trace.patch`) to log executed PCs, data reads, watchpoints, register snapshots and VDP state. Driven from Python (`tools/emu/harness.py`) with scripted scenarios (`scenario.py`: boot, menus, the Ordos campaign, 41 password-started missions, random "monkey" input).
2. **Disassembler** (`tools/disasm/`): trace-guided code/data separation, jump-table and pointer-table recovery, symbolic output that GNU as reassembles exactly. Raw words are emitted wherever as would "optimise" an encoding.
3. **Relocation.** Every pointer must be a label for code to move. The shift tests found missed pointers one at a time (unexercised paths, odd addresses, tables with unused entries). That was mostly fixed with the second ROM: the 480x464 build is the same source assembled at other addresses, so any value that differs consistently between the two builds is a pointer (`variant_ptrcheck.py`: 76 confirmed, 0 false, 0 missed).
4. **Assets** extracted with runtime palette probing (`tools/assets/probe.py` records which palette line shows each tile block).
5. **480x464 folded in** (`variant.py`): functions matched by masked patterns, the variant disassembled with base-address names, then merged as `.if WIDE` blocks. Screen constants are `SCREEN_W` / `SCREEN_H`.
6. **C integration.**
   - The original compiler used 16-bit int, word/long stack arguments with the caller popping, results in d0 (a0 for pointers), and d0-d2/a0-a1 as scratch. Our C uses normal 32-bit int.
   - The generator writes adapters from the prototypes (`csig.py`): stubs for C replacing asm, thunks for C calling asm.
   - Low ROM is layout-sensitive (see section 6), so a replaced routine keeps its size: a `jmp` to the stub plus `nop`s.
7. **Mods.**
   - Sega Mouse driver and hooks (`MOD_HOOKS`: same-size `jsr`/`jmp` to trampolines) in input, cursor, order handling and sprite building.
   - Multi-select logic in `src/c/group.c`.
8. **Decompilation tests**, from weak to strong:
   - per-function Unicorn equivalence on random inputs (`ctest/equiv.py`);
   - per-function replay of real game states (`ctest/snaptest.py`);
   - whole-game lockstep;
   - **equal-timing lockstep** (see section 5), now the main acceptance test.
9. **Bugs the user hit, and their causes:**
   - **480x464 mod crashed at mission start.** Variant-only pointer tables and immediates had been folded as raw bytes, so they weren't relocated. `variant.py` now rewrites them as labels, 61 of them.
   - **480x464 C build showed a black map.** 480x464-only code used d1 as left by `VDP_SetPlaneA/B`, and the C stub restored it. That led to `C_REGOUT` and `tools/check_regouts.py`.
   - **"Screen ran away right, sprites followed the mouse"** (320x224). Mouse-to-d-pad emulation banked unlimited motion; fixed with a cap. Also, the cursor position is the centre of the bracket, and the mod had assumed the top-left (16 px off).
   - **Why they were missed:** the 480x464 ROM refuses stock emulators (section 6), so every earlier "test" of it only saw a warning screen.
10. **Equal-timing lockstep** found one more real difference. The asm helper `sub_012EE2` borrows d3 and leaves bits in its upper word, and the original `sub_01E212` passes them on to callers that use d3 as an effect position. The C version now reproduces this through `C_REGIN` / `C_REGOUT`.

## 4. Setting up a new machine

Recommended on Windows: **WSL2 with Ubuntu** for building and the agent, and native Windows for playing (Mednafen / RetroArch can open ROMs from `\\wsl$\...`).

`tools/setup/setup-wsl.ps1` (the README's `irm ... | iex` one-liner) does all of this unattended:
- creates the `dune2` distro and a user with passwordless sudo;
- finds the ROMs and `Mednafen*0.9.48*H6*.zip` by checksum / name in the current folder, Downloads, Desktop and Documents;
- `git clone`s the repo (a clone's `origin`, else GitHub; SSH URLs become https) to `~/dune2` and runs `tools/setup/setup.sh`, which does the steps below on any Ubuntu 24.04 (progress display; full output in `build/setup.log`);
- copies Mednafen to `%LOCALAPPDATA%\Programs\dune2` with its own config (seeded from `tools/setup/mednafen.cfg`, the user's play settings) and writes `Play Dune II*.cmd` launchers that run the ROMs from `\\wsl$`. Mednafen saves command-line settings into its config, so the launchers always pass screen size and scale.

Both scripts are safe to re-run; an existing `~/dune2` is used as it is.

```sh
sudo apt install make gcc git python3 python3-numpy python3-pil \
     binutils-m68k-linux-gnu gcc-m68k-linux-gnu p7zip-full
pip install unicorn                 # tools/ctest only
# ROMs: see README; then
make setup                          # generate src/ and assets/, verify exact rebuilds
tools/emu/build_core.sh             # the tracing Genesis Plus GX core (clones GPGX, applies the patch)
```

Optional, for agent-driven 480x464 tests under Linux: `wine` (32-bit, `wine32:i386`), `xvfb`, `xdotool` and `imagemagick`, plus the hack's Mednafen 0.9.48.0.H6 Windows build unpacked in `tools/med/mednafen/`. It's linked in the hack's readme and was on Yandex Disk as `Mednafen 0.9.48.0.H6.zip`. On a native Windows machine just run `mednafen.exe`.

## 5. Workflow: adding C routines (the loop that works)

1. **Pick candidates:** `python3 tools/disasm/classify.py --list c` lists compiled-C routines. Prefer routines that:
   - the scenarios reach (`traces/merged.npz['ex'][addr]`);
   - take stack arguments;
   - call other stack-argument routines or simple register helpers.

   Look at the asm with `MAXL=60 python3 tools/disasm/showfunc.py ADDR ...`.
2. **Write the C** in `src/c/*.c`:

   ```c
   ret name(args) C_IMPL(label);
   ```

   - Original routines called from C: `extern ret name(args) ASM(label);` plus the address in `C_EXPORTS`. A routine without an `ASM()` prototype gets a plain alias, for inline-asm register calls (see the wrappers in `dune2.h`, `misc.c`).
   - C routines in other files: repeat the `C_IMPL` prototype.
   - Avoid libgcc: there is no 32-bit division; use `divu16` / `divu32` / `divs32` in `dune2.h`.
3. **Register it:** `C_FUNCS[addr] = (argbytes, '')` in `tools/disasm/config.py`. If a caller uses a register the original leaves changed, add `C_REGOUT` (and `C_REGIN`).
4. **Regenerate:**

   ```sh
   python3 tools/disasm/generate.py baserom.gen traces/merged.npz src
   python3 tools/disasm/variant.py baserom.gen traces/merged.npz variants/wide.gen WIDE src
   make check check-wide        # must stay byte-identical (C is only in NONMATCHING builds)
   ```

5. **Static check:** `python3 tools/check_regouts.py` must report 0 problems. It checks:
   - every call site of every C routine, in both builds, for registers the original changes (or keeps) that callers then read;
   - every inline `jsr X_asm` in C for registers X changes that the asm statement doesn't declare.
6. **Dynamic check** (the real gate):

   ```sh
   python3 tools/buildvariant.py /tmp/t           # or: make nonmatching
   python3 tools/lockstep_sweep.py baserom.gen /tmp/t/rom.gen /tmp/t/dune2.elf   # 47 scenarios, ~25 min on 4 cores
   ```

   It must say `0/47 scenarios differ`.
   - To bisect a failure: `buildvariant.py OUT --disable a,b,c` or `--only x`, then `lockstep.py baserom.gen OUT/rom.gen SCEN --equal-timing OUT/dune2.elf --stop N`.
   - Then find the writer of the first differing address with the harness watchpoints (`e.watch(lo, hi)` / `watch_log()`, and `snapwatch()` for registers and stack at a PC).
7. **Mods and 480x464:**
   - `make mod`, `tools/grouptest.py` (mouse features), `tools/crashsweep.py build/mod/dune2.gen`.
   - For 480x464: `buildvariant.py OUT --wide --mods --testhw`, then `grouptest.py OUT/rom.gen OUT/dune2.elf`; the user tests the real thing in Mednafen.
8. **Commit.**

### Running all tests

`tools/runtests.sh [quick|full|shift|med|all|STEP ...]` runs everything below; the default is `quick`, and a step name runs one step (`tools/runtests.sh sweep_mod`). Totals: quick 1.5 min; full about 20 min (25 on the first run, which builds the snapshot cache); shift 3 min; med 5 min. Each step logs to `build/tests/<step>.log` and prints one line: `PASS`/`FAIL`, its time, and the log's last line. It exits 1 if any step failed. Prerequisites: `make setup` and `tools/emu/build_core.sh`; `med` also needs the Mednafen setup below. Times were measured on 4 cores; the parallel steps use at most 4 processes.

Expected output of `tools/runtests.sh all` (`quick` is the first seven lines, `full` the first twelve):

```
build          PASS     3s  build/modw/dune2.gen: 2479086 bytes, checksum 5599
layout         PASS     0s  2778 labels below 0106C6: 0 moved, 75 inside C-replaced routines
regouts        PASS     1s  0 problem(s)
equiv          PASS    64s  strcmp                 equivalent (1000 cases)
variants       PASS     2s  build/tests/wide_mod/rom.gen: 74 routines in C
grouptest      PASS     2s  0 failure(s)
grouptest_w    PASS     2s  0 failure(s)
snaptest       PASS    70s  64/75 equivalent, 11 untested, 0 failing
sweep_base     PASS   231s  0/47 scenarios differ
sweep_wide     PASS   225s  0/47 scenarios differ
sweep_mod      PASS   233s  differing: pw_sandimpact pw_sardaukars  (expected: pw_sandimpact pw_sardaukars, double taps)
crash          PASS   210s  pw_totalchaos            ok (20784 frames)
shift          PASS   193s  47/47 passed
med            PASS   286s  build/tests/med/mouse.png
```

The checksums change whenever C or mod code changes. What each step is, and the command to run it by hand:

| step | command | checks |
|---|---|---|
| build | `make check check-wide && make nonmatching mod && make mod WIDE=1` | Both ROMs rebuild byte for byte (`build/dune2.gen: OK`, `build/wide/dune2.gen: OK`); the C and mod builds link. |
| layout | `check_layout.py build/dune2.elf build/mod/dune2.elf`, and the same for `build/wide` / `build/modw` | No label below 0x106C6 moves. |
| regouts | `check_regouts.py` | Static register contract of every C routine at every call site in both builds: `0 problem(s)`. |
| equiv | `ctest/equiv.py [--n 1000]` | Original vs C on random inputs; covers only the 9 small leaf functions that have a `case_*` in the script. Needs `build/nm`. |
| variants | `buildvariant.py build/tests/wide_orig --wide --no-c --testhw`, `... wide_c --wide --testhw`, `... wide_mod --wide --mods --testhw` | The 480x464 test builds the next steps use. `TESTHW` lets them past the emulator check on the stock test core. |
| grouptest, grouptest_w | `grouptest.py`, `grouptest.py build/tests/wide_mod/rom.gen build/tests/wide_mod/dune2.elf` | Six mouse / multi-select checks, each `ok`, then `0 failure(s)`. |
| snaptest | `ctest/states.py` (once), then `ctest/snaptest.py [NAME ...] [--n 24]` | Every C routine (no names = all of them) vs the original from real game states. Needs `build/nm`. "Untested" means no call was captured from the state pool (11 routines: `Ui_TakeFlag1`, `strcmp`, `sub_002656`, `sub_005978`, `sub_005ED6`, `sub_00F78A`, `sub_015D78`, `sub_016D10`, `sub_016D62`, `sub_01D42A`) or the routine never returns (`sub_015DCA`). Only a mismatch fails. The first run builds the 185-state pool (`build/states/pool`, 190 MB) and the snapshot cache (`build/snaps`): about 6 min instead of 70 s. Use `--recapture` after changing the scenarios. |
| sweep_base | `lockstep_sweep.py baserom.gen build/nm/dune2.gen build/nm/dune2.elf` | Equal-timing lockstep of the original vs the C build over all 47 scenarios (up to 65 000 frames): `0/47 scenarios differ`. |
| sweep_wide | `lockstep_sweep.py build/tests/wide_orig/rom.gen build/tests/wide_c/rom.gen build/tests/wide_c/dune2.elf` | The same for 480x464. The baseline is the original 480x464 code with the `TESTHW` hooks (`--wide --no-c --testhw`), not `variants/wide.gen`, which stops at its warning screen on the test core. |
| sweep_mod | `lockstep_sweep.py baserom.gen build/mod/dune2.gen build/mod/dune2.elf -- --elf-a build/nm/dune2.elf --no-y` | The original vs the mod build, with pad input and the Y button dropped (Y-hold is the pad box select). `--elf-a` gives the original the free ranges of the C build, which has the same layout as the original. Two scenarios press A twice quickly enough to fire the mod's double tap (`pw_sardaukars` at frame 7355, `pw_sandimpact` at 10514), so exactly those two must differ. |
| crash | `crashsweep.py build/mod/dune2.gen`, `crashsweep.py build/tests/wide_mod/rom.gen` | No scenario reaches the crash screen. |
| shift | `shiftsuite.py` | Relocation: 128 KB of padding inserted, every scenario frame- and audio-identical: `47/47 passed`. Needed after generator / `config.py` changes, not after C-only changes. |
| med | see below | The real 480x464 build in the patched Mednafen. |

**The `med` tier (Mednafen under wine).**

- Setup (Ubuntu 24.04):
  - `sudo dpkg --add-architecture i386 && sudo apt update && sudo apt install wine wine32:i386 xvfb xdotool imagemagick`
  - Unzip Mednafen 0.9.48.0.H6 into `tools/med/mednafen/` (or point `MEDDIR` at it).
  - The default 64-bit wine prefix works; `mednafen.exe` is 32-bit and runs through `wine32`. No `WINEARCH` is needed.
  - No `mednafen.cfg` is needed. The first run writes `mednafen-09x.cfg` with the defaults, and those are what `medrun.py` relies on: keypad 1/2/3 = A/B/C, w/a/s/d = d-pad, Return = Start. Everything else is on the command line: 6-button pad on port 1, `megamouse` on port 2 with `--mouse`, the 480x464 screen with `--wide`, overclock 7, no sound.
- Under WSLg, `medrun.py` still starts its own Xvfb on `:9` (`MEDDISPLAY`).
- Parallel runs each need their own `MEDDISPLAY`, a copy of the Mednafen directory (`MEDDIR`) and a wine prefix (`MEDPREFIX`).
- The very first wine start creates the prefix and can take a minute.
- The tier writes three strips to `build/tests/med/`:
  - `mouse.png`: `build/modw/dune2.gen` with the real mouse protocol. Expect four in-game frames of mission 1: a green box cursor in each, a different cursor position in the first three, and in the last two the cursor parked right of the map, with the radar box bottom right. The map does not flicker or shift sideways, and there are no stray sprites.
  - `ap_orig.png` / `ap_mod.png`: the original 480x464 code and the mod, each an `AUTOPLAY=1` build of the `mission1` scenario, screenshotted at 20, 40, 60 and 80 s. Expect house select, the mentat briefing, then mission 1 twice, the same in both strips. Small differences in unit positions are fine: Mednafen's timing is not equal, and the C code is slower.
- A person has to look at the pictures. The step passes as long as Mednafen ran.
- Keys in `medrun.py` scripts are timed by wall clock, so run the `mouse` part on an idle machine. The `AUTOPLAY` runs are immune to this.
- On Windows itself, run `mednafen.exe -md.screen_x 480 -md.screen256_x 480 -md.screen_y 464 -md.overclock 7 -md.input.port2 megamouse ROM`.

**Other tools**: one-off diagnostics, not part of any tier.

- `wide_rawptrs.py`: raw bytes in `.if WIDE` blocks that look like pointers. Expected: `1 candidate pointers`, the value 0x000800 in `code_004314.s` (sprite data in low ROM, a false positive).
- `variant_ptrcheck.py variants/wide.gen` (about 15 min): pointer detection checked against the 480x464 layout. It prints suspects to review by hand and has no pass line. Run it after changing `DATA_PTRS` or the analysis.
- `variant_diff.py variants/wide.gen`: instruction diff of the 480x464 hack, for reference only.
- `modshots.py`: title / options / pause screenshots, base vs mod. Only meaningful for `TEXTMODS` text edits.
- `mousebot.py ROM OUT [--frames N] [--seed S]`: plays a mission with mouse and pad and writes `OUT/log.txt`. A pass has no `CRASH` line and no `VDP ...` line once the mission is running: a VDP table address changing mid-mission was the symptom of the old glitch where the screen "moved to the right". Its `inputs.json` becomes an `AUTOPLAY` script with `autoplay.py --log`.
- `test_cfuncs.py`: the old per-function scenario test; superseded by the sweeps.

### How equal-timing lockstep works

The game's pacing follows real time (VBlanks), so slower C code changes when things happen, and two builds drift apart within minutes. The test core can make chosen PC ranges cost no CPU time:

- `harness.free_ranges()`;
- `retro_trace_get(39/40)`;
- `trace_is_free()` in the patch.

`tools/lockstep.py --equal-timing` makes these free in both builds:

- the C code, stubs and thunks;
- the bodies of the replaced routines;
- the mod hook sites;
- asm helpers the C versions do themselves (`inlined_helpers()`);
- the few lookups the mods add (`MOD_CALLS`).

So the original and the C build run on identical cycles and must match in RAM on every compared frame. Rules learned the hard way:

- **Never make a wait loop free** (`WaitDmaQueue`, Z80 bus handshakes): time stops and the frame never ends. That is why not all `C_EXPORTS` are free.
- An asm helper the original calls but the C version inlines must be free in both builds, or the original spends cycles the C build doesn't. `inlined_helpers()` finds these.
- "Code called from free code is free" (dynamic extent) looks elegant but hangs on wait loops. It was tried and reverted.

## 6. Hard-won facts and pitfalls

**The game and the ROM**

- **Low ROM is layout-sensitive.** The original reads through null pointers (the vector table) and uses RAM short addresses as long pointers (it reads ROM around 0xE3A8–0xF000). Never move anything below ~0x106C6 (`tools/check_layout.py`). C replacements keep their size, and hooks overwrite instructions with same-size code.
- **Register contracts.** Hand-written asm passes values in registers freely, and some callers depend on registers a routine merely leaves changed. Callees are not "well behaved" C either: asm helpers clobber d3-d7 and a2-a6 at will.
  - `check_regouts.py` follows control flow and callees transitively.
  - `sub_00B126` returns the caller's d0 unchanged when its distance argument is 0. It is left in asm because C can't reproduce that.
- **Some routines read their caller's frame** (`sub_0142A4` and `sub_00EE52` use a6 set up by the caller). They are not separable functions; leave them or convert them together with their caller.
- **The game restarts itself** when a mission begins (`EntryPoint`, warm path; `sub_000AF0` clears almost all RAM; the VBlank counter goes back to 0). It carries the mission over in SRAM. The `AUTOPLAY` input script keeps its position at FFFFFA, above the initial stack pointer, which the RAM clear doesn't reach.
- **The game uses USP as scratch** (`Sprite_BuildTable` parks SP there), so don't use it for anything.
- **Free RAM:** 0xFFC356–0xFFC574. C `.bss` lives at 0xFFC380 (max 0x1C0, linker-asserted), and the autoplay state at 0xFFC360–C36B. The game clears this RAM at start-up, so C variables start at zero.
- **Cursor:**
  - The cursor position is the centre of its 32x32 bracket; the game takes the cell there (`Cursor_UpdateCell`).
  - The view scrolls when the cursor nears an edge, so aim in world coordinates.
  - Several screens skip the free-cursor update (C/Z held with the d-pad, cursor-attached mode, busy frames). The mouse then falls back to d-pad steps.
- **The RNG** (`Random8`, a 3-byte LFSR at FFE017) is seeded once at power-on and advanced only by game code. Runs are reproducible with the same ROM, input and emulator settings. CPU speed (overclocking, or slower code) changes when events happen, so they get different random numbers.

**The 480x464 build**

- It needs the patched emulators. At start-up (`MegaCD_Detect`, which is misnamed) it runs:
  1. a self-modifying-code prefetch probe;
  2. a VRAM write at 0x10000, i.e. 128 KB VRAM.

  Otherwise it shows "Resolution 480x464 is not supported". `TESTHW=1` neutralises both probes, so its logic runs in the stock test core; the picture is wrong without 128 KB VRAM.
- It uses an HBlank interrupt at line 222 for its tall screen, plus extra VDP writes in VBlank.

**Agent-environment gotchas** (cost real time)

- `pkill -f PATTERN` or `ps | grep PATTERN | kill` can kill your own shell when the command text contains the pattern. Kill by PID from a separate command.
- Background jobs have a time limit; a 47-scenario sweep takes about 4 min on an idle 4-core machine, much longer when other jobs compete.
- Mednafen under wine:
  - its window title is the ROM's file name, so search all visible windows;
  - there is no window manager, so focus by moving the pointer into the window;
  - parallel instances need separate displays and separate wine prefixes;
  - key presses timed by wall clock desync when the CPU is loaded. Use `AUTOPLAY` builds instead: the input script is in the ROM.
- RAM read from the harness at the end of a frame can differ from RAM at VBlank: the game updates scroll and other state mid-frame.

## 7. Plans

**Near term**

1. **Continue C, batch by batch** (section 5). 204 compiled routines are left, 186 of them reached by scenarios.
   - Good next ones: `sub_01E26E`, `sub_00F896`, `sub_00665C`, the `Text_*` / `Gfx_*` helpers, `Map_UpdateCell`, `sprintf`.
   - Use Ghidra's 68000 decompiler (headless) for first drafts of the bigger routines, then fix the types and register details by hand.
2. **Better test content.** Scenarios are scripted plus random input. Real human play would be better:
   - have the user record input in Mednafen (movie files) or RetroArch (`.bsv`);
   - write a converter to `scenario.py` steps or `autoplay.bin`;
   - add them to the lockstep sweep.

   `tools/mousebot.py` already logs replayable sessions (`autoplay.py --log`).
3. **Mouse polish** (ideas partly from db4a, section 9):
   - building placement following the mouse directly instead of d-pad steps;
   - the Construction Yard build menu selectable by pointer;
   - house select and mentat yes/no by pointer;
   - a configurable edge-scroll band.
4. **The 480x464 test loop on Windows:** the user runs Mednafen natively; an agent in WSL can build `AUTOPLAY` ROMs and ask for screenshots.

**Medium term**

5. **Name things.** `names.py` names about 150 routines. More names make the C readable and help a port. Port knowledge from the PC game's decompilation (OpenDUNE): the unit and structure layouts match PC Dune II closely (type numbers 2–17 etc.).
6. **The other ROMs in the archive** (Russian translation, 128x128 maps) could be folded in as variants, like `WIDE`. Each adds pointer ground truth for free.

## 8. More C, and how far it can go

- **The compiled-C part (~280 routines, ~17.5k instructions) can all become C.** Most of it is AI, units, map, UI and the order system. The obstacles are register-argument helpers (wrap them inline, then let `check_regouts` verify) and the occasional frame-sharing or garbage-return routine.
- **The hand-written part (~427 routines, ~15.5k instructions)** is engine and plumbing:
  - VBlank, DMA queue, sprite builder, LCW decompressor;
  - the GEMS sound driver interface (the Z80 driver itself is a binary asset);
  - text rendering, the Rebuild's additions.

  Some of it maps to C with register wrappers. The rest is hardware-specific and would be replaced, not translated, in a port.
- With all compiled code in C, the game logic is portable C sitting on a thin layer of Mega Drive services. That's the natural seam for a port.

## 9. Windows port: options and recommendation

**db4a** (<https://github.com/Vegasq/db4a>, MIT) is a native port of the *European vanilla* Dune Mega Drive cartridge (1 MB, PAL). It works by **static recompilation**: 68000 basic blocks translated to C functions returning the next PC, run by a dispatch loop. The hardware layer is its own SDL2 code: VDP, YM2612, PSG and a Z80 for the sound driver. Its status: mission 1 playable, all houses load, gameplay rendering 99.2% against GPGX, audio not yet right. Ideas worth taking:

- **Instruction semantics defined once** as data, generating both the recompiler and its tests (SingleStepTests 68000 vectors, zexdoc for the Z80).
- **"Native overrides":** a C function replaces a block, and `check-native` runs both and diffs RAM, registers, flags, cycles and the exit PC. This is the same idea as our `C_IMPL`, and our equal-timing lockstep is the whole-game version.
- **Mouse:** write the cursor position directly, with a 24 px scroll band at the screen edges. The build console, house select and mentat answers take the pointer.
- **Widescreen in a port** draws the extra map from the game's map data in RAM, not from VRAM leftovers. The 480x464 hack instead does it inside the ROM with an extended VDP.
- Deterministic input record / replay for bug reports and regression tests, a `docs/journal.md` of what went wrong, and a `CLAUDE.md` of gotchas.
- Its legal approach: its repo *does* include the cartridge, ours does not. Its MIT licence covers only its own code.

**Options for us**

| | approach | effort | result |
|---|---|---|---|
| A | Ship an emulator core (GPGX libretro) in a small Windows frontend with mouse, settings and the ROM | small | runs everywhere now, but it is emulation, not a port |
| B | Static recompilation (db4a's approach, possibly db4a's code adapted to our ROM), hardware layer in SDL2; our C routines become native overrides | large, but bounded | a native .exe early; correctness is checked against GPGX |
| C | Finish decompiling (compiled C, then hand asm), then write a Mega Drive services layer in C/SDL2 | very large | a real source port; easiest to change and extend |

**Recommendation: B, fed by C.**

- Adapting db4a's recompiler and SDL2 layer gets a native build of *this* ROM fastest. db4a is MIT and its hardware work is the hard part.
- Every routine we decompile and verify becomes a native override, so the port gradually stops being recompiled code.
- A is a fallback if players just want a Windows package.

**Port-specific challenges**

- **Different cartridge.** Ours is 2.4 MB, NTSC, with SRAM saves, Mega CD audio (CDDA track playing via `MegaCD_PlayTrack`), and the 480x464 extended-VDP tricks (HBlank at line 222, 128 KB VRAM). db4a's code discovery and memory map would need adapting.
- **Sound.** GEMS runs on the Z80 with YM2612/PSG and DAC samples. Either emulate the Z80 and the chips (db4a does, fidelity still open), or reimplement a GEMS player in C from the extracted banks (`assets/sound/`).
- **Pacing.** The logic is tied to VBlank timing. A port should run the original frame loop at 60 Hz.
- **Rendering fidelity** for a widescreen or high-resolution native mode: render from game state (map, units) instead of the VDP.

## 10. Working with the user

- An experienced programmer who tests in the emulator on Windows 10.
- Releases: build `make mod` and `make mod WIDE=1`, run the checks, and hand over `build/mod/dune2.gen` and `build/modw/dune2.gen` (renamed `Dune2_R82c_mouse_multiselect{,_480x464}.gen`).
