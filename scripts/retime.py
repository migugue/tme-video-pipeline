"""Re-sync a finished recording to a revoiced narration, without recording again.

Usage:
    python retime.py <spec.json> <draft.mp4> <revoiced.mp4> <out.mp4>

  draft.mp4     what record_live.py / record_terminal.py produced (picture + Mac voice)
  revoiced.mp4  the same video pulled back from Descript with the new voice

The new voice speaks each sentence at its own pace, so the clicks drift away from
the words. This cuts both files into one piece per SENTENCE of the spec's narration
and plays each sentence's footage under that sentence's new audio:

  - footage longer than the new sentence -> its idle tail is trimmed, but never before
    the on-screen activity in that piece has finished (the audio waits instead)
  - footage shorter than the new sentence -> its last frame is held

Sentences are found in the revoiced audio as the longest pauses, which is why the
Descript script needs a line break after every sentence. The script prints the table
it worked from; if the sentence count is off, it stops rather than guess.

Output: <out.mp4> and a sentence-level <out>.srt
"""
import json
import os
import re
import subprocess
import sys
import tempfile

import imageio_ffmpeg

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from narration import build_m4a, audio_duration, fix_srt, DEFAULT_VOICE

FF = imageio_ffmpeg.get_ffmpeg_exe()
PREROLL = 0.15   # cut this far ahead of the first word so its onset is never clipped
SETTLE = 0.5     # keep this much footage after the last on-screen movement in a piece
MIN_GAP = 0.25   # shortest pause considered when looking for sentence breaks


def duration(path):
    return audio_duration(path)


def silences(path, noise_db=-38, min_d=MIN_GAP):
    out = subprocess.run([FF, '-hide_banner', '-i', path, '-vn', '-af',
                          f'silencedetect=noise={noise_db}dB:d={min_d}', '-f', 'null', '-'],
                         capture_output=True, text=True).stderr
    st = [float(x) for x in re.findall(r'silence_start: ([\d.]+)', out)]
    en = [float(x) for x in re.findall(r'silence_end: ([\d.]+)', out)]
    return list(zip(st, en))


def freezes(path):
    """(start, end) of stretches where the picture doesn't change."""
    out = subprocess.run([FF, '-hide_banner', '-i', path, '-vf', 'freezedetect=n=0.0005:d=0.4',
                          '-map', '0:v', '-f', 'null', '-'], capture_output=True, text=True).stderr
    st = [float(x) for x in re.findall(r'freeze_start: ([\d.]+)', out)]
    en = [float(x) for x in re.findall(r'freeze_end: ([\d.]+)', out)]
    return list(zip(st, en + [1e9] * (len(st) - len(en))))


def sentence_offsets(script):
    """Character offset where each sentence of the narration starts ([[slnc]] markers
    between two sentences stay with the earlier one)."""
    offs = [0]
    for m in re.finditer(r'[.!?]["\')]?\s+(?:\[\[slnc \d+\]\]\s*)*(?=\S)', script):
        offs.append(m.end())
    return offs


def draft_starts(spec, draft):
    """When each sentence starts in the draft: render the narration up to that sentence
    with the same voice and measure it, then snap to the real pause in the draft audio."""
    script, voice = spec['narration'], spec.get('voice', DEFAULT_VOICE)
    # The draft may have been recorded before the spec's narration was respelled for another
    # voice; the recorder keeps the text it actually spoke next to its build files.
    name = spec.get('name') or ''
    spoken = os.path.join(os.getcwd(), 'build', name, 'draft_narration.txt')
    if os.path.exists(spoken):
        was = open(spoken).read()
        if len(sentence_offsets(was)) == len(sentence_offsets(script)):
            script = was
    ends = [e for _, e in silences(draft)]
    starts = [0.0]
    with tempfile.TemporaryDirectory() as tmp:
        for off in sentence_offsets(script)[1:]:
            t = audio_duration(build_m4a(script[:off], os.path.join(tmp, 'p.m4a'), voice=voice))
            near = min(ends, key=lambda e: abs(e - t), default=t)
            starts.append(near if abs(near - t) < 0.7 else t)
    return starts


def revoiced_starts(path, n):
    """Sentence starts in the revoiced audio = ends of its n-1 longest pauses."""
    total = duration(path)
    inner = [(s, e) for s, e in silences(path) if s > 0.2 and e < total - 0.2]
    if len(inner) < n - 1:
        raise SystemExit(f'found only {len(inner)} pauses in {path} but the narration has {n} sentences. '
                         'Add a line break after every sentence in Descript, regenerate, and publish again.')
    picked = sorted(sorted(inner, key=lambda p: p[1] - p[0], reverse=True)[:n - 1])
    rest = sorted(set(inner) - set(picked), key=lambda p: p[1] - p[0], reverse=True)
    if rest and picked and (rest[0][1] - rest[0][0]) > 0.8 * min(e - s for s, e in picked):
        print(f'  ! pause at {rest[0][0]:.1f}s is nearly as long as a sentence break - check the table below')
    return [0.0] + [e for _, e in picked]


