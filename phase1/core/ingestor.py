"""
Phase 1 — PDFIngestor
Detects whether a PDF is digitally-born or scanned, then routes to the
appropriate extraction backend.

Arabic RTL extraction — span-level spatial sort
─────────────────────────────────────────────────
The correct algorithm for Arabic PDFs with broken ToUnicode tables:

  WRONG: sort individual characters by x-position.
         Characters within a single ligature glyph (e.g. لا) get
         assigned different virtual x-origins by PyMuPDF, so they
         end up space-separated and potentially reordered.

  RIGHT: sort SPANS by x-position; preserve character order within
         each span. PyMuPDF guarantees that characters within one
         span belong to the same font run and are listed in their
         correct glyph sequence. The only ordering problem is
         between spans (visual LTR vs logical RTL).

Algorithm per page:
  1. Collect spans from rawdict with their representative x-coord
     (leftmost char origin in the span).
  2. Group spans into visual lines by y-coordinate (±2pt tolerance).
  3. Within each line sort spans descending-x → RTL reading order.
  4. Concatenate chars within each span (original order), apply NFKC.
  5. Join spans with a space; join lines into paragraphs with heading
     detection and soft line-joining.
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
_LINE_TOL_PT = 2.0          # y-tolerance for grouping chars onto same line
_SENT_TERMINAL = re.compile(r'[.؟!]\s*$')
_IS_HEADING    = re.compile(r'^(?!.*[.،؛؟!]).{4,80}$')


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
    #  Span-level RTL extraction                                           #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _extract_rtl_text(page: fitz.Page) -> str:
        """
        Extract Arabic text in correct RTL reading order.

        Sorts SPANS (not individual chars) by x-position descending.
        Characters within each span stay in their original rawdict order,
        which PyMuPDF guarantees is the correct glyph sequence for that span.
        """
        raw = page.get_text(
            "rawdict",
            flags=fitz.TEXT_PRESERVE_WHITESPACE | fitz.TEXT_MEDIABOX_CLIP,
        )

        # Each entry: (x_representative, y_representative, span_text)
        # x = leftmost char origin in span (used for RTL sort)
        # y = first char origin y (used for line grouping)
        span_entries: list[tuple[float, float, str]] = []

        for block in raw.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    char_data = span.get("chars", [])
                    if not char_data:
                        continue

                    # Build span text from chars in their original order
                    # rawdict "c" field: int codepoint in newer PyMuPDF,
                    # string character in some builds — handle both.
                    span_chars = []
                    xs: list[float] = []
                    ys: list[float] = []

                    for ch in char_data:
                        c = ch.get("c", 0)
                        # Normalise to string
                        if isinstance(c, int):
                            if c <= 0x20:       # skip control / space
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

                    span_text = unicodedata.normalize(
                        "NFKC", "".join(span_chars)
                    )
                    if not span_text.strip():
                        continue

                    x_rep = min(xs)     # leftmost x → used for RTL sort
                    y_rep = ys[0]       # first char y → used for line grouping
                    span_entries.append((x_rep, y_rep, span_text))

        if not span_entries:
            return ""

        # ── Group spans into visual lines by y-coordinate ─────────────
        span_entries.sort(key=lambda e: e[1])   # sort by y
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

        # ── Per line: sort spans descending-x → RTL reading order ─────
        visual_lines: list[str] = []
        for line_spans in lines:
            line_spans.sort(key=lambda t: t[0], reverse=True)
            line_text = " ".join(t for _, t in line_spans).strip()
            if line_text:
                visual_lines.append(line_text)

        # ── Paragraph reconstruction with heading detection ────────────
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
