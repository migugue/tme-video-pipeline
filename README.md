# tme-video-pipeline

Record narrated walkthrough videos of live web apps (Aruba Central, VALID8, anything you're logged into in Chrome) and CLI sessions, with zero software cost on the default path.

**Status:** v0.0.1 — Mac-only, pilot audience of ~5 TMEs. Expect rough edges.

## What it does

- Captures a live Chrome tab as video via raw Chrome DevTools Protocol (no Playwright, no screen-recording permission, Chrome-version-proof)
- Captures a simulated terminal (black bg, light green text) for CLI walkthroughs — paste in a SecureCRT session log, get a typewriter-animated video
- Default narration uses macOS `say` with the Zoe Premium voice — **zero cost**
- Optional revoice step uploads to Descript, applies acronym spelling rules (NTP → "N-T-P", MAC → "Mac", etc.) via the Descript MCP server, then pulls the finished video back after you revoice in your cloned voice

## Requirements

- macOS (Intel or Apple Silicon)
- Claude Code installed (desktop app OR VS Code extension — either works)
- Python 3.11 or later
- Chrome Stable
- Zoe Premium macOS voice (System Settings → Accessibility → Spoken Content → System Voice → Manage Voices → English (United Kingdom) → Zoe Premium)
- A Descript account with a cloned voice, if you want to use `/video-revoice`

## Install

```
claude plugin install migugue/tme-video-pipeline
```

Then, in any folder where you want to produce videos:

```
/video-bootstrap
```

That skill will:
1. Create a `.venv/` in the current folder (no sudo)
2. `pip install` the handful of Python dependencies (honors `HTTPS_PROXY`)
3. Verify Chrome, Zoe Premium, and ffmpeg are reachable
4. Ask for your cloned Descript voice name (if you plan to use `/video-revoice`)
5. Save your preferences to `~/.config/tme-video/tme-video.toml`
6. Record a 10-second hello-world demo

## Daily workflow

```
/video-new  "Describe the video you want in a sentence or two"
   → Claude drafts a spec, you edit it conversationally

/video-record
   → raw-CDP captures your Chrome, Zoe narrates
   → out/<name>.mp4

/video-revoice     (optional)
   → uploads to Descript, applies acronym rules
   → you open the Descript URL, Overdub with your cloned voice, publish
   → Claude pulls the finished mp4 back
   → out/<name>_myvoice.mp4
```

## Two content shapes supported

**Live web app** — the raw-CDP recorder attaches to your logged-in Chrome (started once with the included `start_chrome.sh`, which launches Chrome on debug port 9333). Example spec: `templates/central_ntp_profile.json`.

**CLI / terminal** — paste your SecureCRT session log into a spec; the simulated terminal page renders the commands typewriter-style and the output as a fast dump, same as a real session. Example spec: `templates/cli_show_command.json`.

## Behind the scenes (methodology)

- **Raw CDP over websocket** — not Playwright. We hit Chrome's DevTools Protocol directly via `websocket-client`, so Chrome version bumps don't break the recorder. See `scripts/cdp_core.py`.
- **Screencast capture** — Chrome emits JPEG frames via `Page.startScreencast`; we ack each one from the reader thread via `fire()` (not `send()`) to avoid a deadlock.
- **Overlay** — an injected cursor + ring + tick element gives each frame a visual change, so Chrome's "only composite on change" screencast still emits at a steady rate.
- **Narration** — `scripts/narration.py` wraps `say -v "Zoe (Premium)"` with `[[slnc N]]` pauses that correspond to the UI's slow transitions (panel slide-in, sub-panel open/close). We detect the actual silence boundaries in the resulting .m4a with `ffmpeg silencedetect` and use those as action anchors — so if your narration grows or shrinks by a word, the clicks still land in the right place.
- **Descript revoice** — upload via the Descript MCP server, prompt the Agent Underlord to normalize acronyms (`NTP` → `N-T-P`, `MAC` → `Mac`, etc. — rules in `scripts/narration.py`), you revoice in-app, Claude pulls the HLS stream and muxes to mp4.
- **FIX table** — `scripts/narration.py` keeps a regex table that reverses the Descript-script spellings back to normal for the YouTube SRT (so "N-T-P" in the voice script shows as "NTP" in the captions).

## Guardrails

- Nothing writes outside your project folder or `~/.config/tme-video/`
- No telemetry, no outbound calls from the plugin itself
- All network calls honor `HTTPS_PROXY` / `HTTP_PROXY` env vars
- No `sudo` anywhere
- The Descript MCP auth happens through Claude Code's standard `/mcp` flow — no secrets stored by the plugin

## What's NOT in v0.0.1 (coming later)

- Windows / Linux support
- Series polish (consistent intro/end cards, watermark, thumbnails) — use the scripts in VALID8-video-poc for now
- The Higgsfield / Ainsley narration option
- Automatic conversational spec editing (for now, you edit the JSON)
- Templates beyond the two starters

## Troubleshooting

| Symptom | Fix |
|---|---|
| `/video-bootstrap` says "Chrome not found" | Install Chrome Stable (`brew install --cask google-chrome`) or add Chrome to your Applications folder |
| `/video-bootstrap` says "Zoe Premium not installed" | System Settings → Accessibility → Spoken Content → System Voice → Manage Voices → English (United Kingdom) → Zoe Premium (download, ~500 MB) |
| `/video-record` hangs for ~30s then times out | Your Chrome debug session isn't running. Run `./start_chrome.sh` in a separate terminal, log in, then retry |
| Recording captures only a frame or two | The Chrome tab is minimized or behind another window. Keep it visible during recording — Chrome throttles composition on hidden tabs |
| `/video-revoice` fails at upload | The Descript MCP server isn't connected. In Claude Code, run `/mcp` and authorize Descript |
| `pip install` fails with connection errors | Set `HTTPS_PROXY` in your shell and retry `/video-bootstrap` |

## License

MIT — see [LICENSE](./LICENSE).
