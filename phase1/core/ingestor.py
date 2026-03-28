"""
Phase 1 — PDFIngestor
Detects whether a PDF is digitally-born or scanned, then routes to the
appropriate extraction backend.

Arabic RTL extraction — span-level spatial sort
─────────────────────────────────────────────────
Sorts SPANS (not individual chars) by x-position descending.
Characters within each span stay in their original rawdict order,
which PyMuPDF guarantees is the correct glyph sequence for that span.
The only ordering problem is between spans (visual LTR vs logical RTL).

rawdict "c" field returns an int codepoint in newer PyMuPDF builds
and a string character in some older builds — both are handled.
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
_LINE_TOL_PT = 4.0
_SENT_TERMINAL = re.compile(r'[.؟!]\s*$')
_IS_HEADING    = re.compile(r'^(?!.*[.،؛؟!]).{4,55}$')  # 55 = max genuine heading length


@dataclass
class RawPage:
    page_number: int
    pdf_type:    PDFType
    raw_text:    str            # populated by ingestor / OCR engine
    raw_text_pre: str = ""     # snapshot of text BEFORE normalisation (set by pipeline)
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
    Auto-detects PDF type and extracts RTL-correct text.
    """

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
                    raw_text_pre = text,   # snapshot before any processing
                ))
            else:
                mat       = fitz.Matrix(self.dpi / 72, self.dpi / 72)
                pix       = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
                img_bytes = pix.tobytes("png")
                pages.append(RawPage(
                    page_number  = page_num,
                    pdf_type     = "scanned",
                    raw_text     = "",
                    raw_text_pre = "",     # filled after OCR
                    image_bytes  = img_bytes,
                ))

        doc.close()

        digital = sum(1 for p in pages if p.pdf_type == "digital")
        scanned = sum(1 for p in pages if p.pdf_type == "scanned")
        overall_type: PDFType = (
            "scanned" if digital == 0 else
            "digital" if scanned == 0 else
            "mixed"
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
    #  Span-level RTL extraction                                           #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _extract_rtl_text(page: fitz.Page) -> str:
        raw = page.get_text(
            "rawdict",
            flags=fitz.TEXT_PRESERVE_WHITESPACE | fitz.TEXT_MEDIABOX_CLIP,
        )

        span_entries: list[tuple[float, float, str]] = []

        for block in raw.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    char_data = span.get("chars", [])
                    if not char_data:
                        continue

                    span_chars: list[str] = []
                    xs: list[float] = []
                    ys: list[float] = []

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
                        span_chars.append(ch_str)
                        xs.append(ox)
                        ys.append(oy)

                    if not span_chars:
                        continue

                    span_text = unicodedata.normalize("NFKC", "".join(span_chars))
                    if not span_text.strip():
                        continue

                    x_rep = min(xs)
                    y_rep = ys[0]
                    span_entries.append((x_rep, y_rep, span_text))

        if not span_entries:
            return ""

        # Group by y (visual line)
        span_entries.sort(key=lambda e: e[1])
        lines: list[list[tuple[float, str]]] = []
        current_line: list[tuple[float, str]] = []
        current_y = span_entries[0][1]

        for x, y, text in span_entries:
            if abs(y - current_y) > _LINE_TOL_PT:
                if current_line:
                    lines.append(current_line)
                current_line = [(x, text)]
                current_y    = y
            else:
                current_line.append((x, text))
        if current_line:
            lines.append(current_line)

        # Sort each line's spans descending-x → RTL order
        # Diacritic-only spans (ً ٌ ٍ etc.) are appended to the previous span.
        # Arabic comma ، is repositioned: X ، Y → X، Y and ، X → X،
        _DIACRITIC_CP = set(range(0x0610, 0x061B)) | set(range(0x064B, 0x0653)) | {0x0670}

        def is_diacritic_only(s: str) -> bool:
            return bool(s) and all(ord(c) in _DIACRITIC_CP for c in s.strip())

        def fix_comma(line: str) -> str:
            # Move ، from before a word to after the preceding word
            line = re.sub(r'(\S+)\s+،\s*(\S)', r'\1، \2', line)
            line = re.sub(r'^،\s*(\S+)', r'\1،', line)
            return line

        visual_lines: list[str] = []
        for line_spans in lines:
            line_spans.sort(key=lambda t: t[0], reverse=True)
            # Merge diacritic-only spans into previous span
            merged: list[tuple[float, str]] = []
            for x, t in line_spans:
                if is_diacritic_only(t) and merged:
                    merged[-1] = (merged[-1][0], merged[-1][1] + t)
                else:
                    merged.append((x, t))
            line_text = fix_comma(" ".join(t for _, t in merged).strip())
            if line_text:
                visual_lines.append(line_text)

        # Paragraph reconstruction with heading detection
        if not visual_lines:
            return ""

        def is_heading(s: str) -> bool:
            s = s.strip()
            return bool(_IS_HEADING.match(s)) and len(s) <= 55

        paragraphs: list[str] = []
        buffer = visual_lines[0]

        for line in visual_lines[1:]:
            if is_heading(buffer) and paragraphs:
                # Only break on heading if we already have content above it —
                # prevents the first line from emitting an empty leading paragraph.
                paragraphs.extend([buffer, ""])
                buffer = line
            elif is_heading(line) and buffer.strip():
                # Upcoming line is a heading → close current paragraph first.
                paragraphs.extend([buffer, ""])
                buffer = line
            elif _SENT_TERMINAL.search(buffer):
                paragraphs.append(buffer)
                buffer = line
            else:
                buffer = buffer + " " + line

        paragraphs.append(buffer)
        # Remove leading/trailing blank entries
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
