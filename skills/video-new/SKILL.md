---
name: video-new
description: Start a new narrated walkthrough video. Collect the TME's instructions in one of four accepted forms (URL, PDF, screenshot, or typed steps), draft a spec STRICTLY from what they provided, write it to specs/<name>.json, and offer /video-record. Never guess the workflow from training knowledge.
---

# video-new

Create a new video spec. **The TME is the source of truth for every step.** You must not invent, infer, or default to training-knowledge guesses about any product's UI — including products you think you know well (Aruba Central, UXI, EdgeConnect, VALID8, etc.). The plugin's job is to turn the TME's instructions into a runnable spec, nothing more.

## Step 1 — Collect instructions from the TME

Ask the TME which of these four forms they're providing. Keep asking until they've given at least one; don't start drafting until you have enough to work from.

1. **URL to the page the workflow starts at.** Example: `https://internal-ui.central.arubanetworks.com/...`. Use it as the spec's `start_url` and nothing more — do NOT fetch the page yourself, do NOT scrape its DOM, do NOT infer what's on it. The URL tells the recorder where to begin; it does not tell you what to click.
2. **PDF export of a VSG or field-guide page**, dropped into the chat or referenced by path. Read it for the exact steps the TME wants narrated and performed. Quote the steps back to the TME before drafting so they can correct any misreading.
3. **Screenshot(s) of the steps**, attached by the TME. Describe what you see in the image back to the TME so they can confirm you're reading the right UI; only then draft actions based on what you confirmed.
4. **Typed instructions** — the TME writes the steps in chat, e.g. "click Config in the top nav, then Library in the left nav, then System card, then NTP Server". Parse this literally; do not expand or embellish.

If the TME gives none of these, say so and ask. Do not start.

## Step 2 — Confirm what you understood

Before drafting the JSON, repeat back to the TME in plain prose:

- Where the recording starts
- The ordered steps you'll perform
- The narration framing (what the voice should be saying — are they explaining each step, or just a title card?)
- What "done" looks like (last visible state)

Let the TME correct anything before you touch the spec file. If they correct, re-confirm.

## Step 3 — Draft the spec, following the templates for STRUCTURE only

Base the spec on the right template:

- **Live Chrome recording** (any web UI the TME can log into) → copy `$CLAUDE_PLUGIN_ROOT/templates/central_ntp_profile.json` to `specs/<name>.json` and REPLACE its `narration` + `actions` with what the TME confirmed. Do not inherit any NTP-specific text.
- **CLI session** (SecureCRT, ssh, any shell) → copy `$CLAUDE_PLUGIN_ROOT/templates/cli_show_command.json` to `specs/<name>.json` and REPLACE its `narration` + `steps`. If the TME has a session log file, reference it in `print_output_from`; if they pasted output, inline it in `print_output`.

**The templates are structural patterns only** — they show how `at`/`kind`/`text` fields are shaped, how `[[slnc N]]` pauses line up with UI transitions, how the narration pacing works. The CONTENT (what to click, what to type, what to say) must come from the TME's instructions.

### Narration rules

- Use the Descript-script spellings from `$CLAUDE_PLUGIN_ROOT/scripts/narration.py` (DESCRIPT_SPELLINGS dict): "N-T-P" not "NTP", "Mac" (word) not "M-A-C", "Owl" not "O-W-L", etc. This makes the Mac draft and the cloned-voice revoice both read correctly.
- Insert `[[slnc N]]` pauses at UI transitions: 1200–1500 ms before/after any step where a panel slides in, a sub-panel opens, or a page navigates. These pauses give the recorder time to catch up without the voice outpacing the clicks.
- Target ~180 wpm. 30 s of narration ≈ 90 words.

### Action rules

- Each `actions[]` entry has `at` (seconds since screencast start), a `kind`, and kind-specific fields.
- The action should LEAD its narration cue by ~0.2 s so the voice confirms what just happened.
- Supported `kind` values are only those documented at the top of `scripts/record_live.py`: `point`, `click`, `type`, `type_into_placeholder`, `click_button_with_text`, `scroll_to_text`, `hover`, `point_selector`, `click_selector`, `wait`, `goto`. Prefer the text-based kinds; reach for `hover` / `point_selector` / `click_selector` only when the target has no button text (row-hover icons, checkbox labels, dropdown options). Do NOT invent new kinds — if the TME's step doesn't map to one of these, say so and ask them to describe it differently.

## Step 4 — Write the spec file to disk, show the path

Write `specs/<name>.json` (create `specs/` if missing). **This is non-negotiable.** Do not proceed to `/video-record` without a spec file on disk — even if the TME says "just record it now." The spec file is what makes the recording reproducible, inspectable, and shareable with colleagues who may be stuck on an air-gapped laptop and can only execute pre-authored specs (see README → "Executing specs without Claude Code").

After writing, tell the TME:

> Wrote `specs/<name>.json` (N seconds total, M actions). Open it to review, or run `/video-record` to record it.

## Step 5 — Offer the next step

Don't auto-chain into `/video-record`. The TME should look at the spec, maybe tweak timings, and run the recording when they're ready.

## Hard rules — no exceptions

- **Never infer product UI steps from training knowledge.** If the TME didn't tell you about a step, it doesn't go in the spec.
- **Never draft without a confirmation round.** Say what you understood, let the TME correct, then write.
- **Never skip writing the spec file.** No "ephemeral in-memory spec." No "I'll inline it into the record command." The file on disk is the artifact.
- **Never start without at least one of the four input forms.** URL alone is not enough to describe the clicks — ask for the steps too.
- **Customer configs never appear in demos.** If the TME's described content includes customer names, prompt them to use lab names (OWL, BAR, Owl-Bar) instead.
- **Encrypted keys / long hex strings** get blurred automatically by the overlay's `blurSecrets()` — no spec change needed, but mention it to the TME if the flow involves PSKs or RADIUS secrets.
