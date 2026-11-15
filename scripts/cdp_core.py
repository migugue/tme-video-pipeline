"""Minimal raw Chrome DevTools Protocol client over websocket.

Sidesteps Playwright's connect_over_cdp hang against recent Chrome releases.
Everything the recorder needs: pick a tab, screencast JPEG frames, inject JS,
click by coordinate, type text.
"""
import base64
import json
import os
import threading
import time
import urllib.request

import websocket  # websocket-client


class CDP:
    """One websocket to one browser or page target.

    Thread-safe for a single driver + the internal reader thread; the reader
    thread MUST call `fire()` (not `send()`) when it wants to emit a message
    from inside an event handler, because `send()` waits for a response that
    only the reader thread can deliver.
    """

    def __init__(self, ws_url):
        self.ws = websocket.create_connection(ws_url, enable_multithread=True)
        self._id = 0
        self._id_lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._pending = {}        # id -> (event, result_box)
        self._handlers = {}       # method -> callback
        self._alive = True
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def _read_loop(self):
        while self._alive:
            try:
                raw = self.ws.recv()
            except Exception:
                return
            if not raw:
                continue
            msg = json.loads(raw)
            if 'id' in msg and msg['id'] in self._pending:
                ev, box = self._pending.pop(msg['id'])
                if box.get('_discard'):
                    continue
                box['result'] = msg.get('result')
                box['error'] = msg.get('error')
                ev.set()
            elif 'method' in msg:
                cb = self._handlers.get(msg['method'])
                if cb:
                    try:
                        cb(msg.get('params') or {})
                    except Exception as e:
                        print(f'[cdp] handler {msg["method"]} raised: {e}')

    def on(self, method, cb):
        self._handlers[method] = cb

    def send(self, method, params=None, timeout=30):
        with self._id_lock:
            self._id += 1
            mid = self._id
        ev = threading.Event()
        box = {}
        self._pending[mid] = (ev, box)
        with self._send_lock:
            self.ws.send(json.dumps({'id': mid, 'method': method, 'params': params or {}}))
        if not ev.wait(timeout):
            self._pending.pop(mid, None)
            raise TimeoutError(f'{method} did not respond in {timeout}s')
        if box.get('error'):
            raise RuntimeError(f'{method} error: {box["error"]}')
        return box.get('result') or {}

    def fire(self, method, params=None):
        """Send a command without waiting for its response.

        Safe to call from inside an event handler (where `send` would deadlock
        because only the reader thread can deliver the response).
        """
        with self._id_lock:
            self._id += 1
            mid = self._id
        self._pending[mid] = (threading.Event(), {'_discard': True})
        with self._send_lock:
            self.ws.send(json.dumps({'id': mid, 'method': method, 'params': params or {}}))

    def close(self):
        self._alive = False
        try:
            self.ws.close()
        except Exception:
            pass


def pick_tab(cdp_url, url_substr):
    tabs = json.loads(urllib.request.urlopen(f'{cdp_url}/json').read().decode())
    for t in tabs:
        if t.get('type') == 'page' and url_substr in (t.get('url') or ''):
            return t
    raise RuntimeError(
        f'no page tab with URL containing {url_substr!r}; '
        f'tabs found: {[t.get("url") for t in tabs]}'
    )


def browser_ws_url(cdp_url):
    info = json.loads(urllib.request.urlopen(f'{cdp_url}/json/version').read().decode())
    return info['webSocketDebuggerUrl']


class Recorder:
    """Chrome screencast -> JPEG files on disk, timestamped.

    `start(w, h)` begins the screencast at the given max dimensions; frames land
    in `folder` as zero-padded `000000.jpg` files. `frames` is a list of
    (timestamp_s, path) tuples for post-processing into a video.
    """

    def __init__(self, cdp, folder):
        self.cdp = cdp
        self.folder = folder
        self.frames = []
        os.makedirs(folder, exist_ok=True)
        for f in os.listdir(folder):
            os.remove(os.path.join(folder, f))
        cdp.on('Page.screencastFrame', self._frame)

    def _frame(self, params):
        n = len(self.frames)
        path = os.path.join(self.folder, f'{n:06}.jpg')
        with open(path, 'wb') as f:
            f.write(base64.b64decode(params['data']))
        ts = params.get('metadata', {}).get('timestamp') or time.time()
        self.frames.append((ts, path))
        # Fire-and-forget: send() would deadlock (we're inside the reader
        # thread, and only the reader thread can deliver the ack's response).
        try:
            self.cdp.fire('Page.screencastFrameAck', {'sessionId': params['sessionId']})
        except Exception:
            pass

    def start(self, w, h, quality=92):
        self.cdp.send('Page.startScreencast', {
            'format': 'jpeg', 'quality': quality,
            'maxWidth': w, 'maxHeight': h, 'everyNthFrame': 1,
        })

    def stop(self):
        try:
            self.cdp.send('Page.stopScreencast')
        except Exception:
            pass


# ---------- viewport ----------
DEFAULT_VIEWPORT = (1920, 1080)


def resolve_viewport(spec):
    """Recording size as (w, h), or None to record the window as-is.

    Precedence: spec "viewport" ([w, h] or "window"), then TME_VIEWPORT
    env ("1920x1080" or "window"), then DEFAULT_VIEWPORT.
    """
    v = spec.get('viewport', os.environ.get('TME_VIEWPORT'))
    if v is None:
        return DEFAULT_VIEWPORT
    if v == 'window':
        return None
    if isinstance(v, str):
        v = v.lower().split('x')
    w, h = (int(n) for n in v)
    return w, h


def set_viewport(cdp, size, zoom=1):
    """Pin the page to an exact size, independent of window size. `zoom` > 1 lays the page
    out in fewer CSS pixels and renders them larger, so the recorded frame keeps `size`
    pixels but everything on it is `zoom` times bigger."""
    if size:
        cdp.send('Emulation.setDeviceMetricsOverride', {
            'width': round(size[0] / zoom), 'height': round(size[1] / zoom),
            'deviceScaleFactor': zoom, 'mobile': False,
        })


def clear_viewport(cdp):
    try:
        cdp.send('Emulation.clearDeviceMetricsOverride')
    except Exception:
        pass
