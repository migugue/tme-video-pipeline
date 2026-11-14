---
name: video-new
description: Start a new narrated walkthrough video. Draft a JSON spec from the user's natural-language description, let them refine it conversationally, save to specs/<name>.json so /video-record can pick it up.
---

# video-new

Create a new video spec from a natural-language description.

## What to ask

1. **What's the video about?** (one sentence)
2. **Which shape?** Live Chrome tab (Central, VALID8, any logged-in web app) or simulated terminal (CLI walkthrough from a SecureCRT session log)?
3. **For live specs**: Is the Chrome tab already open on the right page? If not, what URL should the recording start at?
4. **For terminal specs**: Do they have a captured session log file to drop in? If not, they can paste the output into the spec directly and we'll inline it.

Don't bombard — ask #1, then #2, then whichever follow-up matches #2.

## Drafting the spec

Base the spec on the right template:

- **Live**: copy `$CLAUDE_PLUGIN_ROOT/templates/central_ntp_profile.json` to `specs/<name>.json` and adapt the `narration` + `actions` to the user's request.
- **Terminal**: copy `$CLAUDE_PLUGIN_ROOT/templates/cli_show_command.json` to `specs/<name>.json` and adapt `narration` + `steps`. If they gave you a log file path, reference it in `print_output_from`. If they pasted output into chat, inline it as a `print_output` array.

### Narration guidelines (apply to every spec you draft)

- Keep the narration as one continuous `say` script with inline `[[slnc N]]` pauses at the slow transition points.
- Use the Descript-script spellings from `$CLAUDE_PLUGIN_ROOT/scripts/narration.py` (DESCRIPT_SPELLINGS dict) in the spoken text — "N-T-P" not "NTP", "Mac" not "MAC", etc. This makes the narration-to-cloned-voice revoice work without any extra cleanup.
- Target ~180 wpm pacing. For a 30-second video, that's ~90 words.
- Pauses to include:
  - 400-700 ms after an intro sentence before moving into the first action
  - 1200-1500 ms before and after any step where the UI has to finish a transition (panel slide-in, sub-panel open/close, page navigation)
  - 300 ms after a comma that introduces a sub-step ("First, type X" | "Then click Y")

### Actions guidelines (live specs)

- Each `actions[]` entry has an `at` time (seconds since screencast start), a `kind`, and kind-specific fields.
- The action should **lead** its narration cue by ~0.2 s, so the voice confirms what just happened.
- If the UI takes 1.5 s to slide a panel in, the spec needs a matching `[[slnc 1500]]` in the narration before the next action.

See the templates for a working example. Don't invent action kinds — only use the ones supported by `scripts/record_live.py`: `point`, `click`, `type`, `type_into_placeholder`, `click_button_with_text`, `scroll_to_text`, `wait`, `goto`.

### Steps guidelines (terminal specs)

- Each `steps[]` entry has an `at` time and either `type_cmd` (types a command at the prompt) or `print_output` / `print_output_from` (dumps command output).
- Terminal output "dumps" at ~40 ms/line to look like a real session; the narration explains the result in the trailing time.
- The `prompt` field is the shell prompt text — use the exact one from the user's real session (e.g. `(OWL_MCr01) *[mynode] #`).

## Save and offer the next step

Write `specs/<name>.json` (create `specs/` if missing). Then:

> Drafted `specs/<name>.json` (~N seconds total). Want to tweak anything before we record, or go straight to `/video-record`?

## Important

- Never fabricate a spec from scratch when a template fits. Templates encode the pauses and selectors that work.
- Never commit the spec for the user; show them the draft and let them say "looks good" or redirect.
- Customer configs never appear in demos. If the user's described content includes customer names, prompt them to use lab names instead (OWL, BAR, Owl-Bar, etc.).
- Encrypted keys / long hex strings get blurred automatically by the recorder's `blurSecrets()` overlay — no spec change needed.
