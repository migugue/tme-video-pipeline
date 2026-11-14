# Spec templates

Starter specs the `/video-new` skill copies from and adapts.

## central_ntp_profile.json

Live Chrome recording. Walks through `Library Profile Management → System Manage → NTP Server Manage → Create Profile → name + add server → Create`. Narration uses `[[slnc N]]` pauses at the two intermediate page loads so clicks stay in sync with the voice.

**What to change** for a different Central workflow:
- `start_url` to the right starting page
- `narration` to describe the new flow
- `actions[]` — each action's `at` is seconds since screencast start, and should lead its narration cue by ~200 ms

## cli_show_command.json

Simulated terminal recording. Types `no paging` then `show configuration node-hierarchy` and dumps the output as a fast scroll. Narration explains the hierarchy over the static tree afterwards.

**What to change** for a different CLI workflow:
- `prompt` to your device's actual prompt (e.g. `(controller-a) #`)
- `narration` to describe the new commands
- `steps[].type_cmd` entries for each command you'd type
- `print_output` for inline output, or `print_output_from: "foo.log"` to read from a file next to the spec

## Action / step kinds

See the top of `scripts/record_live.py` and `scripts/record_terminal.py` for the exhaustive list and their fields. Don't invent new kinds in a spec — add support to the recorder first.
