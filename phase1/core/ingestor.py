"""
Phase 1 — PDFIngestor
Detects whether a PDF is digitally-born or scanned, then routes to the
appropriate extraction backend.

Arabic RTL extraction — definitive approach
────────────────────────────────────────────
Arabic PDF fonts frequently have broken ToUnicode tables that cause:
  • Lam-alef ligature glyphs decoded in wrong char order (alef before lam)
  • Hamza-alef forms confused with plain alef
  • Span-level text in visual (LTR) order rather than logical (RTL) order

All of these are bypassed by working at the CHARACTER level using
page.get_text("rawdict"), which gives us each glyph's Unicode codepoint
AND its exact x-coordinate on the page.

Algorithm per page:
  1. Collect every (x, y, char) triple from rawdict.
  2. Group chars into visual lines by y-coordinate (±2pt tolerance).
  3. Within each line, sort chars by x DESCENDING → right-to-left order.
  4. Identify word boundaries by horizontal gaps > threshold.
  5. Join chars into words, apply NFKC normalization per word.
  6. Detect headings (short lines, no sentence punct) and wrap with \\n\\n.
  7. Soft-join remaining wrapped lines into paragraphs.
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

# Gap between chars (in points) that signals a word boundary
_WORD_GAP_PT = 3.0

# Line grouping tolerance (points) — chars within this y-range = same line
_LINE_TOL_PT = 2.0

# Sentence-terminal: line ending with one of these → hard paragraph break
_SENT_TERMINAL = re.compile(r'[.؟!]\s*$')

# Heading: short line (<=80 chars) with no sentence-end punctuation
_IS_HEADING = re.compile(r'^(?!.*[.،؛؟!]).{4,80}$')


@dataclass
class RawPage:
    page_number: int
    pdf_type:    PDFType
    raw_text:    str
    image_bytes: bytes | None = field(default=None, repr=False)


@dataclass
class IngestionResult:
    source_path: str
    pdf_type:    PDFType
    total_pages: int
    pages:       list[RawPage]
    metadata:    dict


class PDFIngestor:
    """
    Auto-detects PDF type and extracts RTL-correct, ligature-resolved text.
    """

    def __init__(self, dpi: int = 200):
        self.dpi = dpi

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

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
                    page_number=page_num,
                    pdf_type="digital",
                    raw_text=text,
                ))
            else:
                mat       = fitz.Matrix(self.dpi / 72, self.dpi / 72)
                pix       = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
                img_bytes = pix.tobytes("png")
                pages.append(RawPage(
                    page_number=page_num,
                    pdf_type="scanned",
                    raw_text="",
                    image_bytes=img_bytes,
                ))

        doc.close()

        digital      = sum(1 for p in pages if p.pdf_type == "digital")
        scanned      = sum(1 for p in pages if p.pdf_type == "scanned")
        overall_type: PDFType = (
            "scanned" if digital == 0 else
            "digital" if scanned == 0 else
            "mixed"
        )

        logger.info(
            "Ingested '%s' — %d pages (%d digital, %d scanned)",
            pdf_path.name, len(pages), digital, scanned,
        )

        return IngestionResult(
            source_path=str(pdf_path),
            pdf_type=overall_type,
            total_pages=len(pages),
            pages=pages,
            metadata=meta,
        )

    # ------------------------------------------------------------------ #
    #  Character-level RTL extraction                                      #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _extract_rtl_text(page: fitz.Page) -> str:
        """
        Reconstruct page text from individual character positions.

        Uses rawdict mode to get per-character (x, y, unicode) data,
        then sorts characters spatially to recover correct RTL reading order
        regardless of how the font's ToUnicode table is structured.
        """
        raw = page.get_text(
            "rawdict",
            flags=fitz.TEXT_PRESERVE_WHITESPACE | fitz.TEXT_MEDIABOX_CLIP,
        )

        # ── 1. Collect all (x, y, char) triples ──────────────────────
        chars: list[tuple[float, float, str]] = []

        for block in raw.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    for ch in span.get("chars", []):
                        c   = ch.get("c", 0)        # Unicode codepoint int
                        if ord(c) <= 0x20:               # skip control chars / spaces if c <= 0x20
                            continue
                        ox, oy = ch["origin"]
                        chars.append((ox, oy, chr(c)))

        if not chars:
            return ""

        # ── 2. Group chars into visual lines by y-coordinate ──────────
        chars.sort(key=lambda t: t[1])              # sort by y first
        lines: list[list[tuple[float, str]]] = []   # list of [(x, char)]
        current_line: list[tuple[float, str]] = []
        current_y = chars[0][1]

        for ox, oy, ch in chars:
            if abs(oy - current_y) > _LINE_TOL_PT:
                if current_line:
                    lines.append(current_line)
                current_line = [(ox, ch)]
                current_y    = oy
            else:
                current_line.append((ox, ch))

        if current_line:
            lines.append(current_line)

        # ── 3. Per line: sort chars right-to-left, group into words ───
        visual_lines: list[str] = []

        for line_chars in lines:
            # Sort descending x → right-to-left character order
            line_chars.sort(key=lambda t: t[0], reverse=True)

            # Group into words by horizontal gap
            words: list[str] = []
            word_chars: list[str] = [line_chars[0][1]]
            prev_x = line_chars[0][0]

            for x, ch in line_chars[1:]:
                gap = abs(prev_x - x)
                if gap > _WORD_GAP_PT:
                    word = unicodedata.normalize("NFKC", "".join(word_chars))
                    if word.strip():
                        words.append(word)
                    word_chars = [ch]
                else:
                    word_chars.append(ch)
                prev_x = x

            # Flush last word
            if word_chars:
                word = unicodedata.normalize("NFKC", "".join(word_chars))
                if word.strip():
                    words.append(word)

            if words:
                visual_lines.append(" ".join(words))

        # ── 4. Paragraph reconstruction ───────────────────────────────
        if not visual_lines:
            return ""

        def is_heading(s: str) -> bool:
            s = s.strip()
            return bool(_IS_HEADING.match(s)) and len(s) <= 80

        paragraphs: list[str] = []
        buffer = visual_lines[0]

        for line in visual_lines[1:]:
            if is_heading(buffer):
                paragraphs.extend([buffer, ""])
                buffer = line
            elif is_heading(line):
                if buffer:
                    paragraphs.extend([buffer, ""])
                buffer = line
            elif _SENT_TERMINAL.search(buffer):
                paragraphs.append(buffer)
                buffer = line
            else:
                buffer = buffer + " " + line

        paragraphs.append(buffer)
        return "\n".join(paragraphs)

    # ------------------------------------------------------------------ #
    #  Metadata                                                            #
    # ------------------------------------------------------------------ #

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
