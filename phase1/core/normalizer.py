"""
Phase 1 — ArabicTextNormalizer
Source-aware Arabic text normalisation.

PyMuPDF extraction behaviour for Arabic digital PDFs
─────────────────────────────────────────────────────
PyMuPDF returns Arabic glyphs in correct Unicode code points (connected,
not isolated forms), BUT it sequences words in VISUAL left-to-right order
across the page — i.e. the last word of each RTL sentence comes first.

What is needed per source
──────────────────────────
  digital  →  NFC  →  bidi reorder (no reshape)  →  clean
  scanned  →  NFC  →  reshape  →  bidi reorder   →  clean

Why reshape is skipped for digital
────────────────────────────────────
PyMuPDF already returns connected Unicode glyphs. arabic-reshaper converts
connected forms INTO isolated glyph forms (intended for rendering engines).
Applying it to already-correct text breaks the shaping. Only OCR output —
which comes out in isolated visual glyph forms — needs reshaping.
"""

from __future__ import annotations

import re
import unicodedata
import logging
from typing import Literal

logger = logging.getLogger(__name__)

Source = Literal["digital", "scanned"]

_reshaper    = None
_get_display = None


def _load_arabic_libs() -> None:
    global _reshaper, _get_display
    if _reshaper is not None:
        return
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        _reshaper    = arabic_reshaper
        _get_display = get_display
    except ImportError as exc:
        raise ImportError(
            "Run: pip install arabic-reshaper python-bidi"
        ) from exc


class ArabicTextNormalizer:
    """
    Normalises Arabic text with source-aware processing.

    digital pages: bidi reorder only (no reshape — glyphs already connected)
    scanned pages: reshape first, then bidi reorder
    """

    _NOISE_PATTERNS = [
        re.compile(r"^\s*\d+\s*$", re.MULTILINE),   # lone page numbers
        re.compile(r"[\u200b\u200c\u200d\ufeff]"),   # zero-width chars
        re.compile(r"[ \t]{3,}", re.MULTILINE),       # excessive spaces
        re.compile(r"\n{4,}", re.MULTILINE),           # excessive blank lines
    ]

    def normalize(self, text: str, source: Source = "digital") -> str:
        if not text or not text.strip():
            return ""

        _load_arabic_libs()

        # Step 1: Unicode canonical form
        text = unicodedata.normalize("NFC", text)

        # Step 2: reshape only for scanned/OCR output
        if source == "scanned":
            cfg = _reshaper.ArabicReshaper(configuration={
                "delete_harakat":    False,
                "support_ligatures": True,
            })
            text = "\n".join(cfg.reshape(line) for line in text.splitlines())

        # Step 3: bidi reorder — needed for BOTH digital and scanned
        # digital: fixes word-order reversal from PyMuPDF visual extraction
        # scanned: fixes character-level reversal from OCR visual output
        text = "\n".join(
            _get_display(line, base_dir="R") for line in text.splitlines()
        )

        # Step 4: clean noise
        text = self._clean(text)
        return text.strip()

    def normalize_pages(self, pages: list) -> list:
        """In-place normalisation; reads pdf_type from each RawPage."""
        for page in pages:
            source: Source = "scanned" if page.pdf_type == "scanned" else "digital"
            before = len(page.raw_text)
            page.raw_text = self.normalize(page.raw_text, source=source)
            logger.debug(
                "Page %d [%s] normalised: %d → %d chars",
                page.page_number, source, before, len(page.raw_text),
            )
        return pages

    def _clean(self, text: str) -> str:
        for pat in self._NOISE_PATTERNS:
            if pat.pattern == r"\n{4,}":
                text = pat.sub("\n\n\n", text)
            elif pat.pattern == r"[ \t]{3,}":
                text = pat.sub("  ", text)
            else:
                text = pat.sub("", text)
        return text
