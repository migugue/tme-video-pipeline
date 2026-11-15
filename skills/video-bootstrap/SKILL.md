---
name: video-bootstrap
description: First-time setup for tme-video-pipeline — check deps, install Python requirements into a project venv, save user preferences, and record a hello-world smoke test. Run once per machine, or re-run whenever the environment check needs to be re-verified.
---

# video-bootstrap

Guide the user through first-time setup of the tme-video-pipeline plugin. Do NOT assume anything about their environment — check everything explicitly and report in a readable summary.

## Required vs. optional

Checks fall into two classes:

- **Required** — if any of these fail, the recording pipeline doesn't work. Block the smoke test; tell the user what to fix.
- **Optional** — needed only for `/video-revoice` (the Descript AI-voice path). A failure here is informational — the smoke test, `/video-new`, and `/video-record` all still work on the zero-cost default (Mac `say` + raw-CDP).

| Check | Class |
|---|---|
| Chrome Stable | Required |
| Python 3.11+ | Required |
| Zoe Premium voice | Required (default narration) |
| Descript MCP connected | **Optional** — only for `/video-revoice` |

## Checks to run, in order

### 1. Environment probes (parallel)

1. **Chrome Stable**: check `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome` exists.
2. **Python 3.11+**: `python3 --version`. If < 3.11, look for `python3.11`, `python3.12`, `python3.13`, `python3.14` on PATH or at `/opt/homebrew/bin/python3.11` (Apple Silicon) / `/usr/local/bin/python3.11` (Intel). Use the first one you find.
3. **Zoe Premium voice**: `say -v '?' | grep -i 'Zoe.*Premium'`. If no match, prompt the user to install it — see "Installing the Zoe Premium voice" below.
4. **Descript MCP server (optional)**: list available MCP tools. If `mcp__*__import_media` is present, mark connected; otherwise note it as optional and proceed.

### 2. Python dependencies

Create a project venv (never global, never sudo):
```bash
<python-exe> -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r $CLAUDE_PLUGIN_ROOT/requirements.txt
```

If `HTTPS_PROXY` is set, mention pip will use it. If pip fails with a network error, surface the exact error line and suggest the user try again after setting `HTTPS_PROXY`.

### 3. Preferences file

Ask the user:
1. **Narration: will you use Descript to generate an AI voice, or just the Mac system voice?** Record the answer as `use_descript`. Do NOT ask for a voice name — they pick the voice inside Descript when they get there, and it's different for everyone.
2. **Preferred draft narration voice.** Default: `Zoe (Premium)`. Don't offer other options unless they ask.

Write to `~/.config/tme-video/tme-video.toml` (create the directory if missing):
```toml
[narration]
voice = "Zoe (Premium)"

[descript]
use_descript = false     # true if they said they will generate an AI voice in Descript

[chrome]
cdp_port = 9333
profile_dir = "~/.tme-chrome-profile"
```

Do not store secrets here. Descript auth is handled by the MCP server, not by this file.

### 4. Hello-world smoke test

**Run this whenever every REQUIRED check passed, regardless of whether Descript is configured.** Do not skip the smoke test just because the user opted out of Descript or the Descript MCP isn't connected — those are optional and have nothing to do with the recording pipeline.

Offer:

> I'll open a fresh Chrome tab at https://example.com, say "Hello from your TME video pipeline", and produce `out/hello.mp4`. This spends zero credits. Run the demo? (y/n)

On yes:
1. Make sure `.venv/` exists in cwd. If not, re-run step 2.
2. Launch Chrome via `$CLAUDE_PLUGIN_ROOT/scripts/start_chrome.sh` in a background process, wait 3 seconds for the debug port to come up (poll `curl -sS http://127.0.0.1:9333/json/version`).
3. Write a minimal spec to `specs/hello.json`:
   ```json
   {
     "name": "hello",
     "tab_match": "example.com",
     "start_url": "https://example.com",
     "narration": "Hello from your T-M-E video pipeline. [[slnc 500]] This recording is made with the Zoe Premium voice and the raw C-D-P screencast — zero cost, no accounts needed.",
     "actions": [
       {"at": 2.0, "kind": "point", "text": "Example Domain", "optional": true}
     ]
   }
   ```
4. Run `.venv/bin/python $CLAUDE_PLUGIN_ROOT/scripts/record_live.py specs/hello.json`.
5. Confirm `out/hello.mp4` exists and is non-empty. Tell the user where it is.

## Installing the Zoe Premium voice

macOS has shuffled the voice download UI across releases, so don't hard-code one path. Give the user a resilient recipe:

1. Open **System Settings** (macOS 13+) or **System Preferences** (macOS 12 and earlier).
2. In the search box at the top of the Settings window, type **`voice`**. Pick the result that lands you in **Spoken Content** (usually under Accessibility).
3. In Spoken Content, find the **System Voice** dropdown. Click the dropdown, then the option at the bottom — labeled **Manage Voices…**, **Customize…**, or **Download More Voices…** depending on your macOS version. (All three lead to the same voice catalog.)
4. Expand **English (United Kingdom)** and check **Zoe (Premium)**. Click **OK** or **Done**. macOS downloads the voice (~500 MB).
5. When the download finishes, verify in Terminal:
   ```bash
   say -v '?' | grep -i Zoe
   ```
   You should see `Zoe` and/or `Zoe (Premium)` with locale `en_GB`.

If `say -v '?'` already shows `Zoe` without `(Premium)`, you have the base voice only — the Premium download is a separate, higher-quality variant and it's what the plugin defaults to.

## Reporting the result

End with a crisp summary — what's ready, what's not, what runs today, and the single next step. Example:

> Setup complete.
>   ✓ Chrome Stable
>   ✓ Python 3.14 with the project venv at .venv/
>   ✓ Zoe Premium voice
>   ✓ hello.mp4 rendered → ~/test-v0-0-2/out/hello.mp4
>   • Descript: not configured (optional — only needed for /video-revoice)
>
> Next: `/video-new` to script your first real recording.

If a REQUIRED check failed, say exactly what and give the fix. Do NOT run the smoke test with a broken required dep. If only OPTIONAL checks failed, note them below the summary with the line "optional — only needed for …" and still run the smoke test (if the user agrees).

## Important

- No sudo. No global installs. Everything in the project `.venv/`.
- Respect `HTTPS_PROXY` / `HTTP_PROXY` env vars.
- Descript is OPTIONAL. Skipping it doesn't block the pipeline; it only disables `/video-revoice`.
- If a work-laptop DLP / proxy intercepts `pip install` or Claude Code's own API, surface the exact URL that was blocked so the user can take that to IT.
- Never ask the user for a Descript or Higgsfield API key directly. That's what the MCP servers handle.
