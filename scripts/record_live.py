"""Record a narrated walkthrough of a live web app you're already logged into.

Usage:
    python record_live.py <spec.json>

Spec format (JSON):
{
  "name": "central_ntp_demo",
  "tab_match": "central.arubanetworks.com",   // substring of the already-open Chrome tab URL
  "start_url": "https://...",                  // optional, navigates there first
  "narration": "...[[slnc 500]]...",           // say script, [[slnc N]] pauses honored
  "voice": "Zoe (Premium)",                    // optional override
  "viewport": [1920, 1080],                    // optional; default 1920x1080, "window" = as-is
  "actions": [
    {"at": 6.3, "kind": "point",  "text": "Config"},
    {"at": 10.1, "kind": "click", "text": "Create Profile"},
    {"at": 11.9, "kind": "type",  "field": "name", "text": "Owl-Bar-NTP-Demo"},
    {"at": 17.5, "kind": "scroll_to_text", "text": "NTP Server *"},
    {"at": 22.0, "kind": "click_button_with_text", "text": "Create", "right_side": true}
  ]
}

Each action's `at` is seconds after screencast starts. Clicks lead the narration
cue by ~0.2 s so the voice confirms what just happened.

Output: out/<name>.mp4 + out/<name>.srt
"""
import json
import os
import subprocess
import sys
import time

import imageio_ffmpeg

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cdp_core
from narration import build_m4a, audio_duration, DEFAULT_VOICE

FF = imageio_ffmpeg.get_ffmpeg_exe()
CDP_URL = os.environ.get('TME_CDP_URL', 'http://127.0.0.1:9333')


# ---------- CDP helpers ----------
def ev(cdp, expr, timeout=10):
    r = cdp.send('Runtime.evaluate', {'expression': expr, 'returnByValue': True}, timeout=timeout)
    if r.get('exceptionDetails'):
        raise RuntimeError(f'JS error: {r["exceptionDetails"]}')
    return r['result'].get('value')


def inject_overlay(cdp, overlay_js):
    ev(cdp, overlay_js)


def point_box(cdp, box, show_ring=True, hold_ms=500):
    if not box:
        return
    cx = box['x'] + box['w'] / 2
    cy = box['y'] + box['h'] / 2
    ring = ('{x: %s, y: %s, width: %s, height: %s}' % (box['x'], box['y'], box['w'], box['h'])
            if show_ring else 'null')
    ev(cdp, '__v8demo.moveTo(%s, %s); __v8demo.ring(%s);' % (cx, cy, ring))
    time.sleep(hold_ms / 1000)


def clear_ring(cdp):
    ev(cdp, '__v8demo.ring(null);')


def mouse_click(cdp, box):
    cx, cy = box['x'] + box['w'] / 2, box['y'] + box['h'] / 2
    ev(cdp, '__v8demo.click()')
    for t in ('mousePressed', 'mouseReleased'):
        cdp.send('Input.dispatchMouseEvent', {
            'type': t, 'x': cx, 'y': cy, 'button': 'left',
            'clickCount': 1, 'buttons': 1,
        }, timeout=5)
    time.sleep(0.3)
    clear_ring(cdp)


def type_text(cdp, s, delay_ms=65):
    for ch in s:
        cdp.send('Input.dispatchKeyEvent', {'type': 'char', 'text': ch, 'key': ch}, timeout=5)
        time.sleep(delay_ms / 1000)


def box_by_text(cdp, text):
    js = f"""
    (() => {{
      const want = {text!r};
      const cands = [...document.querySelectorAll('button, [role=button], a')].filter(e => {{
        if (!e.offsetParent) return false;
        const t = (e.innerText || e.textContent || '').trim();
        if (t !== want) return false;
        const r = e.getBoundingClientRect();
        return r.width > 2 && r.height > 2 && r.top >= 0 && r.top < innerHeight;
      }});
      if (!cands.length) return null;
      cands.sort((a, b) => {{
        const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
        return (ra.width * ra.height) - (rb.width * rb.height);
      }});
      const r = cands[0].getBoundingClientRect();
      return {{x: r.x, y: r.y, w: r.width, h: r.height}};
    }})()
    """
    return ev(cdp, js)