def srt_time(t):
    ms = int(round(t * 1000))
    return f'{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}'


def main(spec_path, draft, revoiced, dst, starts_json=None):
    spec = json.load(open(spec_path))
    script = spec['narration']
    offs = sentence_offsets(script)
    texts = [re.sub(r'\s+', ' ', re.sub(r'\[\[slnc \d+\]\]', ' ', script[a:b])).strip()
             for a, b in zip(offs, offs[1:] + [len(script)])]
    n = len(texts)

    d_total, r_total = duration(draft), duration(revoiced)
    d = [max(0.0, t - PREROLL) if i else 0.0 for i, t in enumerate(draft_starts(spec, draft))]
    # starts_json: exact sentence starts, when the caller rendered the audio itself and knows them
    r_raw = json.load(open(starts_json)) if starts_json else revoiced_starts(revoiced, n)
    if len(r_raw) != n:
        raise SystemExit(f'{starts_json} lists {len(r_raw)} sentence starts but the narration has {n} sentences')
    r = [max(0.0, t - PREROLL) if i else 0.0 for i, t in enumerate(r_raw)]
    d_end, r_end = d[1:] + [d_total], r[1:] + [r_total]
    fr = freezes(draft)

    v, a, new_starts, t = [], [], [], 0.0
    print(f'{n} sentences   draft {d_total:.1f}s   revoiced {r_total:.1f}s')
    for i in range(n):
        have, need = d_end[i] - d[i], r_end[i] - r[i]
        # last moment anything moves in this piece = start of the freeze that runs to its end
        active = have
        for fs, fe in fr:
            if d[i] < fs < d_end[i] and fe >= d_end[i] - 0.05:
                active = fs - d[i]
                break
        keep = min(have, max(need, active + SETTLE))
        hold = max(0.0, need - keep)
        length = keep + hold
        pad = f',tpad=stop_mode=clone:stop_duration={hold:.3f}' if hold > 0.01 else ''
        v.append(f'[0:v]trim={d[i]:.3f}:{d[i] + keep:.3f},setpts=PTS-STARTPTS,fps=30{pad},'
                 f'trim=0:{length:.3f},setpts=PTS-STARTPTS[v{i}]')
        a.append(f'[1:a]atrim={r[i]:.3f}:{r_end[i]:.3f},asetpts=PTS-STARTPTS,aresample=48000,'
                 f'aformat=channel_layouts=stereo,apad=whole_dur={length:.3f},atrim=0:{length:.3f}[a{i}]')
        new_starts.append((t + (PREROLL if i else 0.0), t + need))
        note = f'+ hold {hold:.1f}s' if hold > 0.01 else (f'voice waits {keep - need:.1f}s' if keep - need > 0.05 else '')
        print(f'  {i + 1:2}. footage {have:5.1f}s (moving {active:4.1f}s)  voice {need:5.1f}s  -> {length:5.1f}s {note:16} {texts[i][:46]}')
        t += length

    graph = ';'.join(v + a) + ';' + ''.join(f'[v{i}][a{i}]' for i in range(n)) + f'concat=n={n}:v=1:a=1[vout][aout]'
    subprocess.run([FF, '-y', '-loglevel', 'error', '-i', draft, '-i', revoiced, '-filter_complex', graph,
                    '-map', '[vout]', '-map', '[aout]', '-c:v', 'libx264', '-preset', 'medium', '-crf', '20',
                    '-pix_fmt', 'yuv420p', '-r', '30', '-c:a', 'aac', '-b:a', '160k',
                    '-movflags', '+faststart', dst], check=True)

    srt = os.path.splitext(dst)[0] + '.srt'
    with open(srt, 'w') as f:
        for i, ((s, e), txt) in enumerate(zip(new_starts, texts), 1):
            f.write(f'{i}\n{srt_time(s)} --> {srt_time(e)}\n{fix_srt(txt)}\n\n')
    print(f'wrote {dst} ({t:.1f} s)')
    print(f'wrote {srt}')


if __name__ == '__main__':
    if len(sys.argv) not in (5, 6):
        sys.stderr.write('usage: retime.py <spec.json> <draft.mp4> <revoiced.mp4|.wav> <out.mp4> [sentence_starts.json]\n')
        sys.exit(2)
    main(*sys.argv[1:6])
