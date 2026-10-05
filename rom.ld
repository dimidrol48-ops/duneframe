/* Dune II Genesis rebuild - linker script.
 * main.o (first on the command line) holds the whole ROM image in ROM order;
 * C objects (src/c) follow it at the end of the ROM.  RAM belongs to the
 * original game: C code gets no initialised data, and its zero-initialised
 * state (.bss) goes to a block the game never uses (FFC356-FFC574, found by
 * tools/ramusage.py plus a scan of static references).  The game leaves it
 * zero, so no start-up code is needed. */
OUTPUT_FORMAT("elf32-m68k")
OUTPUT_ARCH(m68k)
SECTIONS
{
	.text 0x000000 :
	{
		*(.text)
		. = ALIGN(2);
		__c_code = .;
		*(.text.*)
		*(.rodata .rodata.*)
		. = ALIGN(2);
		__rom_end = .;
	}
	.data : { *(.data .data.*) }
	ASSERT(SIZEOF(.data) == 0, "C code must not use initialised writable data")
	.bss 0xFFC380 (NOLOAD) : { *(.bss .bss.* COMMON) }
	ASSERT(SIZEOF(.bss) <= 0x1C0, "C state does not fit the free RAM block FFC380-FFC540")
	/DISCARD/ : { *(.comment) *(.note*) *(.eh_frame) }
}
