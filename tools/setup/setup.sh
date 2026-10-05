#!/bin/bash
# Set up everything needed to build and test this repo on Ubuntu 24.04
# (a fresh WSL2 distro made by setup-wsl.ps1, or any Ubuntu/Debian machine).
# Safe to run again: finished steps are skipped.
#
# usage: tools/setup/setup.sh [--rom FILE] [--wide-rom FILE] [--mednafen ZIP|DIR] [--no-wine] [--verbose]
#
#   --rom       the R82c ROM, copied to baserom.gen (if that isn't there yet)
#   --wide-rom  the R82c 480x464 ROM, copied to variants/wide.gen (optional)
#   --mednafen  the hack's "Mednafen 0.9.48.0.H6.zip" (or its unpacked folder),
#               unpacked to tools/med/mednafen (optional; for tools/med/medrun.py)
#   --no-wine   skip wine/Xvfb (only needed to drive Mednafen from Linux)
#   --verbose   show every command's output instead of one status line per step
#
# The full output always goes to build/setup.log.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
cd "$ROOT"

BASEROM_SHA1=1c5ea483885774ec6649aeb9f5d5a587253557a9
WIDEROM_SHA1=b0168348bcdc642f0f4f8d31433f6c4659a81911
ROM= WIDE_ROM= MEDNAFEN= WINE=1 VERBOSE=0
while [ $# -gt 0 ]; do
    case "$1" in
        --rom) ROM=$2; shift 2 ;;
        --wide-rom) WIDE_ROM=$2; shift 2 ;;
        --mednafen) MEDNAFEN=$2; shift 2 ;;
        --no-wine) WINE=0; shift ;;
        --verbose) VERBOSE=1; shift ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done

# ---- progress display
# Each step runs with its output in the log; the terminal shows one line per
# step (spinner, elapsed time) and, under it, the step's latest log line.
mkdir -p build
LOG=$ROOT/build/setup.log
echo "setup.sh started $(date)" > "$LOG"
[ -t 1 ] && TTY=1 || TTY=0
if [ "$TTY" = 1 ]; then
    B=$'\033[1m' DIM=$'\033[2m' RED=$'\033[31m' GRN=$'\033[32m' YEL=$'\033[33m' CYN=$'\033[36m' R=$'\033[0m'
else
    B= DIM= RED= GRN= YEL= CYN= R=
fi
N=0 TOTAL=0 PID= T0=$SECONDS

mmss() { printf '%d:%02d' $(($1 / 60)) $(($1 % 60)); }
width() {   # room for the detail line
    local c
    c=$(stty size < /dev/tty 2>/dev/null | cut -d' ' -f2)
    c=$((${c:-80} - 10))
    [ $c -lt 20 ] && c=20
    echo $c
}
last_line() {   # the log's latest non-empty line, plain text, cut to fit
    tail -n 20 "$LOG" | tr '\r\t' '\n ' | sed 's/\x1b\[[0-9;?]*[a-zA-Z]//g; /^[[:space:]]*$/d; /^==== /d' |
        tail -n 1 | cut -c 1-$(width)
}
step_log() {    # the log since the current step's ==== marker
    awk '/^==== /{buf=""; next} {buf=buf $0 "\n"} END{printf "%s", buf}' "$LOG"
}
cleanup() {
    [ -n "$PID" ] && kill "$PID" 2>/dev/null
    [ "$TTY" = 1 ] && printf '\033[?25h\033[?7h'   # cursor and line wrap back on
    return 0
}
trap cleanup EXIT
trap 'cleanup; printf "\n%sInterrupted.%s Log: %s\n" "$RED" "$R" "$LOG"; exit 130' INT TERM

note() { printf '        %s%s%s\n' "$DIM" "$*" "$R"; }
fail() {    # message: the step failed
    printf '\n%s%s%s\n\n' "$RED$B" "$*" "$R"
    echo "Last lines of its output:"
    step_log | tail -n 25 | sed 's/^/  /'
    printf '\nFull log: %s\n' "$LOG"
    exit 1
}
skip() {    # title reason
    N=$((N + 1))
    printf '  %s[%d/%d]%s %s  %s%s%s\n' "$CYN" $N $TOTAL "$R" "$1" "$DIM" "$2" "$R"
}
step() {    # title command...: run one step
    local title=$1 t0=$SECONDS rc=0 i=0 spin='|/-\'
    shift
    N=$((N + 1))
    printf '\n==== [%d/%d] %s (%s)\n' $N $TOTAL "$title" "$(date +%T)" >> "$LOG"
    local head
    head=$(printf '%s[%d/%d]%s %s' "$CYN" $N $TOTAL "$R" "$title")
    # always a background job: run as "cmd || rc=$?", a function would have
    # set -e switched off and carry on after a failed command
    if [ "$VERBOSE" = 1 ]; then
        printf '\n  %s\n' "$head"
        { "$@" 2>&1 < /dev/null | tee -a "$LOG"; } &
        PID=$!
        wait "$PID" || rc=$?
        PID=
        printf '  %s  ' "$head"
    elif [ "$TTY" = 0 ]; then
        printf '  %s ... ' "$head"
        "$@" >> "$LOG" 2>&1 < /dev/null &
        PID=$!
        wait "$PID" || rc=$?
        PID=
    else
        "$@" >> "$LOG" 2>&1 < /dev/null &
        PID=$!
        printf '\033[?25l\033[?7l'   # no cursor, no line wrap (a wrapped line breaks the redraw)
        while kill -0 "$PID" 2>/dev/null; do
            # step line, then the latest log line under it; back up to the step line
            printf '\r\033[K  %s  %s%s %s%s\n\r\033[K        %s%s%s\033[1A\r' \
                "$head" "$YEL" "${spin:i++%4:1}" "$(mmss $((SECONDS - t0)))" "$R" "$DIM" "$(last_line)" "$R"
            sleep 0.2
        done
        wait "$PID" || rc=$?
        PID=
        printf '\r\033[K\n\033[K\033[1A\r\033[?7h  %s  ' "$head"
    fi
    if [ "$rc" = 0 ]; then
        printf '%sdone%s %s%s%s\n' "$GRN" "$R" "$DIM" "$(mmss $((SECONDS - t0)))" "$R"
    else
        printf '%sFAILED%s\n' "$RED" "$R"
        fail "Step $N ($title) failed."
    fi
}
SUDO="sudo -n"
need_sudo() {   # ask for the password (if any) up front, not hidden in a step
    if [ "$(id -u)" = 0 ]; then SUDO=; return; fi   # root, e.g. in a container
    sudo -n true 2>/dev/null && return
    echo "  Administrator rights are needed to install packages:"
    sudo -v || fail "sudo failed."
}

