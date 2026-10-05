# Working notes for agents

Read `HANDOFF.md` (history, workflow, pitfalls, plans) before changing anything. Reference material is in `docs/TECHNICAL.md`.

## Rules

- **Never commit the ROM or anything derived from it.** That covers `src/*.s` and the other generated `src/` files, `assets/gfx|palettes|sound`, screenshots, RAM dumps and save states. `make setup` regenerates them; `.gitignore` enforces it.
- **Never edit generated `src/` files.** Change `tools/disasm/config.py` / `names.py` / `src/c/` and regenerate:

  ```sh
  python3 tools/disasm/generate.py baserom.gen traces/merged.npz src
  python3 tools/disasm/variant.py baserom.gen traces/merged.npz variants/wide.gen WIDE src
  make check check-wide
  ```

- **All tests:** `tools/runtests.sh full` (about 20 min), plus `shift` after generator changes. Expected output: HANDOFF.md, "Running all tests".
- **Gate for any C change:**
  1. `make check check-wide` byte-identical;
  2. `python3 tools/check_regouts.py` reports 0 problems;
  3. `python3 tools/lockstep_sweep.py baserom.gen OUT/rom.gen OUT/dune2.elf` says `0/47 scenarios differ`, where `OUT` is from `tools/buildvariant.py OUT`.
- **Gate for mod changes:** `tools/grouptest.py`, `tools/crashsweep.py build/mod/dune2.gen`, and the 480x464 logic via `buildvariant.py OUT --wide --mods --testhw`. The user tests the real 480x464 build in Mednafen.
- Nothing below ~0x106C6 may move (`tools/check_layout.py`).

## Gotchas

- Don't kill processes with `pkill -f` / `grep | kill` on a pattern that appears in your own command line.
- A free (zero-cost) range in equal-timing lockstep must never contain a wait loop.
- The 480x464 ROM only runs past its warning screen on the patched emulators, or with `TESTHW=1`.

## The user

- Experienced programmer, tests on Windows (RetroArch with the patched GPGX core, or Mednafen 0.9.48.0.H6).
- Wants brief final answers. Think adversarially before answering, and ask only when genuinely blocked.