def input_by_name(cdp, name, x_min=0):
    js = f"""
    (() => {{
      const sel = 'input[name="{name}"], textarea[name="{name}"]';
      for (const el of document.querySelectorAll(sel)) {{
        if (!el.offsetParent) continue;
        const r = el.getBoundingClientRect();
        if (r.x < {x_min} || r.width < 1) continue;
        return {{x: r.x, y: r.y, w: r.width, h: r.height}};
      }}
      return null;
    }})()
    """
    return ev(cdp, js)


def input_by_placeholder(cdp, ph_substr):
    js = f"""
    (() => {{
      const want = {ph_substr!r}.toLowerCase();
      for (const el of document.querySelectorAll('input, textarea')) {{
        if (!el.offsetParent) continue;
        const p = (el.placeholder || '').toLowerCase();
        if (!p.includes(want)) continue;
        const r = el.getBoundingClientRect();
        if (r.width < 1) continue;
        return {{x: r.x, y: r.y, w: r.width, h: r.height}};
      }}
      return null;
    }})()
    """
    return ev(cdp, js)


def wide_button_at_bottom(cdp, text, x_min=1500):
    js = f"""
    (() => {{
      const want = {text!r};
      const cands = [...document.querySelectorAll('button')].filter(b => {{
        if (!b.offsetParent) return false;
        if ((b.innerText||'').trim() !== want) return false;
        const r = b.getBoundingClientRect();
        return r.x > {x_min} && r.width > 40;
      }});
      if (!cands.length) return null;
      cands.sort((a,b) => b.getBoundingClientRect().y - a.getBoundingClientRect().y);
      const r = cands[0].getBoundingClientRect();
      return {{x: r.x, y: r.y, w: r.width, h: r.height}};
    }})()
    """
    return ev(cdp, js)


def scroll_to_text(cdp, text):
    ev(cdp, f"""(() => {{
      const want = {text!r};
      const el = [...document.querySelectorAll('div, span, label, h1, h2, h3')].find(e =>
        e.offsetParent && (e.innerText||'').trim() === want);
      if (el) el.scrollIntoView({{block: 'center', behavior: 'instant'}});
    }})()""")
    time.sleep(0.3)


def wait_for(fn, timeout=8, interval=0.25, desc='condition'):
    end = time.time() + timeout
    while time.time() < end:
        r = fn()
        if r:
            return r
        time.sleep(interval)
    raise RuntimeError(f'timeout waiting for {desc}')


def hold_until(t0, when):
    remaining = when - (time.time() - t0)
    if remaining > 0:
        time.sleep(remaining)


def srt_time(sec):
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f'{int(h):02d}:{int(m):02d}:{s:06.3f}'.replace('.', ',')


# ---------- action runner ----------
def run_action(cdp, action, t0):
    at = action.get('at', 0)
    hold_until(t0, at)
    kind = action['kind']

    if kind == 'point':
        box = box_by_text(cdp, action['text'])
        if not box and action.get('optional'):
            return
        if not box:
            raise RuntimeError(f'point target not found: {action["text"]!r}')
        point_box(cdp, box, hold_ms=action.get('hold_ms', 600))

    elif kind == 'click':
        box = wait_for(lambda: box_by_text(cdp, action['text']), timeout=4,
                       desc=f'click target {action["text"]!r}')
        point_box(cdp, box, hold_ms=action.get('lead_ms', 300))
        mouse_click(cdp, box)

    elif kind == 'type':
        field = action['field']
        box = wait_for(lambda: input_by_name(cdp, field, x_min=action.get('x_min', 0)),
                       timeout=5, desc=f'input[name={field!r}]')
        point_box(cdp, box, hold_ms=200)
        mouse_click(cdp, box)
        time.sleep(0.3)
        type_text(cdp, action['text'], delay_ms=action.get('delay_ms', 65))

    elif kind == 'type_into_placeholder':
        box = wait_for(lambda: input_by_placeholder(cdp, action['placeholder']),
                       timeout=5, desc=f'input placeholder~{action["placeholder"]!r}')
        point_box(cdp, box, hold_ms=200)
        mouse_click(cdp, box)
        time.sleep(0.3)
        type_text(cdp, action['text'], delay_ms=action.get('delay_ms', 65))

    elif kind == 'click_button_with_text':
        if action.get('right_side'):
            box = wait_for(lambda: wide_button_at_bottom(cdp, action['text']),
                           timeout=5, desc=f'wide button {action["text"]!r}')
        else:
            box = wait_for(lambda: box_by_text(cdp, action['text']), timeout=5,
                           desc=f'button {action["text"]!r}')
        point_box(cdp, box, hold_ms=action.get('lead_ms', 300))
        mouse_click(cdp, box)

    elif kind == 'scroll_to_text':
        scroll_to_text(cdp, action['text'])

    elif kind == 'wait':
        pass  # `at` already held us here

    elif kind == 'goto':
        cdp.send('Page.navigate', {'url': action['url']})
        time.sleep(action.get('settle', 3.0))

    else:
        raise ValueError(f'unknown action kind: {kind!r}')


