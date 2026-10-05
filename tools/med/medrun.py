"""Drive the 480x464 Mednafen build (Windows exe, via wine + Xvfb).

Needs wine, Xvfb, xdotool, ImageMagick and the hack's Mednafen 0.9.48.0.H6
(Windows build) unpacked in tools/med/mednafen (or $MEDDIR).  Several can
run in parallel: give each its own MEDDISPLAY (:11, :12, ...), MEDDIR copy
and MEDPREFIX (wine prefix), or windows end up on the wrong display.
On Windows, run mednafen.exe directly instead.

Usage: medrun.py ROM OUTDIR [--wide] [--mouse] script
The script is a ';'-separated list of steps:
  w<ms>            wait
  k<key>:<ms>      hold an X key for ms (Return, KP_1 (A), KP_2 (B), KP_3 (C), w a s d)
  s<name>          screenshot to OUTDIR/<name>.png
  m<dx>,<dy>       relative mouse move
  c<button>:<ms>   hold a mouse button (1 left, 2 middle, 3 right)
"""
import os, subprocess, sys, time

MED = os.environ.get('MEDDIR', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mednafen'))
DISPLAY = os.environ.get('MEDDISPLAY', ':9')


def x(*args):
    return subprocess.run(['xdotool', *args], env=dict(os.environ, DISPLAY=DISPLAY),
                          capture_output=True, text=True).stdout.strip()


def main():
    rom, out, *rest = sys.argv[1:]
    wide = '--wide' in rest
    mouse = '--mouse' in rest
    script = [a for a in rest if not a.startswith('--')][0]
    os.makedirs(out, exist_ok=True)
    if subprocess.run(['xdotool', 'getdisplaygeometry'], env=dict(os.environ, DISPLAY=DISPLAY),
                      capture_output=True).returncode:
        for f in ('/tmp/.X11-unix/X' + DISPLAY[1:], '/tmp/.X%s-lock' % DISPLAY[1:]):
            if os.path.exists(f):
                os.remove(f)        # left over from a server that is gone
        subprocess.Popen(['Xvfb', DISPLAY, '-screen', '0', '1280x1024x24'],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2)
    opts = ['-sound', '0', '-video.driver', 'sdl', '-video.fs', '0', '-md.stretch', '0',
            '-md.xscale', '1', '-md.yscale', '1', '-md.input.port1', 'gamepad6',
            '-md.input.port2', 'megamouse' if mouse else 'gamepad6', '-md.overclock', '7']
    if wide:
        opts += ['-md.screen_x', '480', '-md.screen256_x', '480', '-md.screen_y', '464']
    env = dict(os.environ, DISPLAY=DISPLAY, WINEDEBUG='-all')
    if os.environ.get('MEDPREFIX'):
        env['WINEPREFIX'] = os.environ['MEDPREFIX']
    p = subprocess.Popen(['wine', 'mednafen.exe', *opts, os.path.abspath(rom)], cwd=MED, env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        win = ''
        for _ in range(60):
            ws = [w for w in x('search', '--onlyvisible', '--name', '').split()
                  if x('getwindowname', w)]
            win = ' '.join(ws)
            if win:
                break
            time.sleep(0.5)
        win = win.split()[-1] if win else ''
        print('window', repr(win), x('getwindowname', win) if win else '', flush=True)
        def focus():
            if win:
                x('windowraise', win)
                x('windowfocus', '--sync', win)
        if win:
            x('mousemove', '--window', win, '200', '200')
        focus()
        for step in script.split(';'):
            step = step.strip()
            if not step:
                continue
            op, arg = step[0], step[1:]
            if op == 'w':
                time.sleep(int(arg) / 1000)
            elif op == 'k':
                key, ms = arg.split(':')
                focus()
                x('keydown', key); time.sleep(int(ms) / 1000); x('keyup', key)
            elif op == 's':
                subprocess.run(['import', '-display', DISPLAY, '-window', 'root',
                                os.path.join(out, arg + '.png')], capture_output=True)
            elif op == 'm':
                dx, dy = arg.split(',')
                x('mousemove_relative', '--', dx, dy)
            elif op == 'c':
                b, ms = arg.split(':')
                x('mousedown', b); time.sleep(int(ms) / 1000); x('mouseup', b)
        alive = p.poll() is None
        print('alive' if alive else 'exited %s (see stdout.txt in %s)' % (p.returncode, MED))
    finally:
        p.kill()
        # kill this instance's emulator process (other instances may run on other displays)
        for pid in os.listdir('/proc'):
            try:
                if not pid.isdigit() or 'mednafen' not in open('/proc/%s/cmdline' % pid).read():
                    continue
                if ('DISPLAY=' + DISPLAY + '\0').encode() in open('/proc/%s/environ' % pid, 'rb').read():
                    os.kill(int(pid), 9)
            except OSError:
                pass
    sys.exit(0 if win and alive else 1)


main()
