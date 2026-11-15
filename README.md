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
- Zoe Premium macOS voice — open **System Settings**, search `voice`, click **Spoken Content** in the results, open the **System Voice** dropdown → the bottom option (**Manage Voices…**, **Customize…**, or **Download More Voices…** depending on your macOS version) → expand **English (United Kingdom)** → check **Zoe (Premium)** → OK. Verify with `say -v '?' | grep -i Zoe`
- A Descript account, if you want to use `/video-revoice` (you pick the AI voice inside Descript — your own cloned voice or a stock speaker)

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
4. Ask whether you'll use Descript to generate an AI voice or just the Mac system voice
5. Save your preferences to `~/.config/tme-video/tme-video.toml`
6. Record a 10-second hello-world demo

## Daily workflow

```
/video-new  "Describe the video you want + give me one of: URL, PDF, screenshot, or typed steps"
   → Claude asks for the instructions in one of the four accepted forms,
     confirms what it understood, writes specs/<name>.json

/video-record
   → raw-CDP captures your Chrome, Zoe narrates
   → out/<name>.mp4

/video-revoice     (optional)
   → uploads to Descript, applies acronym rules
   → you open the Descript URL, put each sentence on its own line,
     regenerate the narration in the AI voice you choose, publish
   → Claude pulls it back and re-syncs the clicks to the new voice
   → out/<name>_myvoice.mp4
```

## Spec authoring: ask, don't assume

`/video-new` deliberately refuses to draft a spec from Claude's training knowledge of Central / UXI / EdgeConnect / any product. Give it one of four inputs:

1. **URL** to the page the recording starts at — the recorder opens there, but the clicks still have to come from you
2. **PDF** export of a VSG or field-guide page — Claude reads it for the exact steps
3. **Screenshot** of the UI with steps marked or described — Claude describes what it sees back to you before drafting
4. **Typed instructions** — "click Config, then Library, then System card, then NTP Server..." — Claude parses literally

Claude confirms what it understood before writing the JSON. That round trip is the guardrail that keeps the plugin honest for tools Claude has never seen (your own internal apps, new product UIs, etc.).

## Executing specs without Claude Code

Spec execution is a **local-only** pipeline — Python + Chrome CDP + ffmpeg + macOS `say`. No outbound traffic beyond the loopback to Chrome's debug port. If the laptop's security stack (Zscaler DLP, corporate proxy, etc.) blocks Claude Code itself from reaching `api.anthropic.com`, the TME can still **run** pre-authored specs standalone:

```bash
# one time per shell session — find the current install path:
PLUGIN=$(ls -d ~/.claude/plugins/cache/migugue-plugins/tme-video-pipeline/*/ | sort -V | tail -1)

# live Chrome recording:
.venv/bin/python "$PLUGIN/scripts/record_live.py" specs/<name>.json

# CLI / simulated terminal recording:
.venv/bin/python "$PLUGIN/scripts/record_terminal.py" specs/<name>.json
```

This is the pilot-friendly workflow when some TMEs are on Claude-Code-allowed machines and others aren't:

1. A TME on a non-Zscaler machine (personal Mac, or HPE laptop with an Anthropic-API whitelist exception) uses `/video-new` to author specs and commits them to the shared repo.
2. Other TMEs `git pull` the repo and run `scripts/record_live.py` directly from the terminal. No Claude Code involvement, no API traffic, no DLP trigger.
3. Everyone revoices in Descript the same way.

`/video-revoice` does need Claude Code (it drives the Descript MCP tools), but once a spec exists on disk, you can always shell out to the recorder to produce the mp4 even if the chat layer is blocked.

## Two content shapes supported

**Live web app** — the raw-CDP recorder attaches to your logged-in Chrome (started once with the included `start_chrome.sh`, which launches Chrome on debug port 9333). Example spec: `templates/central_ntp_profile.json`.

**CLI / terminal** — paste your SecureCRT session log into a spec; the simulated terminal page renders the commands typewriter-style and the output as a fast dump, same as a real session. Example spec: `templates/cli_show_command.json`.

## Behind the scenes (methodology)

- **Raw CDP over websocket** — not Playwright. We hit Chrome's DevTools Protocol directly via `websocket-client`, so Chrome version bumps don't break the recorder. See `scripts/cdp_core.py`.
- **Screencast capture** — Chrome emits JPEG frames via `Page.startScreencast`; we ack each one from the reader thread via `fire()` (not `send()`) to avoid a deadlock.
- **Overlay** — an injected cursor + ring + tick element gives each frame a visual change, so Chrome's "only composite on change" screencast still emits at a steady rate.
- **Narration** — `scripts/narration.py` wraps `say -v "Zoe (Premium)"` with `[[slnc N]]` pauses that correspond to the UI's slow transitions (panel slide-in, sub-panel open/close). We detect the actual silence boundaries in the resulting .m4a with `ffmpeg silencedetect` and use those as action anchors — so if your narration grows or shrinks by a word, the clicks still land in the right place.
- **Descript revoice** — upload via the Descript MCP server, prompt the Agent Underlord to normalize acronyms (`NTP` → `N-T-P`, `MAC` → `Mac`, etc. — rules in `scripts/narration.py`), you revoice in-app (one sentence per line), Claude pulls the HLS stream, then `scripts/retime.py` fits each sentence's footage to the new voice — trimming idle tails or holding the last frame — so no second take is needed.
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
| `/video-bootstrap` says "Zoe Premium not installed" | Open **System Settings**, search `voice`, pick **Spoken Content**, open the **System Voice** dropdown, click the bottom option (**Manage Voices…** / **Customize…** / **Download More Voices…**), expand **English (United Kingdom)**, check **Zoe (Premium)** → OK. macOS has renamed this dialog across releases; the search-then-dropdown recipe is version-resilient |
| `/video-record` hangs for ~30s then times out | Your Chrome debug session isn't running. Run `./start_chrome.sh` in a separate terminal, log in, then retry |
| Recording captures only a frame or two | The Chrome tab is minimized or behind another window. Keep it visible during recording — Chrome throttles composition on hidden tabs |
| `/video-revoice` fails at upload | The Descript MCP server isn't connected. In Claude Code, run `/mcp` and authorize Descript |
| `pip install` fails with connection errors | Set `HTTPS_PROXY` in your shell and retry `/video-bootstrap` |
| Zscaler (or similar DLP) blocks "SOURCE CODE upload" when Claude Code runs | Claude Code sends conversation context to Anthropic's API and the laptop's DLP classifies it as source-code upload. Get `api.anthropic.com` whitelisted by IT, or author specs on an unblocked machine and execute standalone (see "Executing specs without Claude Code" above) |
| Recording captured, but the name typed at 2× speed was the problem | Known: setting `text` on both `keyDown` and `char` key events inserts twice. The recorder dispatches only `char` with text — if you see doubled characters, you're on an old version; re-install |

## License

MIT — see [LICENSE](./LICENSE).
