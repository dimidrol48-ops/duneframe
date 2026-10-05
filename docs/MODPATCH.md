# Mouse + selection box for existing mod ROMs

Hundreds of Dune II (Mega Drive) mods exist, and almost all of them are *data*
edits - new graphics, text, unit stats, maps - of the same "Full Version R82c"
base ROM.  The code never moves, so this repo's mouse and multi-select mods
can be injected into any of them without touching the mod's content:

```sh
make payload                          # once: build build/payload/ from src/c/
tools/modpatch.py SOME_MOD.gen        # -> SOME_MOD_mouse.gen
```

Play the result exactly like `build/mod/dune2.gen`: a Sega Mouse on controller
port 2 (RetroArch / Genesis Plus GX: *MD Mouse*), left-drag (or hold Y on the
pad) for the selection box, double-tap A for all units of a type, triple-tap
for all combat units.

## What it does

1. `make payload` compiles `src/c/input.c` + `src/c/group.c` (plus the hook
   trampolines from `tools/disasm/config.py` `MOD_HOOKS` and the C->asm thunks)
   into a standalone block, linked at the end of the base ROM (`PAYLOAD_BASE`,
   by default the size of `baserom.gen`) with its state in the free RAM block
   FFC380-FFC540 - the same place this repo's own `make mod` build puts it.
   No ROM content is needed to build it, only `baserom.gen`'s size.
2. `tools/modpatch.py` then, for a third-party ROM:
   - checks it is the same size as `baserom.gen`, and that `baserom.gen` is the
     real R82c base (sha1, as in the Makefile);
   - checks the 4 hook sites (6-8 bytes each) and every game routine the
     payload calls (register contracts!) still have the original R82c code,
     by comparing with `baserom.gen`;
   - appends the payload, writes the hook jumps over the hook sites and fixes
     the cartridge header (ROM end + checksum, like `tools/fixheader.py`).

Everything else - the mod's graphics, text, data, even game code it changed
elsewhere - is kept byte for byte as the mod ships it.  Data-only mods always
pass the check; the tool reports what it kept.  A mod that rewired the hooked
code (Input_ReadPad's end, Ui_Frame's order call, the cursor update, the
sprite table build) is refused, because the mouse hooks would replay the wrong
instructions; `--force-code` overrides at your own risk.

The tool never writes anything before the checks pass, and `--check` only
reports:

```sh
tools/modpatch.py SOME_MOD.gen --check     # compatibility report only
```

## What a mod must be like

- **Built on the R82c base.**  The many mod-editor ROMs in the wild are; the
  check against `baserom.gen` proves it.  ROMs built on a different revision
  are refused until that revision gets its own `config.py` addresses.
- **The same size** as the base (0x240000 bytes).
- **Its RAM layout untouched** (data mods are): the payload state lives at
  FFC380-FFC540, which the base game never uses.  A mod that runs its own
  code from that block would clash - there is no way to see that in the ROM
  image, so such (very rare) mods are on the `--force-code` user.
- The mod's own code changes elsewhere are fine and are kept.

## Limits

- The patched ROM carries the mouse/selection code only - not this repo's 74
  decompiled C routines.  That is deliberate: replacing them would silently
  *revert* a mod's changes to those routines.
- 320x224 only.  The 480x464 hack builds are a different base ROM; they would
  need their own `MOD_HOOKS`/`names` configuration.
- The payload grows the ROM past its original size (a few KB), exactly like
  `make mod` does; emulators handle it fine (that is how this repo's release
  ROMs are built).

## Testing a patched ROM

The automated rigs (equiv / lockstep / grouptest) compare against this repo's
own builds and do not apply to third-party ROMs.  What is checked for every
patch: hook sites and called routines byte-identical to the base, payload
linked with no unresolved symbols, `.bss` within the free RAM block, header
checksum recomputed.  Beyond that, play the mod: box-select a group, order it
around, double/triple-tap, right-click to deselect - the same moves
`tools/grouptest.py` makes on the repo's own build.
