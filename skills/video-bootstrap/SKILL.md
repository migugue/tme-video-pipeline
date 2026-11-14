---
name: video-bootstrap
description: First-time setup for tme-video-pipeline — check deps, install Python requirements into a project venv, save user preferences, and record a hello-world smoke test. Run once per machine, or re-run whenever the environment check needs to be re-verified.
---

# video-bootstrap

Guide the user through first-time setup of the tme-video-pipeline plugin. Do NOT assume anything about their environment — check everything explicitly and report in a readable summary.

## Checks to run, in order

Perform these in parallel where possible (environment probes), then sequential for the installs.

### Environment probes (parallel)

1. **Chrome Stable**: check that `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome` exists. Report found/missing.
2. **Python 3.11+**: `python3 --version`. Require 3.11 or newer. Report the version you found.
3. **Zoe Premium voice**: `say -v '?' | grep -i 'Zoe'`. If the match includes `(Premium)` or the voice line reads as premium, mark installed; otherwise ask the user to download it via System Settings → Accessibility → Spoken Content → System Voice → Manage Voices → English (United Kingdom) → Zoe Premium.
4. **Descript MCP server reachable**: list available MCP tools. If `mcp__*__import_media` is present, mark connected; otherwise tell the user to run `/mcp` and authorize Descript, then rerun this bootstrap.

### Python dependencies

Create a project venv (never global, never sudo):
```bash
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r $CLAUDE_PLUGIN_ROOT/requirements.txt
```

If `HTTPS_PROXY` is set in the environment, mention that pip will use it. If the install fails with a network error, surface the exact error line and suggest the user try again after setting `HTTPS_PROXY`.

### Preferences file

Ask the user:
1. Display name of their cloned Descript voice (e.g., "Miguel Deeper Voice"). Skip if they don't plan to use `/video-revoice`.
2. Preferred narration voice for drafts. Default: `Zoe (Premium)`. Offer no other options unless they ask.

Write to `~/.config/tme-video/tme-video.toml` (create the directory if missing):
```toml
[narration]
voice = "Zoe (Premium)"

[descript]
cloned_voice_name = "Miguel Deeper Voice"

[chrome]
cdp_port = 9333
profile_dir = "~/.tme-chrome-profile"
```

Do not store secrets here. Descript / Higgsfield auth is handled by their MCP servers.

### Hello-world smoke test

Only if every environment probe passed, offer to record a 5-second demo:

> I'll open a fresh Chrome tab at https://example.com, say "Hello from your TME video pipeline", and produce `out/hello.mp4`. This spends zero credits. Run the demo? (y/n)

On yes:
1. Make sure `.venv/` exists in cwd. If not, re-run the dep install step.
2. Launch Chrome via `$CLAUDE_PLUGIN_ROOT/scripts/start_chrome.sh` in a background process, capture the stdout, wait 3 seconds for it to come up.
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

## Reporting the result

End with a crisp summary — what's ready, what's not, and the single next step. Example:

> Setup complete.
>   ✓ Chrome Stable
>   ✓ Python 3.14 with the project venv at .venv/
>   ✓ Zoe Premium voice
>   ✓ Descript MCP connected (voice: Miguel Deeper Voice)
>   ✓ hello.mp4 rendered (out/hello.mp4)
>
> Next: `/video-new` to script your first real recording.

If anything failed, say exactly what and give the fix. Do not proceed to the smoke test with a partial environment.

## Important

- No sudo. No global installs. Everything in the project `.venv/`.
- Respect `HTTPS_PROXY` / `HTTP_PROXY` env vars — just pass them through, don't strip them.
- If the user is on a work laptop with network restrictions, failures will be network-shaped — surface the exact URL that was unreachable so they can get it whitelisted.
- Never ask the user for a Descript or Higgsfield API key directly. That's what the MCP servers handle.
