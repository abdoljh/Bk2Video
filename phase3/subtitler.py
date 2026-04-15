"""
Phase 3 — Arabic subtitle generator.

Produces an ASS (Advanced SubStation Alpha) subtitle file from parsed
script sections with known durations.

ASS is preferred over SRT because:
  - libass (used by FFmpeg) supports full Unicode bidi and Arabic shaping
  - Custom Arabic font, size, colour, outline and shadow are all specifiable
  - Bottom-centre alignment (\an2) works correctly with RTL Arabic text

The script text is split into blocks of ≤ MAX_WORDS_PER_BLOCK Arabic words,
preferring sentence boundaries.  Each block is timed proportionally to its
word count within the enclosing section.
"""

from __future__ import annotations

import re
from pathlib import Path

from .parser import ScriptSection

MAX_WORDS_PER_BLOCK = 10   # Arabic words shown per subtitle card

# ── ASS header ──────────────────────────────────────────────────────────── #
# PlayRes must match the video resolution (1280×720 default).
# The Arabic style uses Noto Naskh Arabic (installed via packages.txt),
# white text with a dark outline + soft drop shadow for readability on
# any background colour.
_ASS_HEADER = """\
[Script Info]
ScriptType: v4.00+
Collisions: Normal
PlayResX: {width}
PlayResY: {height}
Timer: 100.0000

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Arabic,Amiri,{fontsize},&H00FFFFFF,&H000000FF,&H00000000,&HA0000000,1,0,0,0,100,100,0,0,1,3,1.5,2,40,40,50,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


# ── Time formatting ──────────────────────────────────────────────────────── #

def _sec_to_ass(sec: float) -> str:
    """Convert seconds to ASS timestamp  H:MM:SS.cc"""
    sec  = max(0.0, sec)
    h    = int(sec // 3600)
    m    = int((sec % 3600) // 60)
    s    = int(sec % 60)
    cs   = int(round((sec - int(sec)) * 100))
    if cs >= 100:
        cs = 99
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


# ── Text splitting ───────────────────────────────────────────────────────── #

def _split_blocks(text: str, max_words: int = MAX_WORDS_PER_BLOCK) -> list[str]:
    """
    Split Arabic text into subtitle blocks of at most `max_words` words.

    Strategy:
    1. Split on sentence terminals (. ؟ ! followed by whitespace or end).
    2. If a sentence is longer than max_words, subdivide it at word boundaries.
    3. Merge very short sentences (<4 words) with the next one.
    """
    # Normalise whitespace
    text = re.sub(r'\s+', ' ', text.strip())

    # Split on sentence terminals
    raw_sentences = re.split(r'(?<=[.؟!\n])\s+', text)
    sentences = [s.strip() for s in raw_sentences if s.strip()]

    # Sub-divide long sentences at word boundaries
    chunks: list[str] = []
    for sent in sentences:
        words = sent.split()
        while len(words) > max_words:
            chunks.append(' '.join(words[:max_words]))
            words = words[max_words:]
        if words:
            chunks.append(' '.join(words))

    # Merge very short trailing chunks with the previous one
    merged: list[str] = []
    for chunk in chunks:
        if merged and len(chunk.split()) < 4 and len(merged[-1].split()) + len(chunk.split()) <= max_words:
            merged[-1] = merged[-1] + ' ' + chunk
        else:
            merged.append(chunk)

    return merged or [text]


# ── ASS generation ───────────────────────────────────────────────────────── #

def generate_ass(
    sections: list[ScriptSection],
    section_durations: list[float],
    width: int = 1280,
    height: int = 720,
    min_block_sec: float = 2.0,
    gap_sec: float = 0.1,
) -> str:
    """
    Build a complete ASS subtitle file and return it as a string.

    Parameters
    ----------
    sections           Parsed script sections (ScriptSection list).
    section_durations  Duration in seconds for each section (same order).
    width / height     Must match the output video resolution.
    min_block_sec      Minimum duration for a single subtitle card.
    gap_sec            Tiny gap between consecutive cards to avoid flash.
    """
    fontsize = max(32, height // 18)   # scale with resolution
    lines = [_ASS_HEADER.format(width=width, height=height, fontsize=fontsize)]

    cursor = 0.0   # running clock position in seconds

    for section, duration in zip(sections, section_durations):
        blocks    = _split_blocks(section.text)
        n_blocks  = len(blocks)
        wc_list   = [max(1, len(b.split())) for b in blocks]
        total_wc  = sum(wc_list)

        t = cursor
        for i, (block, wc) in enumerate(zip(blocks, wc_list)):
            raw_dur  = duration * wc / total_wc
            blk_dur  = max(min_block_sec, raw_dur)
            end_t    = min(t + blk_dur - gap_sec, cursor + duration - gap_sec)
            end_t    = max(end_t, t + min_block_sec)

            # Escape braces so libass does not misparse them as override tags
            safe = block.replace('{', r'\{')
            # \an2 = bottom-centre; \q2 = no word-wrap (libass wraps natively for RTL)
            dialogue = (
                f"Dialogue: 0,{_sec_to_ass(t)},{_sec_to_ass(end_t)},"
                f"Arabic,,0,0,0,,{{\\an2}}{safe}"
            )
            lines.append(dialogue)
            t = end_t + gap_sec

        cursor += duration

    return "\n".join(lines) + "\n"


def write_ass(
    sections: list[ScriptSection],
    section_durations: list[float],
    dest: Path,
    width: int = 1280,
    height: int = 720,
) -> Path:
    """Write the ASS file to `dest` and return its path."""
    content = generate_ass(sections, section_durations, width=width, height=height)
    dest.write_text(content, encoding="utf-8")
    return dest
