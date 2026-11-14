---
name: video-record
description: Render a video from a spec in specs/. Checks the environment, launches Chrome if needed, runs the matching recorder (record_live.py for live Chrome, record_terminal.py for simulated terminal), reports the output path.
---

# video-record

Render the video for a spec.

## Which spec?

If the user passed a spec path, use it. Otherwise:
- If there's exactly one `specs/*.json`, use it.
- If there are several, list them with their last-modified times and ask which one.
- If there are none, tell them to run `/video-new` first.

## Pre-flight checks

Run these in parallel before starting the recording:

1. **venv ready**: `.venv/bin/python` exists in cwd. If not, tell them to run `/video-bootstrap`.
2. **Chrome on debug port**: `curl -sS http://127.0.0.1:9333/json/version` returns JSON. If not:
   - Offer to launch `$CLAUDE_PLUGIN_ROOT/scripts/start_chrome.sh` in the background.
   - After launch, wait up to 10 seconds for the port to come up.
   - Tell them to log into their target app (Central, etc.) and come back.
3. **Spec validity**: parse the JSON, check required fields (`name`, `narration`, and either `tab_match` or `prompt`+`steps`).

## Running the recorder

For a live spec (has `tab_match`):
```bash
.venv/bin/python $CLAUDE_PLUGIN_ROOT/scripts/record_live.py specs/<name>.json
```

For a terminal spec (has `prompt` and `steps`):
```bash
.venv/bin/python $CLAUDE_PLUGIN_ROOT/scripts/record_terminal.py specs/<name>.json
```

## During the recording

- Terminal recordings usually complete without user intervention.
- Live recordings need the Chrome tab to stay **visible** (not minimized, not behind another window). Chrome throttles composition on hidden tabs and the screencast will starve. Remind the user once before starting.

## After it finishes

The script prints paths. Confirm the mp4 exists and show its size and duration:

> Recorded `out/<name>.mp4` (N.N seconds, X MB). Open it to review.

If they want to retake, tell them to edit `specs/<name>.json` (or describe the change and you'll edit it) and re-run `/video-record`.

If they're happy with the draft and want their own voice, next step is `/video-revoice`.

## Failure modes to catch

- **"no page tab with URL containing ..."** — the Chrome tab they need isn't open. Ask them to navigate to the right page and re-run.
- **"no frames captured"** — Chrome tab was hidden/minimized during recording. Remind them to keep it visible.
- **A `box_by_text` selector not found** — the spec's `text` field doesn't match any visible element. Open the recorder's error, tell the user which text is missing, offer to edit the spec.
- **ffmpeg errors on odd dimensions** — shouldn't happen (we pad to even), but if it does, log the ffmpeg stderr and ask for the viewport size.

## Important

- Never spend credits here — this is the zero-cost path. Higgsfield/Descript only enter in `/video-revoice`.
- Don't re-record automatically on failure. Surface the error, let the user decide.
- The `out/` and `build/` folders are per-project (cwd), not per-plugin. Everything lives next to the spec.
