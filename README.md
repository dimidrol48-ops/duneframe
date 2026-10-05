# Dune II: The Battle for Arrakis (Sega Mega Drive) - rebuildable disassembly

> This is a hobby project, free of charge, built from data available online and AI training data. If you believe your rights are violated please contact me via Issues of this repo and I will take action promptly.

## Goals

Play Dune 2 with modern creature comforts.
1. Mouse support
2. Multi-selection of units
3. ???
4. PROFIT

This is just a first version, a stub, a POC.

## What this contains

- Script to for a quick start (see next section)
- Tools to disassemble the supplied rom
- Tools to rebuild the rom byte-perfect from asm and c code
- Some decompiled c code (that intends to replace some asm code)

## Quick start

1. This will assume you are on Windows. This can (and kind of has to) also work on Linux, please inspect the .sh script.
2. Find the required ROMs and the patched emulator. For evaluation purposes you can try this online search query: "dune 2 full version Ti_ M3tro". If you find a 7z file, inside there will be a txt with a link to Mednafen_v0.9.43_(480x464) emulator. Put and extract the files in Downloads or current directory.
3. Run the below command in powershell. It will download an execute a powershell script from this repo.

```powershell
irm https://raw.githubusercontent.com/rsheptolut/dune2smd/main/tools/setup/setup-wsl.ps1 | iex
```

4. Wait for a while for everything to install (5-20 min). Follow the prompts, if any.
5. DUNE II starts (if roms and emulator was supplied)

## What the setup script does

1. Sets up the Mednafen emulator on Windows side if you supplied it.
2. Sets up a WSL2 Ubuntu distro named `dune2`
3. Clones this repo into it and starts setup.sh in your new Ubuntu machine. 
```
tools/setup/setup.sh --rom ROM [--wide-rom ROM] [--mednafen ZIP]
```
4. Installs the packages
5. Disassembles the ROM
6. Rebuilds the ROM from c and asm
7. Verifies the ROM without the patch matches the source rom exactly after reassembly

## Play

- **320x224 ROM:** any Genesis emulator. Put a Sega Mouse (RetroArch / Genesis Plus GX: *MD Mouse*) on port 2.
- **480x464 ROM:** only runs on the hack's patched emulators: Mednafen 0.9.48.0.H6 (`-md.screen_x 480 -md.screen256_x 480 -md.screen_y 464 -md.input.port2 megamouse`), or the patched RetroArch core.

Mednafen keys (Windows setup): W A S D pad, keypad 1 2 3 = A B C, Enter = Start, **Alt+E captures / releases the mouse**, Alt+Enter fullscreen, Esc quits.

Mouse controls:

- left click selects / orders; left drag box-selects;
- right click cancels; middle click is C;
- double click on a unit selects all on-screen units of that type; triple click selects the whole class.

## How to bulid this by hand without running the scripts

Please read the scripts referenced above with your eyeballs and repeat the steps manually via keyboard.

## More

- [`docs/TECHNICAL.md`](docs/TECHNICAL.md): layout, build switches, the C interface, test tools.
- [`docs/DEVNOTES.md`](DEVNOTES.md): history, plans, pitfalls, and the Windows-port outlook.
