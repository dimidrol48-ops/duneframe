# Dune II: The Battle for Arrakis (Genesis) - "Full Version R82c" rebuild
#
#   make            build/dune2.gen      byte-identical rebuild of the original
#   make check      verify it against the original (sha1)
#   make mod        build/mod/dune2.gen  C versions of decompiled functions
#                                        (NONMATCHING=1) + modifications (MODS=1)
#   make wide       build/wide/dune2.gen the 480x464 build (WIDE=1), for emulators
#                                        with the matching screen hack
#   make check-wide verify it against the original 480x464 ROM (sha1)
#   make mod WIDE=1 build/modw/dune2.gen  modded 480x464 build
#   make setup      generate src/ and assets/ from baserom.gen (and variants/wide.gen
#                   if present), then verify: needed once after a fresh clone
#   make clean

PREFIX  ?= m68k-linux-gnu-
AS      := $(PREFIX)as
CC      := $(PREFIX)gcc
LD      := $(PREFIX)ld
OBJCOPY := $(PREFIX)objcopy

ASFLAGS := -m68000 --register-prefix-optional -I src -I .
CFLAGS  := -m68000 -mstrict-align -fno-store-merging -fno-strict-aliasing -fno-delete-null-pointer-checks -O2 -fomit-frame-pointer -fcall-used-d2 -fno-ivopts -fno-pic -ffreestanding \
           -fno-builtin -fno-common -nostdlib -Wall -Isrc/c
BASEROM_SHA1 := 1c5ea483885774ec6649aeb9f5d5a587253557a9
WIDEROM_SHA1 := b0168348bcdc642f0f4f8d31433f6c4659a81911
WIDE ?= 0

ASM_SRCS   := $(wildcard src/*.s src/*.inc)
C_SRCS     := $(wildcard src/c/*.c)
ASSET_SRCS := $(shell find assets -type f 2>/dev/null)

all: build/dune2.gen

# ---- generated sources: src/*.s and assets/ are derived from the ROM and
# not committed; regenerate them from your own ROM
setup:
	python3 tools/disasm/generate.py baserom.gen traces/merged.npz src
	python3 tools/assets/extract.py
	$(MAKE) build/assets/.stamp
	@if [ -f variants/wide.gen ]; then python3 tools/disasm/variant.py baserom.gen traces/merged.npz variants/wide.gen WIDE src; \
	else echo "variants/wide.gen not found: 480x464 (WIDE) builds will not work"; fi
	$(MAKE) check
	@if [ -f variants/wide.gen ]; then $(MAKE) check-wide; fi

# ---- assets (PNG / palette / sound files -> binary blobs)
build/assets/.stamp: $(ASSET_SRCS) tools/assets/build.py tools/assets/gfx.py tools/assets/lcw.py
	@mkdir -p build/assets
	python3 tools/assets/build.py build/assets
	@touch $@

# ---- matching build (assembly only)
build/obj/main.o: $(ASM_SRCS) build/assets/.stamp
	@mkdir -p $(dir $@)
	$(AS) $(ASFLAGS) -o $@ src/main.s

build/dune2.elf: build/obj/main.o rom.ld
	$(LD) -T rom.ld -o $@ build/obj/main.o

build/dune2.gen: build/dune2.elf
	$(OBJCOPY) -O binary -j .text $< $@

check: build/dune2.gen
	@echo "$(BASEROM_SHA1)  build/dune2.gen" | sha1sum -c -

# ---- 480x464 build (assembly only)
build/wide/main.o: $(ASM_SRCS) build/assets/.stamp
	@mkdir -p $(dir $@)
	$(AS) $(ASFLAGS) --defsym WIDE=1 -o $@ src/main.s

build/wide/dune2.elf: build/wide/main.o rom.ld
	$(LD) -T rom.ld -o $@ build/wide/main.o

build/wide/dune2.gen: build/wide/dune2.elf
	$(OBJCOPY) -O binary -j .text $< $@

wide: build/wide/dune2.gen

check-wide: build/wide/dune2.gen
	@echo "$(WIDEROM_SHA1)  build/wide/dune2.gen" | sha1sum -c -

# ---- modded build: C replacements + MODS (build/mod, or build/modw for WIDE=1)
MD := build/mod$(if $(filter 1,$(WIDE)),w)
MOD_OBJS := $(MD)/main.o $(patsubst src/c/%.c,$(MD)/c/%.o,$(C_SRCS))

$(MD)/main.o: $(ASM_SRCS) build/assets/.stamp
	@mkdir -p $(dir $@)
	$(AS) $(ASFLAGS) --defsym NONMATCHING=1 --defsym MODS=1 --defsym WIDE=$(WIDE) -o $@ src/main.s

$(MD)/c/%.o: src/c/%.c src/c/dune2.h src/c/mods.h
	@mkdir -p $(dir $@)
	$(CC) $(CFLAGS) -DMODS=1 -DWIDE=$(WIDE) -c -o $@ $<

$(MD)/dune2.elf: $(MOD_OBJS) rom.ld
	$(LD) -T rom.ld -o $@ $(MOD_OBJS)

$(MD)/dune2.gen: $(MD)/dune2.elf
	$(OBJCOPY) -O binary -j .text $< $@
	python3 tools/fixheader.py $@

mod: $(MD)/dune2.gen

# ---- C-only build (NONMATCHING=1, no MODS): same ROM layout as the
# original except the C code at the end; used by tools/ctest/snaptest.py
NM_OBJS := build/nm/main.o $(patsubst src/c/%.c,build/nm/c/%.o,$(C_SRCS))

build/nm/main.o: $(ASM_SRCS) build/assets/.stamp
	@mkdir -p $(dir $@)
	$(AS) $(ASFLAGS) --defsym NONMATCHING=1 --defsym MODS=0 -o $@ src/main.s

build/nm/c/%.o: src/c/%.c src/c/dune2.h src/c/mods.h
	@mkdir -p $(dir $@)
	$(CC) $(CFLAGS) -DMODS=0 -DWIDE=0 -c -o $@ $<

build/nm/dune2.elf: $(NM_OBJS) rom.ld
	$(LD) -T rom.ld -o $@ $(NM_OBJS)

build/nm/dune2.gen: build/nm/dune2.elf
	$(OBJCOPY) -O binary -j .text $< $@
	python3 tools/fixheader.py $@

nonmatching: build/nm/dune2.gen

clean:
	rm -rf build/obj build/mod build/modw build/nm build/wide build/assets build/dune2.elf build/dune2.gen

.PHONY: setup all check wide check-wide mod nonmatching clean
