"""
Phase 1 — PDFIngestor
Detects whether a PDF is digitally-born or scanned, then routes to the
appropriate extraction backend (PyMuPDF for digital, EasyOCR for scanned).
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

PDFType = Literal["digital", "scanned", "mixed"]

# Heuristic: if fewer than this many chars per page on average → likely scanned
_DIGITAL_CHARS_THRESHOLD = 100


@dataclass
class RawPage:
    page_number: int          # 1-indexed
    pdf_type: PDFType
    raw_text: str             # straight from PyMuPDF (may be reversed Arabic)
    image_bytes: bytes | None = field(default=None, repr=False)  # for OCR path


@dataclass
class IngestionResult:
    source_path: str
    pdf_type: PDFType
    total_pages: int
    pages: list[RawPage]
    metadata: dict            # title, author, subject from PDF header


class PDFIngestor:
    """
    Auto-detects PDF type and extracts raw text from every page.

    Digital PDFs  → PyMuPDF text extraction (fast, lossless).
    Scanned PDFs  → renders each page to an image then hands off to OCR.
    Mixed PDFs    → per-page routing (some pages digital, some scanned).
    """

    def __init__(self, dpi: int = 200):
        """
        Args:
            dpi: Resolution for rasterising scanned pages before OCR.
                 200 is a good balance of speed vs accuracy for Arabic.
        """
        self.dpi = dpi

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def ingest(self, pdf_path: str | Path) -> IngestionResult:
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        doc = fitz.open(str(pdf_path))
        meta = self._extract_metadata(doc)
        pages: list[RawPage] = []

        for i, page in enumerate(doc):
            page_num = i + 1
            text = page.get_text("text")
            char_count = len(text.strip())

            if char_count >= _DIGITAL_CHARS_THRESHOLD:
                pages.append(RawPage(
                    page_number=page_num,
                    pdf_type="digital",
                    raw_text=text,
                ))
            else:
                # Render page to PNG bytes for OCR
                mat = fitz.Matrix(self.dpi / 72, self.dpi / 72)
                pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
                img_bytes = pix.tobytes("png")
                pages.append(RawPage(
                    page_number=page_num,
                    pdf_type="scanned",
                    raw_text="",           # filled in by OCREngine
                    image_bytes=img_bytes,
                ))

        doc.close()

        digital = sum(1 for p in pages if p.pdf_type == "digital")
        scanned = sum(1 for p in pages if p.pdf_type == "scanned")

        if digital == 0:
            overall_type: PDFType = "scanned"
        elif scanned == 0:
            overall_type = "digital"
        else:
            overall_type = "mixed"

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
    #  Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _extract_metadata(doc: fitz.Document) -> dict:
        raw = doc.metadata or {}
        return {
            "title":    raw.get("title", ""),
            "author":   raw.get("author", ""),
            "subject":  raw.get("subject", ""),
            "creator":  raw.get("creator", ""),
            "pages":    doc.page_count,
        }
