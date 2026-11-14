---
name: video-revoice
description: Upload a recorded video to Descript, apply acronym spelling rules to the transcript, hand the user the Descript URL to revoice in their cloned voice, then pull the final video back as out/<name>_myvoice.mp4.
---

# video-revoice

Round-trip a recorded video through Descript to replace the draft narration with the user's own cloned voice.

## Prerequisites

- The Descript MCP server must be authorized. If `mcp__*__import_media` isn't available, tell the user to run `/mcp` and connect Descript, then come back.
- The user must have a cloned voice already set up in Descript (one-time Descript setup, outside this plugin). The display name of that voice is in `~/.config/tme-video/tme-video.toml` under `[descript].cloned_voice_name`.

## Which video?

If a video name was passed, use `out/<name>.mp4`. Otherwise:
- If there's exactly one `out/*.mp4` without a `_myvoice` suffix, use it.
- Otherwise list candidates and ask.

## The round-trip

### 1. Upload to Descript

Call the Descript MCP's `import_media` tool with:
- `project_name`: `<spec name> — cloned voice take`
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

> Clean up the transcript for voice cloning. Apply these spellings so my cloned voice reads the acronyms correctly:
> - NTP → N-T-P, AOS → A-O-S eight / A-O-S ten, CLI → C-L-I, IP → I-P
> - MAC (as in "MAC address") → Mac (reads as the word)
> - OWL → Owl, BAR → Bar
> Do NOT add background music. Keep the transcript as flowing sentences. Do not change the meaning.

Only include rules relevant to the actual transcript content — don't paste the full list if the narration only uses half of them.

Wait for the job, read the agent's response. If the agent mentions dropping any words or making structural changes, surface that to the user so they can verify.

### 4. Hand over to the user

Give them the Descript project URL from the import response. Include these instructions:

> **Descript project**: <url>
>
> 1. Open it — the transcript is pre-cleaned.
> 2. Select all → right-click → Replace with Overdub → pick **<cloned voice name>**.
> 3. Press Enter per sentence as it generates.
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
                   'out/<name>_myvoice.mp4'], check=True)
   "
   ```

If ffmpeg returns 404 on the first try, wait 15 seconds and retry — Descript's HLS segments can take a moment to publish.

### 6. Deliver

Confirm the file exists, report its size and duration, deliver it to the user. Note that Descript may have retimed the clip length to match the new narration, so the final length likely differs from the draft.

## Important

- Never automate the Overdub click in Descript — that's the step where the user explicitly authorizes using their cloned voice. Keep it manual.
- Never store the user's Descript publish URL anywhere. It's shared-link-only, meant for them.
- The MCP tools do NOT appear in this skill's tool allowlist by name because Descript's MCP tool names include per-install UUIDs; look for `mcp__*__import_media`, `mcp__*__prompt_project_agent`, `mcp__*__wait_for_job`, `mcp__*__get_project` dynamically.
