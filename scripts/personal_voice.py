"""Redo a recording's voiceover with a voice the `say` command can't reach - above all a
macOS Personal Voice - and re-sync the picture to it. No Descript, no second take.

Usage:
    python personal_voice.py <spec.json> <draft.mp4> <out.mp4> [voice] [rate]

  voice   "personal" (default) = your macOS Personal Voice, or part of a system voice name.
  rate    Personal Voice pace: 0.5 = its normal pace (default), 0.53 = about a third faster,
          which roughly matches the Zoe draft. Small steps - the scale is steep.

Personal Voice needs a one-time permission: System Settings > Accessibility > Personal Voice >
"Allow applications to request to use", then approve the prompt the first time this runs.

It speaks the spec's narration chunk by chunk through the macOS speech API (pv_say.swift),
rebuilds the [[slnc N]] pauses, and hands the audio plus the exact sentence start times to
retime.py, which fits each sentence's footage to the new voice.
"""
import json
import os
import re
import subprocess
import sys
import wave

import imageio_ffmpeg

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import retime

FF = imageio_ffmpeg.get_ffmpeg_exe()
RATE = 48000
SENTENCE_GAP_MS = 350   # pause after a sentence that has no [[slnc]] of its own


def main(spec_path, draft, dst, voice='personal', rate=None):
    spec = json.load(open(spec_path))
    script = spec['narration']
    name = spec.get('name') or os.path.splitext(os.path.basename(spec_path))[0]
    work = os.path.join(os.getcwd(), 'build', name, 'voice_' + re.sub(r'\W+', '_', voice))
    os.makedirs(work, exist_ok=True)

    # chunks: (sentence index, text, pause after in ms)
    offs = retime.sentence_offsets(script)
    chunks = []
    for si, (a, b) in enumerate(zip(offs, offs[1:] + [len(script)])):
        parts = re.split(r'\[\[slnc (\d+)\]\]', script[a:b])
        for k in range(0, len(parts), 2):
            text = parts[k].strip()
            pause = int(parts[k + 1]) if k + 1 < len(parts) else 0
            if text:
                chunks.append([si, text, pause])
            elif chunks:
                chunks[-1][2] += pause
        if chunks and chunks[-1][0] == si and chunks[-1][2] == 0:
            chunks[-1][2] = SENTENCE_GAP_MS

    for f in os.listdir(work):
        if f.startswith('chunk'):
            os.remove(os.path.join(work, f))
    cj = os.path.join(work, 'chunks.json')
    json.dump([c[1] for c in chunks], open(cj, 'w'))
    if voice == 'personal':
        # macOS will speak a Personal Voice but not render it to a file, so play it aloud
        # and record the Mac's own sound output, then cut that recording back into chunks.
        print('Speaking the narration aloud and recording it - keep the Mac otherwise silent...')
        r = subprocess.run(['swift', os.path.join(HERE, 'pv_speak_record.swift'), voice, cj, work] + ([str(rate)] if rate else []),
                           capture_output=True, text=True)
    else:
        r = subprocess.run(['swift', os.path.join(HERE, 'pv_say.swift'), voice, cj, work], capture_output=True, text=True)
    print(r.stdout.strip().splitlines()[0] if r.stdout.strip() else '')
    if r.returncode == 3:
        raise SystemExit('macOS refused Personal Voice access. Turn on System Settings > Accessibility > '
                         'Personal Voice > "Allow applications to request to use", approve the prompt, and run again.')
    if r.returncode == 5:
        raise SystemExit('macOS refused system-audio recording. Allow the app you run this from (VS Code, Terminal...) '
                         'under System Settings > Privacy & Security > Screen & System Audio Recording, then run again.')
    if r.returncode:
        raise SystemExit(r.stderr.strip()[-800:] or 'voice rendering failed')

    if voice == 'personal':
        marks = json.load(open(os.path.join(work, 'marks.json')))
        trim = ('silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.03,areverse,'
                'silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.06,areverse')
        for i, (s0, e0) in enumerate(marks):
            subprocess.run([FF, '-y', '-loglevel', 'error', '-ss', f'{max(0, s0 - 0.05):.3f}', '-to', f'{e0:.3f}',
                            '-i', os.path.join(work, 'playback.wav'), '-af', trim,
                            os.path.join(work, f'chunk{i:03d}.wav')], check=True)

    # stitch chunks + pauses into one track, noting where each sentence starts
    full = os.path.join(work, 'narration.wav')
    starts, t = [], 0
    with wave.open(full, 'wb') as out:
        out.setnchannels(1); out.setsampwidth(2); out.setframerate(RATE)
        for i, (si, _, pause) in enumerate(chunks):
            src = os.path.join(work, f'chunk{i:03d}.wav')
            if not os.path.exists(src):
                raise SystemExit(f'the voice produced no audio for chunk {i}: {chunks[i][1]!r}')
            pcm = subprocess.run([FF, '-loglevel', 'error', '-i', src, '-f', 's16le', '-ac', '1', '-ar', str(RATE), '-'],
                                 capture_output=True, check=True).stdout
            if len(pcm) < RATE * 2 * 0.15:
                raise SystemExit(f'chunk {i} came out silent ({chunks[i][1]!r}) - was the Mac muted through a '
                                 'device the recording cannot hear, or did something interrupt playback?')
            if len(starts) == si:
                starts.append(t / RATE)
            out.writeframes(pcm)
            silence = int(RATE * pause / 1000)
            out.writeframes(b'\x00\x00' * silence)
            t += len(pcm) // 2 + silence
    sj = os.path.join(work, 'sentence_starts.json')
    json.dump(starts, open(sj, 'w'))
    print(f'narration: {t / RATE:.1f} s, {len(starts)} sentences')
    retime.main(spec_path, draft, full, dst, sj)


if __name__ == '__main__':
    if len(sys.argv) not in (4, 5, 6):
        sys.stderr.write('usage: personal_voice.py <spec.json> <draft.mp4> <out.mp4> [voice] [rate]\n')
        sys.exit(2)
    main(*sys.argv[1:6])
