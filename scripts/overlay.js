// Injected into the recorded Chrome tab. Provides:
//   __v8demo.moveTo(x, y)    - glide the on-screen cursor to (x, y)
//   __v8demo.ring(rect)      - highlight ring around {x, y, width, height}, or null to clear
//   __v8demo.click()         - pulse-click animation at the cursor's current spot
//   __v8demo.caption(text)   - bottom-of-screen caption; '' to hide
//   __v8demo.keycap(text)    - bottom-right key indicator (e.g. 'Enter')
//   __v8demo.blurSecrets()   - redact long hex strings (encryption keys, etc.)
//
// Idempotent: if already injected, does nothing.

(() => {
  if (window.__v8demo || location.protocol === 'file:') {
    // file:// is our simulated terminal; it doesn't need the overlay.
    if (location.protocol === 'file:' && !window.__v8demo) {
      window.__v8demo = { moveTo(){}, ring(){}, click(){}, caption(){}, keycap(){}, blurSecrets(){} };
    }
    return;
  }
  const css = `
    #v8-cursor { position: fixed; z-index: 2147483647; width: 22px; height: 22px; pointer-events: none;
      left: 50vw; top: 50vh; transition: left .55s cubic-bezier(.3,.7,.3,1), top .55s cubic-bezier(.3,.7,.3,1);
      filter: drop-shadow(0 1px 2px rgba(0,0,0,.5)); }
    #v8-cursor.click::after { content: ''; position: absolute; left: -9px; top: -9px; width: 40px; height: 40px;
      border-radius: 50%; border: 3px solid rgba(1,169,130,.95); animation: v8pulse .45s ease-out forwards; }
    @keyframes v8pulse { from { transform: scale(.3); opacity: 1 } to { transform: scale(1.3); opacity: 0 } }
    #v8-ring { position: fixed; z-index: 2147483646; pointer-events: none; border: 3px solid #01A982;
      border-radius: 10px; box-shadow: 0 0 0 6px rgba(1,169,130,.18); opacity: 0; transition: all .35s ease; }
    #v8-caption { position: fixed; z-index: 2147483645; left: 50%; bottom: 28px; transform: translateX(-50%);
      max-width: 1100px; width: max-content; padding: 12px 22px; border-radius: 10px; pointer-events: none;
      background: rgba(10,14,22,.86); color: #fff; font: 600 21px/1.4 Inter, system-ui, sans-serif;
      text-align: center; opacity: 0; transition: opacity .3s ease; }
    #v8-key { position: fixed; z-index: 2147483647; right: 36px; bottom: 36px; pointer-events: none;
      padding: 10px 18px; border-radius: 10px; background: rgba(42,45,57,.92); color: #fff;
      font: 600 26px/1 Inter, system-ui, sans-serif; letter-spacing: .04em; opacity: 0; transition: opacity .25s ease; }
    /* Keeps the page repainting so the recorder gets a frame every vsync: Chrome's screencast sends frames
       only on change, and Playwright compresses still stretches, which puts the picture ahead of the voice. */
    #v8-tick { position: fixed; z-index: 2147483647; left: 0; bottom: 0; width: 2px; height: 2px; pointer-events: none;
      background: #888; opacity: .03; animation: v8tick 1s linear infinite; }
    @keyframes v8tick { to { transform: translateX(1px); } }`;
  const st = document.createElement('style'); st.textContent = css;
  const cur = document.createElement('div'); cur.id = 'v8-cursor';
  cur.innerHTML = '<svg viewBox="0 0 24 24" width="22" height="22"><path d="M3 2l7 19 2.6-7.4L20 11z" fill="#fff" stroke="#111" stroke-width="1.5" stroke-linejoin="round"/></svg>';
  const ring = document.createElement('div'); ring.id = 'v8-ring';
  const cap = document.createElement('div'); cap.id = 'v8-caption';
  const key = document.createElement('div'); key.id = 'v8-key';
  const tick = document.createElement('div'); tick.id = 'v8-tick';
  const add = () => { document.head.appendChild(st); document.body.append(cur, ring, cap, key, tick); };
  document.body ? add() : document.addEventListener('DOMContentLoaded', add);
  window.__v8demo = {
    moveTo(x, y) { cur.style.left = x + 'px'; cur.style.top = y + 'px'; },
    ring(r) {
      if (!r) { ring.style.opacity = 0; return; }
      Object.assign(ring.style, {
        left: (r.x - 6) + 'px', top: (r.y - 6) + 'px',
        width: (r.width + 12) + 'px', height: (r.height + 12) + 'px',
        opacity: 1
      });
    },
    click() { cur.classList.remove('click'); void cur.offsetWidth; cur.classList.add('click'); },
    caption(t) { cap.textContent = t || ''; cap.style.opacity = t ? 1 : 0; },
    keycap(t) { key.textContent = t; key.style.opacity = 1; clearTimeout(key._t);
      key._t = setTimeout(() => { key.style.opacity = 0; }, 1400); },
    blurSecrets() {
      const re = /\b[0-9a-fA-F]{24,}\b/;
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      const hits = [];
      while (walker.nextNode()) {
        const n = walker.currentNode;
        if (re.test(n.nodeValue) && !n.parentElement.closest('.v8-secret,#v8-caption')) hits.push(n);
      }
      hits.forEach(n => {
        const span = document.createElement('span');
        span.innerHTML = n.nodeValue.replace(/\b([0-9a-fA-F]{24,})\b/g,
          '<span class="v8-secret" style="filter:blur(6px);user-select:none">$1</span>');
        n.replaceWith(span);
      });
    },
  };
})();