# ---------- main ----------
def main(spec_path):
    spec = json.load(open(spec_path))
    name = spec.get('name') or os.path.splitext(os.path.basename(spec_path))[0]
    tab_match = spec['tab_match']

    # 1. Render narration audio
    out_dir = os.path.join(os.getcwd(), 'out')
    build_dir = os.path.join(os.getcwd(), 'build', name)
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(build_dir, exist_ok=True)

    audio_m4a = os.path.join(build_dir, 'narration.m4a')
    build_m4a(spec['narration'], audio_m4a, voice=spec.get('voice', DEFAULT_VOICE))
    dur = audio_duration(audio_m4a)
    print(f'narration: {dur:.2f} s')

    # 2. Attach to Chrome, inject overlay, start screencast
    overlay_js = open(os.path.join(HERE, 'overlay.js')).read()

    tab = cdp_core.pick_tab(CDP_URL, tab_match)
    cdp = cdp_core.CDP(tab['webSocketDebuggerUrl'])
    try:
        cdp.send('Page.enable'); cdp.send('Runtime.enable')
        cdp.send('Page.bringToFront'); time.sleep(0.3)
        cdp_core.set_viewport(cdp, cdp_core.resolve_viewport(spec))

        if spec.get('start_url'):
            cdp.send('Page.navigate', {'url': spec['start_url']})
            time.sleep(spec.get('nav_settle', 5.0))

        vw = ev(cdp, 'innerWidth'); vh = ev(cdp, 'innerHeight')
        print(f'viewport: {vw}x{vh}')

        inject_overlay(cdp, overlay_js)
        ev(cdp, '__v8demo.moveTo(600, 400); __v8demo.ring(null);')
        time.sleep(0.3)

        frames_dir = os.path.join(build_dir, 'frames')
        rec = cdp_core.Recorder(cdp, frames_dir)
        rec.start(vw, vh)
        time.sleep(0.5)
        t0 = time.time()

        # 3. Run actions in order
        for i, action in enumerate(spec['actions']):
            print(f'  action {i}: {action.get("kind")} @ {action.get("at")}s')
            run_action(cdp, action, t0)

        # 4. Hold through end of narration, keeping overlay repaint active
        end = t0 + dur + 0.4
        while time.time() < end:
            ev(cdp, 'void(0)')
            time.sleep(0.15)

        total = time.time() - t0
        rec.stop()
        print(f'captured {len(rec.frames)} frames over {total:.2f}s')

        # Clear overlay
        ev(cdp, """(() => { for (const id of ['v8-cursor','v8-ring','v8-caption','v8-key','v8-tick'])
            { const e=document.getElementById(id); if (e) e.remove(); } delete window.__v8demo; })()""")
    finally:
        cdp_core.clear_viewport(cdp)
        cdp.close()

    frames = rec.frames
    if not frames:
        raise SystemExit('no frames captured — check that Chrome tab was visible')

    # 5. Resample frames at 30 fps using CDP timestamps
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

    # 6. Mux
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

    # 7. Write a single-caption SRT (the whole narration as one entry; good enough
    # for YouTube's auto-chapterer to anchor against)
    srt_path = os.path.join(out_dir, f'{name}.srt')
    with open(srt_path, 'w') as f:
        f.write('1\n')
        f.write(f'{srt_time(0)} --> {srt_time(dur)}\n')
        f.write(spec['narration'].replace('[[slnc', '').replace(']]', '') + '\n')

    print(f'wrote {out_mp4} ({length:.1f} s)')
    print(f'wrote {srt_path}')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.stderr.write('usage: record_live.py <spec.json>\n'); sys.exit(2)
    main(sys.argv[1])
