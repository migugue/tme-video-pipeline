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

Action kinds:
  point                   ring a button/link found by exact text (no click)
  click                   click a button/link found by exact text
  click_button_with_text  same; `right_side: true` picks the wide button at the bottom right
  type                    click input[name=<field>] and type `text`
  type_into_placeholder   click the input whose placeholder contains `placeholder`, type `text`
  scroll_to_text          scroll a label/heading with exact text into view
  hover                   move the real mouse over an element so hover-only controls appear.
                          Target: `text` (exact text of ANY element, e.g. a table cell) or `selector`.
  point_selector          ring an element found by CSS `selector` (no click) - for things that
                          are not buttons, e.g. "label:has(input[name=enable_vlan])"
  click_selector          click an element found by CSS `selector` - for icon buttons with no
                          text and for dropdown options.
  caption                 show `text` as a caption bar at the bottom of the frame ('' hides it).
                          It stays up, across page changes too, until the next caption action.
  scroll                  smooth-scroll a `selector` (optionally filtered by exact `text`) to the
                          top of its scroll area, e.g. {"kind": "scroll", "selector": "#rollback"};
                          `offset` px of space is left above it (default 110).
  wait                    do nothing until `at`
  goto                    navigate to `url`

The three selector kinds (and hover) accept two optional filters:
  "text": "Assign"            keep only matches whose own text is exactly this
  "near_text": "my-profile"   of the matches, take the one on the same row as (vertically
                              closest to) the element with this exact text
e.g. {"at": 40, "kind": "hover", "text": "my-profile"},
     {"at": 41, "kind": "click_selector", "selector": "#options-anchor", "near_text": "my-profile"}

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


OVERLAY = {'js': None, 'caption': '', 'cursor': None}


def inject_overlay(cdp, overlay_js):
    OVERLAY['js'] = overlay_js
    ev(cdp, overlay_js)


def ensure_overlay(cdp, timeout=6):
    """A click or goto that loads a new page wipes the injected cursor and caption.
    Wait for the new document, put the overlay back, and restore what it was showing."""
    if not OVERLAY['js']:
        return
    end = time.time() + timeout
    while time.time() < end:
        try:
            if ev(cdp, 'document.readyState !== "loading" && !!document.body', timeout=3):
                break
        except Exception:
            pass                      # mid-navigation: the old page's context is gone
        time.sleep(0.15)
    try:
        if ev(cdp, '!!(window.__v8demo && document.getElementById("v8-cursor"))', timeout=3):
            return
        ev(cdp, 'delete window.__v8demo')
        ev(cdp, OVERLAY['js'])
        if OVERLAY['cursor']:
            ev(cdp, '__v8demo.moveTo(%s, %s)' % OVERLAY['cursor'])
        ev(cdp, '__v8demo.caption(%s)' % json.dumps(OVERLAY['caption']))
    except Exception:
        pass


def point_box(cdp, box, show_ring=True, hold_ms=500):
    if not box:
        return
    cx = box['x'] + box['w'] / 2
    cy = box['y'] + box['h'] / 2
    ring = ('{x: %s, y: %s, width: %s, height: %s}' % (box['x'], box['y'], box['w'], box['h'])
            if show_ring else 'null')
    OVERLAY['cursor'] = (cx, cy)
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
    try:
        clear_ring(cdp)
    except Exception:
        pass   # the click loaded a new page and took the overlay with it; ensure_overlay restores it


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


