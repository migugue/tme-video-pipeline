"""Record a narrated walkthrough of a simulated CLI session.

Usage:
    python record_terminal.py <spec.json>

Spec format:
{
  "name": "mm_cli_show_hierarchy",
  "prompt": "(OWL_MCr01) *[mynode] #",
  "narration": "...[[slnc 500]]...",
  "voice": "Zoe (Premium)",
  "steps": [
    {"at": 11.5, "type_cmd": "no paging",                             "ms_per_char": 60},
    {"at": 18.5, "type_cmd": "show configuration node-hierarchy",     "ms_per_char": 55},
    {"at": 22.5, "print_output_from": "output.txt",                   "ms_per_line": 40}
  ]
}

`print_output_from` is a path relative to the spec file; its contents go into
the terminal as the command output. Capture a real SecureCRT session log, drop
it in alongside the spec, done.

Output: out/<name>.mp4 + out/<name>.srt
"""
import json
import os
import subprocess
import sys
import threading
import time

import imageio_ffmpeg

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cdp_core
from narration import build_m4a, audio_duration, DEFAULT_VOICE

FF = imageio_ffmpeg.get_ffmpeg_exe()
CDP_URL = os.environ.get('TME_CDP_URL', 'http://127.0.0.1:9333')
TERMINAL_HTML = os.path.join(HERE, 'terminal.html')


def ev(cdp, expr, timeout=20, await_promise=False):
    r = cdp.send('Runtime.evaluate', {'expression': expr, 'returnByValue': True,
                                      'awaitPromise': await_promise}, timeout=timeout)
    if r.get('exceptionDetails'):
        raise RuntimeError(f'JS err: {r["exceptionDetails"]}')
    return r['result'].get('value')


def hold_until(t0, when):
    remaining = when - (time.time() - t0)
    if remaining > 0:
        time.sleep(remaining)


def srt_time(sec):
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f'{int(h):02d}:{int(m):02d}:{s:06.3f}'.replace('.', ',')


