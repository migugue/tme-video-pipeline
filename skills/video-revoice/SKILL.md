---
name: video-revoice
description: Upload a recorded video to Descript, apply acronym spelling rules to the transcript, hand the user the Descript URL to regenerate the narration in their AI voice, pull the result back, and re-sync the picture to the new voice as out/<name>_myvoice.mp4.
---

# video-revoice

Round-trip a recorded video through Descript to replace the draft Mac narration with an AI voice the user picks in Descript, then re-sync the clicks to that voice.

## Prerequisites

- The Descript MCP server must be authorized. If `mcp__*__import_media` isn't available, tell the user to run `/mcp` and connect Descript, then come back.
- The user picks the voice themselves inside Descript (their own cloned voice or a stock AI speaker). **Never ask for the voice's name and never look one up in the config** - Descript shows it differently for every account (often just "Add a speaker"), and the plugin doesn't need it.

## Which video?

If a video name was passed, use `out/<name>.mp4`. Otherwise:
- If there's exactly one `out/*.mp4` without a `_myvoice` suffix, use it.
- Otherwise list candidates and ask.

## The round-trip

### 1. Upload to Descript

Call the Descript MCP's `import_media` tool with:
- `project_name`: `<spec name> — AI voice take`
- `add_media`: `{"<basename>.mp4": {"content_type": "video/mp4", "file_size": <bytes>, "language": "en"}}`
- `add_compositions`: `[{"name": "<spec name>", "width": <w>, "height": <h>, "fps": 30, "clips": [{"media": "<basename>.mp4"}]}]`

The width/height come from the recorded mp4 — probe with ffmpeg if you don't already have them.

### 2. PUT the file to the upload URL

The import_media response includes `upload_urls.<basename>.upload_url`. PUT the local file to it:
```bash
curl -sS -w "HTTP %{http_code}\n" -X PUT \
  -H "Content-Type: application/octet-stream" \
  --data-binary @out/<name>.mp4 \
  '<upload_url>'
```

Expect HTTP 200. Then call `wait_for_job` on the import's `job_id`.

### 3. Clean the transcript

Call `prompt_project_agent` with a prompt like:

> Clean up the transcript for AI voice generation. Apply these spellings so the generated voice reads the acronyms correctly:
> - NTP → N-T-P, AOS → A-O-S eight / A-O-S ten, CLI → C-L-I, IP → I-P
> - MAC (as in "MAC address") → Mac (reads as the word)
> - OWL → Owl, BAR → Bar
> Put a line break after every sentence, so each sentence is its own paragraph.
> Do NOT add background music. Do not change the meaning or the wording.

Only include rules relevant to the actual transcript content — don't paste the full list if the narration only uses half of them.

Wait for the job, read the agent's response. If the agent mentions dropping any words or making structural changes, surface that to the user so they can verify.

### 4. Hand over to the user

Give them the Descript project URL from the import response. Include these instructions:

> **Descript project**: <url>
>
> 1. Open it — the transcript is pre-cleaned.
> 2. Check there is a **line break after every sentence** (one sentence per paragraph). Add any that are missing — the re-sync step finds the sentences by the pauses those breaks create.
> 3. Select all → regenerate the narration with the AI voice of your choice (your cloned voice or a stock speaker).
> 4. Publish → video. Paste the share URL back here when it's done.

Then wait. Do not proceed until they give you a publish URL.

### 5. Pull the final

When they give you the publish URL (format: `https://share.descript.com/view/<id>`):

1. Scrape the share page for the HLS stream URL:
   ```bash
   curl -sSL '<share-url>' -o /tmp/share.html
   grep -oE 'og:video:url[^>]*content="[^"]*"' /tmp/share.html \
     | head -1 | sed 's/&#x3D;/=/g; s/&amp;/\&/g; s/.*content="//; s/"$//'
   ```
2. Download the HLS as mp4:
   ```bash
   .venv/bin/python -c "
   import imageio_ffmpeg, subprocess
   FF = imageio_ffmpeg.get_ffmpeg_exe()
   subprocess.run([FF, '-y', '-loglevel', 'warning', '-i', '<hls-url>',
                   '-c', 'copy', '-movflags', '+faststart',
                   'build/<name>/descript_pull.mp4'], check=True)
   "
   ```

If ffmpeg returns 404 on the first try, wait 15 seconds and retry — Descript's HLS segments can take a moment to publish.

### 6. Re-sync the picture to the new voice

The new voice paces each sentence differently, so in the raw pull the clicks no longer land on the words. Do not re-record. Run:

```bash
.venv/bin/python $CLAUDE_PLUGIN_ROOT/scripts/retime.py specs/<name>.json \
  out/<name>.mp4 build/<name>/descript_pull.mp4 out/<name>_myvoice.mp4
```

It cuts the draft footage and the new audio into one piece per sentence and fits each piece of footage to its sentence (trims an idle tail or holds the last frame; never cuts on-screen activity). It prints a per-sentence table and writes a sentence-level `out/<name>_myvoice.srt`.

If it stops because it found fewer pauses than sentences, or warns that a pause is nearly as long as a sentence break, the Descript script is missing line breaks: ask the user to add one after every sentence, regenerate, publish again, and re-run from step 5.

### 7. Deliver

Confirm `out/<name>_myvoice.mp4` exists, report its size and duration, and tell the user to watch it once for voice-to-click sync. The length usually differs a little from the draft.

## Important

- Never automate the voice generation in Descript — that's the step where the user chooses and authorizes the voice. Keep it manual.
- Never store the user's Descript publish URL anywhere. It's shared-link-only, meant for them.
- The MCP tools do NOT appear in this skill's tool allowlist by name because Descript's MCP tool names include per-install UUIDs; look for `mcp__*__import_media`, `mcp__*__prompt_project_agent`, `mcp__*__wait_for_job`, `mcp__*__get_project` dynamically.