# ---- the steps
check_sha1() { [ "$(sha1sum "$1" | cut -d' ' -f1)" = "$2" ]; }
put_rom() {   # src dst sha1 label
    if [ -f "$2" ]; then
        check_sha1 "$2" "$3" || { echo "$2 has the wrong sha1 (want $3)"; return 1; }
        echo "$2 is there"
    elif [ -n "$1" ]; then
        [ -f "$1" ] || { echo "$4 ROM not found: $1"; return 1; }
        check_sha1 "$1" "$3" || { echo "$1 is not the $4 ROM (sha1 should be $3)"; return 1; }
        cp "$1" "$2"
        echo "$4 ROM -> $2"
    fi
}
roms() {
    put_rom "$ROM" baserom.gen $BASEROM_SHA1 R82c
    put_rom "$WIDE_ROM" variants/wide.gen $WIDEROM_SHA1 "R82c 480x464"
    [ -f baserom.gen ] || { echo "baserom.gen is missing: pass --rom ROM (see README)"; return 1; }
}
packages() {
    local pkgs="make gcc git unzip p7zip-full python3 python3-numpy python3-pil python3-unicorn
                binutils-m68k-linux-gnu gcc-m68k-linux-gnu"
    [ "$WINE" = 1 ] && pkgs="$pkgs xvfb xdotool imagemagick"
    $SUDO apt-get update -q
    $SUDO apt-get install -y -q $pkgs
}
wine_() {
    dpkg --print-foreign-architectures | grep -qx i386 || {
        $SUDO dpkg --add-architecture i386
        $SUDO apt-get update -q
    }
    $SUDO apt-get install -y -q --install-recommends wine wine32:i386
    # create the wine prefix now, without the Mono/Gecko install dialogs
    # (they would wait forever on medrun.py's invisible display)
    [ -d ~/.wine ] || xvfb-run -a env WINEDEBUG=-all WINEDLLOVERRIDES="mscoree,mshtml=" wineboot -i
}
mednafen() {    # the Windows build, run under wine by tools/med/medrun.py
    local tmp exe
    tmp=$(mktemp -d)
    if [ -d "$MEDNAFEN" ]; then cp -r "$MEDNAFEN"/. "$tmp"/
    else unzip -q "$MEDNAFEN" -d "$tmp"; fi
    exe=$(find "$tmp" -iname mednafen.exe | head -1)
    [ -n "$exe" ] || { echo "no mednafen.exe in $MEDNAFEN"; return 1; }
    mkdir -p tools/med/mednafen
    cp -r "$(dirname "$exe")"/. tools/med/mednafen/
    rm -rf "$tmp"
}
mods() {
    make mod
    if [ -f variants/wide.gen ]; then make mod WIDE=1; fi
}

if ! command -v apt-get > /dev/null; then
    echo "This script installs its packages with apt (Ubuntu/Debian). On another distro,"
    echo "run it in an Ubuntu 24.04 container, for example with distrobox:"
    echo "  distrobox create -i ubuntu:24.04 dune2"
    echo "  distrobox enter dune2 -- tools/setup/setup.sh --rom ROM [...]"
    exit 1
fi
export DEBIAN_FRONTEND=noninteractive
DO_MED=0
[ -n "$MEDNAFEN" ] && [ ! -f tools/med/mednafen/mednafen.exe ] && DO_MED=1
TOTAL=$((5 + WINE + DO_MED))

printf '\n%sSetting up %s%s   %s(log: %s)%s\n\n' "$B" "$(basename "$ROOT")" "$R" "$DIM" "$LOG" "$R"
need_sudo
step "Checking the ROMs" roms
[ -f variants/wide.gen ] || note "No 480x464 ROM: its builds will be skipped."
step "Installing build tools" packages
if [ "$WINE" = 1 ]; then step "Installing wine (to run Mednafen)" wine_; fi
if [ "$DO_MED" = 1 ]; then step "Unpacking Mednafen" mednafen
elif [ -z "$MEDNAFEN" ] && [ ! -f tools/med/mednafen/mednafen.exe ]; then
    note "No Mednafen: tools/med/medrun.py won't work until it's in tools/med/mednafen."
fi
step "Generating sources from the ROMs, verifying exact rebuilds" make setup
if [ -f tools/emu/build/genesis_plus_gx_libretro.so ]; then
    skip "Building the test emulator core" "already built"
else
    step "Building the test emulator core" tools/emu/build_core.sh
fi
step "Building the mod ROMs" mods

printf '\n%sAll done%s in %s.\n' "$GRN$B" "$R" "$(mmss $((SECONDS - T0)))"
echo "Mod ROMs:"
ls -1 build/mod/dune2.gen build/modw/dune2.gen 2>/dev/null | sed 's/^/  /'
