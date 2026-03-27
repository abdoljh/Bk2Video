"""
Phase 1 — PDFIngestor
Detects whether a PDF is digitally-born or scanned, then routes to the
appropriate extraction backend.

Arabic RTL extraction strategy
────────────────────────────────
page.get_text("text") loses directionality — Arabic words come out in
visual left-to-right order (last word first). Instead we use get_text("dict")
which gives us spans with direction vectors. We detect RTL spans and
reassemble each line in the correct right-to-left reading order before
joining into page text.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

PDFType = Literal["digital", "scanned", "mixed"]

_DIGITAL_CHARS_THRESHOLD = 100


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
    Auto-detects PDF type and extracts RTL-correct text from every page.

    Digital PDFs → PyMuPDF dict-mode extraction with RTL span reordering.
    Scanned PDFs → page rasterised to PNG, handed to OCREngine.
    Mixed PDFs   → per-page routing.
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
                # Use dict mode to get span-level direction info
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
    #  RTL-aware text extraction                                           #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _extract_rtl_text(page: fitz.Page) -> str:
        """
        Extract text from a page preserving RTL reading order.

        PyMuPDF's dict mode returns blocks → lines → spans, each span
        carrying a 'dir' tuple (cos θ, sin θ) for the writing direction.
        For standard horizontal RTL text, dir ≈ (1, 0) but the spans
        within each line are ordered left-to-right on the page (i.e.
        visually, which is reversed for Arabic).

        Strategy:
        1. Collect all lines across all blocks, sorted top-to-bottom by y.
        2. Within each line, sort spans by x-position descending (rightmost
           span first) to reconstruct RTL reading order.
        3. Join span text with spaces, lines with newlines.
        """
        data       = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
        line_buckets: dict[float, list[tuple[float, str]]] = {}

        for block in data.get("blocks", []):
            if block.get("type") != 0:   # 0 = text block
                continue
            for line in block.get("lines", []):
                # Use the top-y of the line's bbox as the bucket key
                # Round to 1 decimal to merge spans on the same visual line
                y_key = round(line["bbox"][1], 1)
                for span in line.get("spans", []):
                    span_text = span.get("text", "").strip()
                    if not span_text:
                        continue
                    x_origin = span["origin"][0]
                    if y_key not in line_buckets:
                        line_buckets[y_key] = []
                    line_buckets[y_key].append((x_origin, span_text))

        lines: list[str] = []
        for y_key in sorted(line_buckets):
            spans = line_buckets[y_key]
            # Sort spans right-to-left (descending x) for RTL reading order
            spans.sort(key=lambda t: t[0], reverse=True)
            line_text = " ".join(text for _, text in spans)
            lines.append(line_text)

        return "\n".join(lines)

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
