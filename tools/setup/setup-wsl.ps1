<#
.SYNOPSIS
  Make a WSL2 Ubuntu distro that builds and tests this repo, and Windows
  launchers that play the result in Mednafen.

.DESCRIPTION
  In PowerShell, without cloning anything:
    irm https://raw.githubusercontent.com/rsheptolut/dune2smd/main/tools/setup/setup-wsl.ps1 | iex
  With options:
    & ([scriptblock]::Create((irm <same url>))) -NoLaunch
  From a clone:
    powershell -ExecutionPolicy Bypass -File tools\setup\setup-wsl.ps1 [options]

  Steps:
  1. Create the distro (WSL2, Ubuntu 24.04) and a user named after yours,
     with passwordless sudo.
  2. Find the ROMs by checksum in the current folder, Downloads, Desktop and
     Documents (and the clone, if run from one); if the base ROM isn't
     found, a file dialog asks for it. The 480x464 ROM and the hack's
     "Mednafen 0.9.48.0.H6.zip" are optional.
  3. git clone the repo to ~/dune2 in the distro and run
     tools/setup/setup.sh there (packages, source generation, builds).
  4. Put a copy of Mednafen in %LOCALAPPDATA%\Programs\<Name>, with its
     own config (started from tools/setup/mednafen.cfg; your other
     Mednafen setups are untouched), and Play*.cmd launchers that run the
     latest build straight from the distro. Then offer to start the game.

  Safe to run again: the distro, the clone and Mednafen's config are kept.