def box_by_selector(cdp, selector=None, text=None, near_text=None):
    """Box of a visible element. `selector` narrows by CSS (default: any element),
    `text` keeps exact-text matches, `near_text` picks the match on the same row as
    the element carrying that text. Smallest match wins otherwise."""
    js = f"""
    (() => {{
      const sel = {json.dumps(selector)}, want = {json.dumps(text)}, near = {json.dumps(near_text)};
      const txt = e => (e.innerText || e.textContent || '').trim();
      const vis = e => {{
        if (!e.offsetParent && getComputedStyle(e).position !== 'fixed') return false;
        const r = e.getBoundingClientRect();
        return r.width > 2 && r.height > 2 && r.bottom > 0 && r.top < innerHeight;
      }};
      const area = e => {{ const r = e.getBoundingClientRect(); return r.width * r.height; }};
      const smallest = (css, t) => [...document.querySelectorAll(css)]
        .filter(e => !e.closest('#v8-cursor,#v8-ring,#v8-caption,#v8-key,#v8-tick'))
        .filter(e => vis(e) && (t === null || txt(e) === t))
        .sort((a, b) => area(a) - area(b));
      let cands = smallest(sel || '*', want);
      // Prefer targets that are actually on top (not covered by a side panel or dialog).
      const onTop = e => {{
        const r = e.getBoundingClientRect();
        const h = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
        return !!h && (e === h || e.contains(h) || h.contains(e));
      }};
      const top = cands.filter(onTop);
      if (top.length) cands = top;
      if (!cands.length) return null;
      if (near !== null) {{
        const anchor = smallest('*', near)[0];
        if (!anchor) return null;
        const ar = anchor.getBoundingClientRect(), ay = ar.y + ar.height / 2;
        const dy = e => {{ const r = e.getBoundingClientRect(); return Math.abs(r.y + r.height / 2 - ay); }};
        cands.sort((a, b) => dy(a) - dy(b));
      }}
      const r = cands[0].getBoundingClientRect();
      return {{x: r.x, y: r.y, w: r.width, h: r.height}};
    }})()
    """
    return ev(cdp, js)


def target_box(cdp, action, timeout=5):
    """Resolve the selector/text/near_text target of an action, waiting for it to appear."""
    if not (action.get('selector') or action.get('text')):
        raise ValueError(f'{action["kind"]} needs "selector" or "text"')
    desc = ' '.join(f'{k}={action[k]!r}' for k in ('selector', 'text', 'near_text') if action.get(k))
    return wait_for(lambda: box_by_selector(cdp, action.get('selector'), action.get('text'),
                                            action.get('near_text')),
                    timeout=timeout, desc=f'{action["kind"]} target {desc}')


def mouse_move(cdp, box):
    """Move the REAL mouse (not just the overlay cursor) so :hover styles and
    mouseenter handlers fire."""
    cdp.send('Input.dispatchMouseEvent', {
        'type': 'mouseMoved', 'x': box['x'] + box['w'] / 2, 'y': box['y'] + box['h'] / 2,
    }, timeout=5)


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

    elif kind == 'hover':
        box = target_box(cdp, action)
        point_box(cdp, box, show_ring=action.get('ring', False), hold_ms=action.get('lead_ms', 300))
        mouse_move(cdp, box)
        time.sleep(action.get('hold_ms', 400) / 1000)

    elif kind == 'point_selector':
        try:
            box = target_box(cdp, action, timeout=3)
        except RuntimeError:
            if action.get('optional'):
                return
            raise
        point_box(cdp, box, hold_ms=action.get('hold_ms', 600))

    elif kind == 'click_selector':
        box = target_box(cdp, action)
        point_box(cdp, box, hold_ms=action.get('lead_ms', 300))
        mouse_move(cdp, box)
        mouse_click(cdp, box)

    elif kind == 'caption':
        OVERLAY['caption'] = action.get('text', '')
        ev(cdp, '__v8demo.caption(%s)' % json.dumps(OVERLAY['caption']))

    elif kind == 'scroll':
        js = """
        (() => {
          const sel = %s, want = %s, off = %s;
          const txt = e => (e.innerText || e.textContent || '').trim();
          const el = [...document.querySelectorAll(sel)].find(e => want === null || txt(e) === want);
          if (!el) return false;
          el.style.scrollMarginTop = off + 'px';
          el.scrollIntoView({behavior: 'smooth', block: 'start'});
          return true;
        })()""" % (json.dumps(action['selector']), json.dumps(action.get('text')), int(action.get('offset', 110)))
        wait_for(lambda: ev(cdp, js), timeout=6, desc=f'scroll target {action["selector"]!r}')

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
    # retime.py needs the exact text this take was spoken with, even if the spec is edited later
    with open(os.path.join(build_dir, 'draft_narration.txt'), 'w') as f:
        f.write(spec['narration'])
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
            ensure_overlay(cdp)
            run_action(cdp, action, t0)
            if action.get('kind') in ('click', 'click_selector', 'click_button_with_text', 'goto'):
                time.sleep(0.25)
                ensure_overlay(cdp)   # the click may have loaded a new page

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
