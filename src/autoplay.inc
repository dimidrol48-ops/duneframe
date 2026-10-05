| Autoplay (AUTOPLAY=1 test builds only): Input_ReadPad's hardware read is
| replaced by an input script, so a test plays back the same way on any
| emulator, whatever its speed.  autoplay.bin is made by tools/autoplay.py:
| 8-byte records
|	.word frames
|	.byte held, ext, mouse_dx, mouse_dy, mouse_buttons, flags
| held: Up Down Left Right B C A Start = bits 0-7; ext: Z Y X Mode = bits 0-3;
| mouse (MODS builds): per-frame motion and buttons (1 L, 2 R, 4 M, 8 Start).
| The script advances with the VBlank counter, not with the number of pad
| reads, and starts at power-on (the game does not read the pad during the
| first logos).  frames = 0 ends the script.
|
| The game restarts itself (EntryPoint, RAM cleared, VBlank counter back to
| 0) when a mission begins, so the position in the script (record index + 1)
| is also kept at FFFFFA, above the initial stack pointer, which the game's
| RAM clear does not reach (a cold boot zeroes it).  A record with flags
| bit 0 marks such a restart: the script waits there, and after the restart
| carries on behind it.
	.set	ap_last, 0xFFFFC360	| g_vblankCount at the previous call
	.set	ap_ptr, 0xFFFFC362	| current record
	.set	ap_left, 0xFFFFC366	| frames left in it
	.set	ap_magic, 0xFFFFC368
	.set	ap_save, 0xFFFFFFFA	| record index + 1, survives the game's restarts
Autoplay_ReadPad:
	move.l	d2,-(sp)
	cmpi.w	#0xA97A,(ap_magic).w
	beq.s	3f
	| (re)start: from the beginning, or behind the next restart mark
	move.w	#0xA97A,(ap_magic).w
	lea	(Autoplay_Script).l,a0
	moveq	#0,d0
	move.w	(ap_save).w,d0
	beq.s	2f
	subq.w	#1,d0
	lsl.l	#3,d0
	lea	(0,a0,d0.l),a1
	cmpa.l	#Autoplay_End,a1
	bcc.s	2f
1:	btst.b	#0,(7,a1)		| find the mark
	bne.s	11f
	tst.w	(a1)
	beq.s	2f
	addq.l	#8,a1
	bra.s	1b
11:	lea	(8,a1),a0
2:	move.l	a0,(ap_ptr).w
	move.w	(a0),(ap_left).w
	clr.w	(ap_last).w
3:	movea.l	(ap_ptr).w,a0
	move.w	(g_vblankCount).w,d1
	move.w	d1,d0
	cmp.w	(ap_last).w,d0
	bcc.s	31f
	clr.w	(ap_last).w		| the counter went back: the game restarted
	movea.l	a0,a1			| (without clearing RAM): go behind the mark
32:	btst.b	#0,(7,a1)
	bne.s	33f
	tst.w	(a1)
	beq.s	31f			| no mark left: carry on
	addq.l	#8,a1
	bra.s	32b
33:	lea	(8,a1),a0
	move.w	(a0),(ap_left).w
31:	sub.w	(ap_last).w,d1		| frames since the last call
	move.w	d0,(ap_last).w
4:	tst.w	(a0)
	beq.s	6f			| end of the script
	btst.b	#0,(7,a0)
	bne.s	6f			| restart mark: wait for the restart
	cmp.w	(ap_left).w,d1
	bcs.s	5f
	sub.w	(ap_left).w,d1
	addq.l	#8,a0
	move.w	(a0),(ap_left).w
	bra.s	4b
5:	sub.w	d1,(ap_left).w
6:	move.l	a0,(ap_ptr).w
	move.l	a0,d0
	subi.l	#Autoplay_Script,d0
	lsr.l	#3,d0
	addq.w	#1,d0
	move.w	d0,(ap_save).w
	moveq	#0,d0
	moveq	#0,d2
	tst.w	(a0)
	beq.s	7f
	btst.b	#0,(7,a0)
	bne.s	7f
	move.b	(2,a0),d0		| held
	move.b	(3,a0),d2		| ext
7:	lea	(g_padExtHeld).w,a1	| 6-button bookkeeping, as in Input_ReadPad
	move.b	(a1),d1
	eor.b	d2,d1
	move.b	d2,(a1)
	and.b	d2,d1
	move.b	d1,-(a1)
	move.l	(sp)+,d2
	jmp	(loc_001238).l
	.balign	2
Autoplay_Script:
	.incbin	"autoplay.bin"
	.word	0, 0, 0, 0
Autoplay_End:
	.balign	2
