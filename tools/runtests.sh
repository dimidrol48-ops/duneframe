#!/bin/bash
# Run the test suite.  See HANDOFF.md, "Running all tests".
#
# usage: tools/runtests.sh [TIER|STEP ...]  (default: quick)
#   quick   builds, layout, register contracts, equiv, grouptest      (~1.5 min)
#   full    quick + snaptest, the three lockstep sweeps, crash sweeps (~25 min on 4 cores)
#   shift   relocation test, needed after generator / config changes  (~4 min)
#   med     480x464 runs in the patched Mednafen under wine: screenshots to
#           build/tests/med/ for a person to look at                  (~5 min)
#   all     full + shift + med
# or single steps by name, e.g. tools/runtests.sh sweep_mod
#
# Each step logs to build/tests/<step>.log and prints PASS / FAIL with its
# last line.  Exit status 1 if any step failed.
cd "$(dirname "$0")/.." || exit 1
T=build/tests
mkdir -p $T
FAILED=()

step() {   # step NAME CMD... : run CMD, log it, report
    local name=$1; shift
    local t0=$SECONDS
    printf '%-14s ' "$name"
    if "$@" > $T/$name.log 2>&1; then r=PASS; else r=FAIL; FAILED+=("$name"); fi
    printf '%s %5ds  %s\n' $r $((SECONDS - t0)) "$(grep -v '^\s*$' $T/$name.log | tail -n 1 | cut -c1-90)"
}

build() {
    make check check-wide && make nonmatching mod && make mod WIDE=1
}

layout() {
    python3 tools/check_layout.py build/dune2.elf build/mod/dune2.elf &&
    python3 tools/check_layout.py build/wide/dune2.elf build/modw/dune2.elf
}

variants() {   # test builds of the 480x464 ROM that run on the stock test core
    python3 tools/buildvariant.py $T/wide_orig --wide --no-c --testhw &&
    python3 tools/buildvariant.py $T/wide_c --wide --testhw &&
    python3 tools/buildvariant.py $T/wide_mod --wide --mods --testhw
}

snaptest() {
    if [ -z "$(ls build/states/pool 2>/dev/null)" ]; then python3 tools/ctest/states.py || return 1; fi
    python3 tools/ctest/snaptest.py
}

sweep_mod() {   # with pad input the mods only differ where a double tap of A fires
    python3 tools/lockstep_sweep.py baserom.gen build/mod/dune2.gen build/mod/dune2.elf \
        -- --elf-a build/nm/dune2.elf --no-y
    local bad
    bad=$(grep -E '^[a-z0-9_]+ +RAM difference' $T/sweep_mod.log | awk '{print $1}' | sort | tr '\n' ' ')
    echo "differing: ${bad:-none} (expected: pw_sandimpact pw_sardaukars, double taps)"
    [ "$bad" = "pw_sandimpact pw_sardaukars " ]
}

crash() {
    python3 tools/crashsweep.py build/mod/dune2.gen &&
    python3 tools/crashsweep.py $T/wide_mod/rom.gen
}

med() {   # needs wine (+ wine32:i386), xvfb, xdotool, imagemagick, tools/med/mednafen/
    local O=$T/med boot
    rm -rf $O; mkdir -p $O
    # title -> start -> pick a house with C presses -> mission 1 (wall-clock timed)
    boot='w12000;kReturn:80;w2000;kReturn:80;w2000;kReturn:80;w2000;kReturn:80;w2000'
    for i in $(seq 15); do boot="$boot;kKP_3:80;w3000"; done
    boot="$boot;kKP_1:80;w14000"
    timeout 600 python3 tools/med/medrun.py build/modw/dune2.gen $O/mouse --wide --mouse \
        "$boot;s1;m-60,0;w300;m-60,30;w600;s2;m120,-40;w300;m120,-40;w300;m100,100;w800;s3;w30000;s4" || return 1
    # AUTOPLAY: the original 480x464 ROM and the mod play the same input script
    mkdir -p $T/ap && python3 tools/autoplay.py mission1 $T/ap/autoplay.bin &&
    python3 tools/buildvariant.py $T/ap_orig --wide --no-c --autoplay $T/ap &&
    python3 tools/buildvariant.py $T/ap_mod --wide --mods --autoplay $T/ap || return 1
    for v in orig mod; do
        timeout 600 python3 tools/med/medrun.py $T/ap_$v/rom.gen $O/ap_$v --wide \
            'w20000;s20;w20000;s40;w20000;s60;w20000;s80' || return 1
    done
    for d in $O/mouse $O/ap_orig $O/ap_mod; do
        convert $(ls $d/*.png | sort -V) -crop 480x464+0+29 +repage +append $d.png || return 1
    done
    ls $O/*.png
}

sweep_base() {
    python3 tools/lockstep_sweep.py baserom.gen build/nm/dune2.gen build/nm/dune2.elf
}

sweep_wide() {
    python3 tools/lockstep_sweep.py $T/wide_orig/rom.gen $T/wide_c/rom.gen $T/wide_c/dune2.elf
}

QUICK="build layout regouts equiv variants grouptest grouptest_w"
FULL="$QUICK snaptest sweep_base sweep_wide sweep_mod crash"
ALL="$FULL shift med"
declare -A CMD=(
    [build]=build [layout]=layout [regouts]="python3 tools/check_regouts.py"
    [equiv]="python3 tools/ctest/equiv.py" [variants]=variants
    [grouptest]="python3 tools/grouptest.py"
    [grouptest_w]="python3 tools/grouptest.py $T/wide_mod/rom.gen $T/wide_mod/dune2.elf"
    [snaptest]=snaptest [sweep_base]=sweep_base [sweep_wide]=sweep_wide [sweep_mod]=sweep_mod
    [crash]=crash [shift]="python3 tools/shiftsuite.py" [med]=med
)

main() {   # inside a function, so editing this file while it runs is harmless
    local steps="" a
    [ $# -eq 0 ] && set -- quick
    for a in "$@"; do
        case $a in
        quick) steps="$steps $QUICK" ;;
        full) steps="$steps $FULL" ;;
        all) steps="$steps $ALL" ;;
        *) [ -n "${CMD[$a]}" ] || { echo "unknown tier or step: $a (steps: $ALL)"; exit 2; }
           steps="$steps $a" ;;
        esac
    done
    for a in $steps; do
        step $a ${CMD[$a]}
    done
    if [ ${#FAILED[@]} -gt 0 ]; then echo "FAILED: ${FAILED[*]} (logs in $T/)"; exit 1; fi
    echo "all passed"
}

main "$@"
exit
