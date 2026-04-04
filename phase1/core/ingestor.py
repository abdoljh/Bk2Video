"""
Phase 1 — PDFIngestor
Detects whether a PDF is digitally-born or scanned, then routes to the
appropriate extraction backend.

Arabic RTL extraction — span-level spatial sort with gap-based word joining
────────────────────────────────────────────────────────────────────────────
The PDF stores Arabic text with glyphs in visual left-to-right order.
The lam-alef article ligature is split across MULTIPLE SPANS by PyMuPDF,
with the article alef in one span and the lam+rest in a separate span.
These must be joined WITHOUT a space to form complete words.

Algorithm:
  1. Collect spans from rawdict with BOTH left-x (for RTL sort) and
     right-x (for gap detection).
  2. Group spans into visual lines by y-coordinate.
  3. Sort spans descending left-x → RTL reading order.
  4. Join consecutive spans: insert a space only when the visual gap
     between the right edge of span[i] and the left edge of span[i+1]
     exceeds WORD_GAP_PT. Otherwise join directly (same word).
  5. Merge diacritic-only spans to their adjacent word span.
  6. Fix comma positions and duplicate punctuation.
  7. Reconstruct paragraphs with heading detection.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

PDFType = Literal["digital", "scanned", "mixed"]

_DIGITAL_CHARS_THRESHOLD = 100
_LINE_TOL_PT  = 4.0    # y-tolerance for grouping spans onto same line
_WORD_GAP_PT  = 3.0    # minimum gap (pts) between spans to insert a space
_SENT_TERMINAL = re.compile(r'[.؟!]\s*$')
_IS_HEADING    = re.compile(r'^(?!.*[.،؛؟!]).{4,55}$')


@dataclass
class RawPage:
    page_number:  int
    pdf_type:     PDFType
    raw_text:     str
    raw_text_pre: str = ""
    image_bytes:  bytes | None = field(default=None, repr=False)


@dataclass
class IngestionResult:
    source_path: str
    pdf_type:    PDFType
    total_pages: int
    pages:       list[RawPage]
    metadata:    dict


class PDFIngestor:
    def __init__(self, dpi: int = 200):
        self.dpi = dpi

    def ingest(self, pdf_path: str | Path) -> IngestionResult:
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        doc   = fitz.open(str(pdf_path))
        meta  = self._extract_metadata(doc)
        pages: list[RawPage] = []

        for i, page in enumerate(doc):
            page_num   = i + 1
            probe_text = page.get_text("text").strip()
            if len(probe_text) >= _DIGITAL_CHARS_THRESHOLD:
                text = self._extract_rtl_text(page)
                pages.append(RawPage(
                    page_number  = page_num,
                    pdf_type     = "digital",
                    raw_text     = text,
                    raw_text_pre = text,
                ))
            else:
                mat       = fitz.Matrix(self.dpi / 72, self.dpi / 72)
                pix       = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
                img_bytes = pix.tobytes("png")
                pages.append(RawPage(
                    page_number  = page_num,
                    pdf_type     = "scanned",
                    raw_text     = "",
                    raw_text_pre = "",
                    image_bytes  = img_bytes,
                ))

        doc.close()
        digital = sum(1 for p in pages if p.pdf_type == "digital")
        scanned = sum(1 for p in pages if p.pdf_type == "scanned")
        overall_type: PDFType = (
            "scanned" if digital == 0 else
            "digital" if scanned == 0 else "mixed"
        )
        logger.info("Ingested '%s' — %d pages (%d digital, %d scanned)",
                    pdf_path.name, len(pages), digital, scanned)
        return IngestionResult(
            source_path=str(pdf_path),
            pdf_type=overall_type,
            total_pages=len(pages),
            pages=pages,
            metadata=meta,
        )

    # ------------------------------------------------------------------ #
    #  RTL text extraction                                                 #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _extract_rtl_text(page: fitz.Page) -> str:
        raw = page.get_text(
            "rawdict",
            flags=fitz.TEXT_PRESERVE_WHITESPACE | fitz.TEXT_MEDIABOX_CLIP,
        )

        # Each entry: (x_left, x_right, y, text)
        # x_left  = leftmost char origin  → used for RTL sort (descending)
        # x_right = rightmost char bbox right edge → used for gap detection
        span_entries: list[tuple[float, float, float, str]] = []

        for block in raw.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    char_data = span.get("chars", [])
                    if not char_data:
                        continue

                    span_chars: list[str] = []
                    x_origins: list[float] = []
                    x_rights:  list[float] = []
                    y_origins: list[float] = []

                    for ch in char_data:
                        c = ch.get("c", 0)
                        if isinstance(c, int):
                            if c <= 0x20:
                                continue
                            ch_str = chr(c)
                        else:
                            ch_str = str(c)
                            if not ch_str.strip():
                                continue

                        ox, oy = ch["origin"]
                        # bbox: (x0, y0, x1, y1) — x1 is right edge of glyph
                        bbox = ch.get("bbox", (ox, oy, ox, oy))
                        span_chars.append(ch_str)
                        x_origins.append(ox)
                        x_rights.append(bbox[2])
                        y_origins.append(oy)

                    if not span_chars:
                        continue

                    span_text = unicodedata.normalize("NFKC", "".join(span_chars))
                    if not span_text.strip():
                        continue

                    x_left  = min(x_origins)
                    x_right = max(x_rights)
                    y_rep   = y_origins[0]
                    span_entries.append((x_left, x_right, y_rep, span_text))

        if not span_entries:
            return ""

        # ── Group spans into visual lines by y-coordinate ──────────────
        span_entries.sort(key=lambda e: e[2])   # sort by y
        lines: list[list[tuple[float, float, str]]] = []
        current_line: list[tuple[float, float, str]] = []
        current_y = span_entries[0][2]

        for x_l, x_r, y, text in span_entries:
            if abs(y - current_y) > _LINE_TOL_PT:
                if current_line:
                    lines.append(current_line)
                current_line = [(x_l, x_r, text)]
                current_y    = y
            else:
                current_line.append((x_l, x_r, text))
        if current_line:
            lines.append(current_line)

        # ── Per line: sort spans RTL, merge diacritics, join with gap ──
        _DIACRITIC_CP = set(range(0x0610, 0x061B)) | set(range(0x064B, 0x0653)) | {0x0670}

        _ALEF_CHARS = {'\u0627', '\u0622', '\u0623', '\u0625'}

        def is_diacritic_only(s: str) -> bool:
            """Catches pure diacritics AND alef+diacritics (tanwin-fath marker اًّ)."""
            s = s.strip()
            if not s:
                return False
            if all(ord(c) in _DIACRITIC_CP for c in s):
                return True
            # Standalone alef followed only by diacritics = tanwin-fath marker
            if s[0] in _ALEF_CHARS and len(s) >= 2 and all(ord(c) in _DIACRITIC_CP for c in s[1:]):
                return True
            return False

        def fix_comma(line: str) -> str:
            # In RTL text, ، follows the word to its RIGHT in visual space
            # (the word that PRECEDES it in reading order).
            # Pattern: X ، Y → X Y،   (comma trails Y, which is read first)
            line = re.sub(r'(\S+)\s+،\s*(\S+)', r'\1 \2،', line)
            # Leading ، with no left-side word: ، X → X،
            line = re.sub(r'^،\s*(\S+)', r'\1،', line)
            return line

        def clean_punct(line: str) -> str:
            line = re.sub(r'،،+', '،', line)
            line = re.sub(r'\.{2,}', '.', line)
            return line

        visual_lines: list[str] = []

        for line_spans in lines:
            # Sort descending by left-x → RTL reading order
            line_spans.sort(key=lambda t: t[0], reverse=True)

            # Merge diacritic-only spans into adjacent word spans
            # (x_left, x_right, text)
            merged: list[tuple[float, float, str]] = []
            pending_diac = ""

            for x_l, x_r, t in line_spans:
                if is_diacritic_only(t):
                    if merged:
                        prev = merged[-1]
                        merged[-1] = (prev[0], prev[1], prev[2] + t)
                    else:
                        pending_diac += t
                else:
                    merged.append((x_l, x_r, pending_diac + t))
                    pending_diac = ""

            if pending_diac and merged:
                prev = merged[-1]
                merged[-1] = (prev[0], prev[1], prev[2] + pending_diac)

            if not merged:
                continue

            # Join spans: insert space only when visual gap exceeds threshold
            # In RTL sorted order, merged[i] is to the RIGHT of merged[i+1].
            # Gap = merged[i].x_left - merged[i+1].x_right
            # (right span's left edge minus left span's right edge)
            parts = [merged[0][2]]
            for i in range(1, len(merged)):
                prev_x_left  = merged[i-1][0]   # left edge of previous (rightward) span
                curr_x_right = merged[i][1]      # right edge of current (leftward) span
                gap = prev_x_left - curr_x_right
                if gap >= _WORD_GAP_PT:
                    parts.append(" ")
                parts.append(merged[i][2])

            line_text = clean_punct(fix_comma("".join(parts).strip()))
            if line_text:
                visual_lines.append(line_text)

        # ── Paragraph reconstruction with heading detection ─────────────
        if not visual_lines:
            return ""

        _DIAC_ONLY_LINE = re.compile(
            r'^[\u0600-\u0615\u064B-\u065F\u0670\u0627\u0622\u0623\u0625\s]+$'
        )

        def is_heading(s: str) -> bool:
            s = s.strip()
            if _DIAC_ONLY_LINE.match(s):
                return False
            return bool(_IS_HEADING.match(s)) and len(s) <= 55

        paragraphs: list[str] = []
        buffer = visual_lines[0]

        for line in visual_lines[1:]:
            if is_heading(buffer) and paragraphs:
                paragraphs.extend([buffer, ""])
                buffer = line
            elif is_heading(line) and buffer.strip():
                paragraphs.extend([buffer, ""])
                buffer = line
            elif _SENT_TERMINAL.search(buffer):
                paragraphs.append(buffer)
                buffer = line
            else:
                buffer = buffer + " " + line

        paragraphs.append(buffer)
        while paragraphs and not paragraphs[0].strip():
            paragraphs.pop(0)
        while paragraphs and not paragraphs[-1].strip():
            paragraphs.pop()
        return "\n".join(paragraphs)

    @staticmethod
    def _extract_metadata(doc: fitz.Document) -> dict:
        raw = doc.metadata or {}
        return {
            "title":   raw.get("title",   ""),
            "author":  raw.get("author",  ""),
            "subject": raw.get("subject", ""),
            "creator": raw.get("creator", ""),
            "pages":   doc.page_count,
        }
