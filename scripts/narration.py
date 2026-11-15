"""macOS `say` narration with [[slnc N]] pauses, plus the FIX table that reverses
Descript-script spellings back to normal for the YouTube SRT.

Called by the recorder scripts via `build_m4a(script, out_m4a)` and by the
Descript round-trip via `fix_srt(text)`.
"""
import os
import re
import shlex
import subprocess
import sys

import imageio_ffmpeg

FF = imageio_ffmpeg.get_ffmpeg_exe()

# The default narration voice. Zoe Premium is a UK English voice, close to
# Descript's Ainsley preset for consistency across drafts and finals. Overridable
# per-project in ~/.config/tme-video/tme-video.toml under [narration].voice.
DEFAULT_VOICE = 'Zoe (Premium)'
DEFAULT_RATE = 180  # words per minute


# ------------------------------------------------------------------
# Descript-script spellings (apply to the Descript transcript, not the YouTube SRT).
# When you add a rule here, also add its reverse to FIX below.
# ------------------------------------------------------------------
DESCRIPT_SPELLINGS = {
    # Acronyms that Miguel's cloned voice reads wrong without hints:
    'NTP':    'N-T-P',
    'AOS':    'A-O-S',       # followed by a space + 'eight' or 'ten' in context
    'WLAN':   'double U LAN',
    'SSID':   'S-S-I-D',
    'VLAN':   'Vee Lan',     # said as a word, not spelled out
    'VLANs':  'Vee Lans',
    'VRRP':   'V-R-R-P',
    'DNS':    'D-N-S',
    'IP':     'I-P',
    'CLI':    'C-L-I',
    'API':    'A-P-I',
    'PLM':    'P-L-M',
    'DDG':    'D-D-G',
    'UDG':    'U-D-G',
    'CSV':    'C-S-V',
    'DFS':    'D-F-S',
    'JSON':   'Jay-Son',
    # Plurals that would otherwise come out as "A P S":
    'APs':    "A-P's",
    'MDs':    "M-D's",
    'APIs':   "A-P-I's",
    # Words/names that need word-reading, not letter-reading:
    'CAP':    'Cap',      # AOS-8 forwarding mode
    'MAC':    'Mac',      # as in "MAC address"
    'OWL':    'Owl',
    'BAR':    'Bar',
    # Brand quirks:
    'VALID8': 'validate',
}


# ------------------------------------------------------------------
# FIX table: reverses the Descript-script spellings so the YouTube SRT is readable.
# Each entry is (regex, replacement-or-callable). Order matters: longer patterns first.
# ------------------------------------------------------------------
FIX = [
    (r"\b[Vv]ee[ -][Ll]ans\b", "VLANs"), (r"\b[Vv]ee[ -][Ll]an\b", "VLAN"),
    (r"\bV-L-A-N's\b", "VLANs"),
    (r"\bValidate's\b", "VALID8's"), (r"\bValidate\b", "VALID8"),
    (r"\bA-P-I's\b", "APIs"), (r"\bA-P-Is\b", "APIs"), (r"\bA-P-I\b", "API"),
    (r"\bP-L-M\b", "PLM"), (r"\bD-D-G\b", "DDG"), (r"\bU-D-G\b", "UDG"),
    (r"\bC-S-V\b", "CSV"), (r"\bD-F-S\b", "DFS"),
    (r"\bA-P's\b", "APs"), (r"\bA-Ps\b", "APs"), (r"\bA-P\b", "AP"),
    (r"\bM-D's\b", "MDs"), (r"\bM-Ds\b", "MDs"), (r"\bM-D\b", "MD"),
    (r"\bAOS ?8\b", "AOS-8"), (r"\bAOS8\b", "AOS-8"),
    (r"\bAOS ?10\b", "AOS-10"), (r"\bAOS10\b", "AOS-10"),
    (r"\bAOS eight\b", "AOS-8"), (r"\bAOS ten\b", "AOS-10"),
    (r"\bAOS-8 Cap\b", "AOS-8 CAP"), (r"\bAOS-10 Cap\b", "AOS-10 CAP"),
    (r"\bJay-Son\b", "JSON"), (r"\bJay Son\b", "JSON"), (r"\bJayson\b", "JSON"),
    (r"\bdouble U LANs?\b", lambda m: m.group(0).replace('double U LAN', 'WLAN')),
    (r"\bW LAN\b", "WLAN"), (r"\bW-L-A-N\b", "WLAN"),
    (r"\bS-S-I-D\b", "SSID"), (r"\bV-R-R-P\b", "VRRP"), (r"\bV-L-A-N\b", "VLAN"),
    (r"\bN-T-P\b", "NTP"), (r"\bD-N-S\b", "DNS"), (r"\bI-P\b", "IP"),
    (r"\bC-L-I\b", "CLI"),
    (r"\b[Mm]ac address(es)?\b", lambda m: "MAC address" + (m.group(1) or "")),
]


def fix_srt(text):
    """Apply the FIX table to normalize letter-spaced acronyms back to plain form."""
    for pat, repl in FIX:
        text = re.sub(pat, repl, text)
    return text


def _run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        sys.stderr.write('[narration] FAILED: ' + ' '.join(shlex.quote(a) for a in cmd) + '\n')
        sys.stderr.write(r.stderr[-1500:] + '\n')
        raise SystemExit(1)
    return r


def build_m4a(script_text, out_m4a, voice=None, rate=None):
    """Render a narration script to .m4a. `script_text` may contain [[slnc N]] pauses."""
    voice = voice or DEFAULT_VOICE
    rate = rate or DEFAULT_RATE
    # `say` writes AIFF natively; convert to AAC-in-MP4 so ffmpeg mux stays clean.
    aiff = out_m4a[:-4] + '.aiff' if out_m4a.lower().endswith('.m4a') else out_m4a + '.aiff'
    _run(['/usr/bin/say', '-v', voice, '-r', str(rate), '-o', aiff, script_text])
    _run([FF, '-y', '-loglevel', 'error', '-i', aiff, '-c:a', 'aac', '-b:a', '192k', out_m4a])
    try:
        os.remove(aiff)
    except OSError:
        pass
    return out_m4a


def audio_duration(path):
    r = subprocess.run([FF, '-i', path], capture_output=True, text=True)
    for line in r.stderr.splitlines():
        if 'Duration:' in line:
            h, m, s = line.split('Duration:')[1].split(',')[0].strip().split(':')
            return int(h) * 3600 + int(m) * 60 + float(s)
    raise RuntimeError(f'cannot probe audio duration of {path}')


def silence_boundaries(path, noise_db=-25.0, min_duration=0.25):
    """Return a list of (silence_start, silence_end) tuples detected in `path`.

    Used by the recorder to anchor UI actions to the natural pauses in the narration.
    """
    r = subprocess.run([FF, '-i', path, '-af',
                        f'silencedetect=noise={noise_db}dB:d={min_duration}',
                        '-f', 'null', '-'], capture_output=True, text=True)
    starts, ends = [], []
    for line in r.stderr.splitlines():
        if 'silence_start' in line:
            starts.append(float(line.split('silence_start:')[1].strip()))
        elif 'silence_end' in line:
            ends.append(float(line.split('silence_end:')[1].split('|')[0].strip()))
    return list(zip(starts, ends))