def main(spec_path):
    spec = json.load(open(spec_path))
    name = spec.get('name') or os.path.splitext(os.path.basename(spec_path))[0]
    spec_dir = os.path.dirname(os.path.abspath(spec_path))

    out_dir = os.path.join(os.getcwd(), 'out')
    build_dir = os.path.join(os.getcwd(), 'build', name)
    os.makedirs(out_dir, exist_ok=True); os.makedirs(build_dir, exist_ok=True)

    # 1. Narration
    audio_m4a = os.path.join(build_dir, 'narration.m4a')
    build_m4a(spec['narration'], audio_m4a, voice=spec.get('voice', DEFAULT_VOICE))
    dur = audio_duration(audio_m4a)
    print(f'narration: {dur:.2f} s')

    # 2. Open a fresh Chrome tab at file://terminal.html
    bcdp = cdp_core.CDP(cdp_core.browser_ws_url(CDP_URL))
    try:
        bcdp.send('Target.createTarget',
                  {'url': 'file://' + TERMINAL_HTML, 'newWindow': False, 'background': False},
                  timeout=10)
    finally:
        bcdp.close()
    time.sleep(1.5)

    tab = cdp_core.pick_tab(CDP_URL, 'terminal.html')
    cdp = cdp_core.CDP(tab['webSocketDebuggerUrl'])
    try:
        cdp.send('Page.enable'); cdp.send('Runtime.enable')
        cdp.send('Page.bringToFront'); time.sleep(0.4)
        cdp_core.set_viewport(cdp, cdp_core.resolve_viewport(spec))

        vw = ev(cdp, 'innerWidth'); vh = ev(cdp, 'innerHeight')
        print(f'viewport: {vw}x{vh}')

        prompt = spec.get('prompt', '($) #').replace('\\', '\\\\').replace("'", "\\'")
        ev(cdp, f"__v8term.init('{prompt}')", await_promise=True)
        time.sleep(0.3)

        frames_dir = os.path.join(build_dir, 'frames')
        rec = cdp_core.Recorder(cdp, frames_dir)
        rec.start(vw, vh)
        time.sleep(0.5)
        t0 = time.time()

        # 3. Run steps at their narration anchors (type/print in background threads so
        # the step itself doesn't block subsequent anchors)
        for i, step in enumerate(spec['steps']):
            at = step.get('at', 0)
            hold_until(t0, at)

            if 'type_cmd' in step:
                cmd = step['type_cmd'].replace('\\', '\\\\').replace("'", "\\'")
                mspc = step.get('ms_per_char', 65)
                def _type(cmd=cmd, mspc=mspc):
                    ev(cdp, f"__v8term.typeCommand('{cmd}', {mspc})", await_promise=True, timeout=15)
                    ev(cdp, "__v8term.newPrompt()", timeout=5)
                threading.Thread(target=_type, daemon=True).start()

            elif 'print_output_from' in step:
                out_path = step['print_output_from']
                if not os.path.isabs(out_path):
                    out_path = os.path.join(spec_dir, out_path)
                with open(out_path) as f:
                    lines = f.read().splitlines()
                mspl = step.get('ms_per_line', 40)
                lines_js = json.dumps(lines)
                def _print(lines_js=lines_js, mspl=mspl):
                    ev(cdp, f"__v8term.printOutput({lines_js}, {mspl})",
                       await_promise=True, timeout=60)
                threading.Thread(target=_print, daemon=True).start()

            elif 'print_output' in step:
                lines = step['print_output']
                mspl = step.get('ms_per_line', 40)
                lines_js = json.dumps(lines)
                def _print(lines_js=lines_js, mspl=mspl):
                    ev(cdp, f"__v8term.printOutput({lines_js}, {mspl})",
                       await_promise=True, timeout=60)
                threading.Thread(target=_print, daemon=True).start()

            print(f'  step {i}: {list(step.keys())} @ {at}s')

        # 4. Hold through narration end, keep frames flowing
        end = t0 + dur + 0.4
        while time.time() < end:
            ev(cdp, 'void(0)')
            time.sleep(0.15)

        total = time.time() - t0
        rec.stop()
        print(f'captured {len(rec.frames)} frames over {total:.2f}s')
    finally:
        cdp_core.clear_viewport(cdp)
        cdp.close()
        # Close the terminal tab
        try:
            bcdp2 = cdp_core.CDP(cdp_core.browser_ws_url(CDP_URL))
            try:
                import urllib.request
                tabs = json.loads(urllib.request.urlopen(f'{CDP_URL}/json').read().decode())
                for t in tabs:
                    if 'terminal.html' in (t.get('url') or ''):
                        bcdp2.send('Target.closeTarget', {'targetId': t['id']}, timeout=5)
                        break
            finally:
                bcdp2.close()
        except Exception:
            pass

    frames = rec.frames
    if not frames:
        raise SystemExit('no frames captured')

    FPS = 30
    seq_dir = os.path.join(build_dir, 'seq')
    os.makedirs(seq_dir, exist_ok=True)
    for f in os.listdir(seq_dir):
        os.remove(os.path.join(seq_dir, f))
    f0 = frames[0][0]
    live = [(ts - f0, p) for ts, p in frames]
    target_frames = int(round(max(total, dur + 0.4) * FPS))
    j = 0
    for k in range(target_frames):
        t = k / FPS
        while j + 1 < len(live) and live[j + 1][0] <= t:
            j += 1
        os.link(live[j][1], os.path.join(seq_dir, f'{k:06}.jpg'))

    out_mp4 = os.path.join(out_dir, f'{name}.mp4')
    length = max(total, dur + 0.4)
    subprocess.run([
        FF, '-y', '-loglevel', 'warning',
        '-framerate', str(FPS), '-i', os.path.join(seq_dir, '%06d.jpg'),
        '-i', audio_m4a,
        '-vf', 'pad=ceil(iw/2)*2:ceil(ih/2)*2,format=yuv420p',
        '-c:v', 'libx264', '-preset', 'medium', '-crf', '20',
        '-c:a', 'aac', '-b:a', '160k',
        '-shortest', '-t', f'{length:.2f}', '-movflags', '+faststart',
        out_mp4,
    ], check=True)

    srt_path = os.path.join(out_dir, f'{name}.srt')
    with open(srt_path, 'w') as f:
        f.write('1\n')
        f.write(f'{srt_time(0)} --> {srt_time(dur)}\n')
        f.write(spec['narration'].replace('[[slnc', '').replace(']]', '') + '\n')

    print(f'wrote {out_mp4} ({length:.1f} s)')
    print(f'wrote {srt_path}')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.stderr.write('usage: record_terminal.py <spec.json>\n'); sys.exit(2)
    main(sys.argv[1])