.PARAMETER Repo      What to clone (default: this clone's origin, else rsheptolut/dune2smd on GitHub).
.PARAMETER Name      Distro name (default dune2).
.PARAMETER Location  Where the distro's disk goes (default %USERPROFILE%\WSL\<Name>).
.PARAMETER Rom       The R82c ROM.
.PARAMETER WideRom   The R82c 480x464 ROM.
.PARAMETER Mednafen  "Mednafen 0.9.48.0.H6.zip" or its unpacked folder.
.PARAMETER NoWine    Don't install wine/Xvfb in the distro (only needed by tools/med/medrun.py).
.PARAMETER NoLaunch  Don't offer to start the game at the end.
#>

# Everything runs inside this block, so under "irm | iex" nothing leaks into
# the caller's session, and errors return instead of closing the window. Its
# output isn't captured: wsl.exe must write straight to the console (setup.sh
# shows its progress display only on a terminal).
& {
param(
    [string]$Repo = '',
    [string]$Name = 'dune2',
    [string]$Location = '',
    [string]$Rom = '',
    [string]$WideRom = '',
    [string]$Mednafen = '',
    [string]$Distro = 'Ubuntu-24.04',
    [switch]$NoWine,
    [switch]$NoLaunch
)
$ErrorActionPreference = 'Stop'
$env:WSL_UTF8 = '1'     # plain UTF-8 output from wsl.exe instead of UTF-16

$DefaultRepo = 'https://github.com/rsheptolut/dune2smd.git'
$Dir = 'dune2'          # the clone: ~/dune2 in the distro
$BaseSha1 = '1C5EA483885774EC6649AEB9F5D5A587253557A9'
$WideSha1 = 'B0168348BCDC642F0F4F8D31433F6C4659A81911'
$RomSize = 2466626      # both ROMs; files of any other size aren't hashed
if (-not $Location) { $Location = Join-Path $env:USERPROFILE "WSL\$Name" }

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Fail($msg) { throw $msg }
function Wsl {
    & wsl.exe @args
    if ($LASTEXITCODE -ne 0) { Fail "wsl.exe $($args -join ' ') failed ($LASTEXITCODE)" }
}

try {

# ---- what to clone: run from a clone, use its origin (a fork stays a fork)
$Checkout = ''
if ($PSScriptRoot) {
    $r = Join-Path $PSScriptRoot '..\..'
    if (Test-Path (Join-Path $r '.git\config')) { $Checkout = (Resolve-Path $r).Path }
}
if (-not $Repo -and $Checkout) {
    $cfg = Get-Content (Join-Path $Checkout '.git\config') -Raw
    if ($cfg -match '(?ms)^\[remote "origin"\][^\[]*?^\s*url\s*=\s*(\S+)') { $Repo = $Matches[1] }
}
if (-not $Repo) { $Repo = $DefaultRepo }
# a fresh distro has no SSH keys: clone GitHub over https
$Repo = $Repo -replace '^git@github\.com:', 'https://github.com/'

# ---- WSL itself
Step 'Checking WSL'
& wsl.exe --version *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host 'WSL is missing or too old. Installing it (needs administrator rights)...'
    Start-Process wsl.exe -ArgumentList '--install', '--no-distribution' -Verb RunAs -Wait
    Write-Host 'Restart Windows, then run this again.' -ForegroundColor Yellow
    return
}

# ---- ROMs and Mednafen
Step 'Looking for the ROMs'
$SearchDirs = @((Get-Location).Path, "$env:USERPROFILE\Downloads", "$env:USERPROFILE\Desktop", "$env:USERPROFILE\Documents")
if ($Checkout) { $SearchDirs = @($Checkout, (Join-Path $Checkout 'variants'), (Split-Path $Checkout)) + $SearchDirs }
$SearchDirs = $SearchDirs | Where-Object { Test-Path $_ } | Select-Object -Unique
$cache = @{}
function Find-Rom($sha1) {
    if (-not $cache.ContainsKey('roms')) {
        $cache.roms = @($SearchDirs | ForEach-Object {
            Get-ChildItem -Path $_ -Recurse -Depth 3 -File -Include *.gen, *.bin, *.md, *.smd -ErrorAction SilentlyContinue
        } | Where-Object { $_.Length -eq $RomSize } | Sort-Object FullName -Unique)
    }
    foreach ($f in $cache.roms) {
        if ((Get-FileHash -Algorithm SHA1 -LiteralPath $f.FullName).Hash -eq $sha1) { return $f.FullName }
    }
    return ''
}
function Check-Rom($path, $sha1, $label) {
    if (-not (Test-Path -LiteralPath $path)) { Fail "$label ROM not found: $path" }
    if ((Get-FileHash -Algorithm SHA1 -LiteralPath $path).Hash -ne $sha1) {
        Fail "$path is not the $label ROM (sha1 should be $($sha1.ToLower()))"
    }
}

if ($Rom) { Check-Rom $Rom $BaseSha1 'R82c' } else { $Rom = Find-Rom $BaseSha1 }
if (-not $Rom) {
    Add-Type -AssemblyName System.Windows.Forms
    $dlg = New-Object System.Windows.Forms.OpenFileDialog
    $dlg.Title = 'Select DuneII_-_The_Battle_For_Arrakis_Full_Version_(R82c).gen'
    $dlg.Filter = 'Mega Drive ROM (*.gen;*.bin;*.md;*.smd)|*.gen;*.bin;*.md;*.smd|All files (*.*)|*.*'
    if ($dlg.ShowDialog() -ne 'OK') { Fail 'The R82c ROM is needed (see README).' }
    $Rom = $dlg.FileName
    Check-Rom $Rom $BaseSha1 'R82c'
}
Write-Host "R82c ROM:         $Rom"

if ($WideRom) { Check-Rom $WideRom $WideSha1 'R82c 480x464' } else { $WideRom = Find-Rom $WideSha1 }
if ($WideRom) { Write-Host "R82c 480x464 ROM: $WideRom" }
else { Write-Host 'R82c 480x464 ROM: not found (optional; the 480x464 builds will be skipped)' }

if (-not $Mednafen) {
    $m = $SearchDirs | ForEach-Object {
        Get-ChildItem -Path $_ -Recurse -Depth 2 -Filter 'Mednafen*0.9.48*H6*' -ErrorAction SilentlyContinue
    } | Where-Object {
        ($_.PSIsContainer -and (Test-Path (Join-Path $_.FullName 'mednafen.exe'))) -or $_.Extension -eq '.zip'
    } | Select-Object -First 1
    if ($m) { $Mednafen = $m.FullName }
}
if ($Mednafen) { Write-Host "Mednafen:         $Mednafen" }
else { Write-Host 'Mednafen:         not found (optional; to play the 480x464 build and for tools/med/medrun.py)' }

# ---- the distro
$existing = (& wsl.exe --list --quiet) -split "`r?`n" | ForEach-Object { $_.Trim([char]0, ' ') }
if ($existing -contains $Name) {
    Step "Distro '$Name' already exists, reusing it"
} else {
    Step "Installing $Distro as '$Name' in $Location"
    Wsl --install $Distro --name $Name --location $Location --no-launch
}

# Scripts run in the distro from temp files: quoting multi-line commands
# through wsl.exe's command line is fragile.
function Q($s) { "'" + ($s -replace "'", "'\''") + "'" }
function LinuxPath($p) { (& wsl.exe -d $Name -u root -e wslpath -a $p).Trim() }
function Run-InDistro($user, $script) {
    $tmp = Join-Path $env:TEMP "$Name-wsl-$PID.sh"
    [IO.File]::WriteAllText($tmp, ($script -replace "`r", ''), (New-Object Text.UTF8Encoding $false))
    try { Wsl -d $Name -u $user -e bash (LinuxPath $tmp) }
    finally { Remove-Item $tmp -ErrorAction SilentlyContinue }
}

# a user named after the Windows one, with passwordless sudo, as the default
$User = ($env:USERNAME.ToLower() -replace '[^a-z0-9_-]', '')
if ($User -notmatch '^[a-z_]') { $User = 'dune' }
Step "Setting up user '$User'"
Run-InDistro root @"
set -e
# (Ubuntu's first-launch setup sees this user and doesn't ask for one)
id -u $User >/dev/null 2>&1 || useradd -m -s /bin/bash -G adm,cdrom,sudo,dip,plugdev $User
echo '$User ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/90-$User
chmod 440 /etc/sudoers.d/90-$User
grep -q '^default=' /etc/wsl.conf 2>/dev/null || printf '\n[user]\ndefault=$User\n' >> /etc/wsl.conf
command -v git >/dev/null || { apt-get update -q && apt-get install -y -q git; } >/dev/null
"@
Wsl --terminate $Name   # so /etc/wsl.conf takes effect

# ---- clone and run setup.sh
$args_ = @('--rom', (LinuxPath $Rom))
if ($WideRom) { $args_ += @('--wide-rom', (LinuxPath $WideRom)) }
if ($Mednafen) { $args_ += @('--mednafen', (LinuxPath $Mednafen)) }
if ($NoWine) { $args_ += '--no-wine' }

Step "Cloning $Repo to ~/$Dir in '$Name' and running tools/setup/setup.sh"
Run-InDistro $User @"
set -e
cd ~
if [ -d $(Q $Dir) ]; then echo "~/$Dir is already there, using it as it is"
else git clone -q $(Q $Repo) $(Q $Dir); fi
cd $(Q $Dir)
exec bash tools/setup/setup.sh $(($args_ | ForEach-Object { Q $_ }) -join ' ')
"@

# ---- Windows side: Mednafen and launchers
$win = "\\wsl$\$Name\home\$User\$Dir"
$play = Join-Path $env:LOCALAPPDATA "Programs\$Name"
$launch = ''
if (Test-Path "$win\tools\med\mednafen\mednafen.exe") {
    Step "Setting up Mednafen and launchers in $play"
    $med = Join-Path $play 'mednafen'
    New-Item -ItemType Directory -Force $med | Out-Null
    Copy-Item "$win\tools\med\mednafen\*.exe", "$win\tools\med\mednafen\*.dll" $med -Force
    if (-not (Test-Path "$med\mednafen-09x.cfg")) { Copy-Item "$win\tools\setup\mednafen.cfg" "$med\mednafen-09x.cfg" }

    # the largest whole window scale that fits the screen
    Add-Type -AssemblyName System.Windows.Forms
    $h = [Windows.Forms.Screen]::PrimaryScreen.WorkingArea.Height - 60
    function Launcher($file, $rom, $w, $w256, $hh) {
        $scale = [Math]::Max(1, [Math]::Floor($h / $hh))
        $cmd = "@echo off`r`n" +
               "rem Made by setup-wsl.ps1: plays the latest build in the '$Name' WSL distro.`r`n" +
               "set MEDNAFEN_HOME=%~dp0mednafen`r`n" +
               "start `"`" `"%~dp0mednafen\mednafen.exe`" -md.screen_x $w -md.screen256_x $w256 -md.screen_y $hh " +
               "-md.xscale $scale -md.yscale $scale `"$rom`"`r`n"
        [IO.File]::WriteAllText((Join-Path $play $file), $cmd)
        Write-Host "  $file"
        return (Join-Path $play $file)
    }
    if (Test-Path "$win\build\mod\dune2.gen") {
        $launch = Launcher 'Play Dune II.cmd' "$win\build\mod\dune2.gen" 320 256 240
    }
    if (Test-Path "$win\build\modw\dune2.gen") {
        $launch = Launcher 'Play Dune II 480x464.cmd' "$win\build\modw\dune2.gen" 480 480 464
    }
}

Step 'All set'
Write-Host "Shell in the distro:  wsl -d $Name   (then: cd ~/$Dir)"
Write-Host "The repo in Explorer: $win"
Write-Host "Mod ROMs:             $win\build\mod\dune2.gen"
if ($WideRom) { Write-Host "                      $win\build\modw\dune2.gen" }
Write-Host "Setup log:            $win\build\setup.log"
if ($launch) {
    Write-Host "Play:                 $play\Play Dune II*.cmd (always the latest build)"
    Write-Host ''
    Write-Host 'Keys: W A S D = pad, keypad 1 2 3 = A B C, Enter = Start, Alt+E = capture/release'
    Write-Host '      the mouse (Sega Mouse), Alt+Enter = fullscreen, Esc = quit.'
    if (-not $NoLaunch) {
        Write-Host ''
        Read-Host "Press Enter to play $(Split-Path $launch -Leaf), or Ctrl+C to finish" | Out-Null
        Start-Process cmd.exe -ArgumentList '/c', "`"$launch`"" -WindowStyle Hidden
    }
} elseif (-not $Mednafen) {
    Write-Host ''
    Write-Host 'To play: open a mod ROM in any Genesis emulator with a Sega Mouse on port 2,'
    Write-Host 'or run this again with the hack''s Mednafen zip in Downloads (see README).'
}

} catch {
    Write-Host ''
    Write-Host "error: $($_.Exception.Message)" -ForegroundColor Red
    if ($PSCommandPath) { exit 1 }   # run as a file: exit code 1 (under iex, just return)
}
} @args
