"""
Phase 1 — ArabicTextNormalizer
Source-aware Arabic text normalisation.

The critical insight driving this design:
─────────────────────────────────────────
• PyMuPDF (digital PDFs) already returns Arabic in correct LOGICAL order.
  Applying BiDi get_display() on top of it RE-REVERSES the text into visual
  order — which looks wrong and breaks every downstream consumer (LLM, TTS).
  Reshaping is also wrong here: PyMuPDF returns connected Unicode code points,
  not isolated glyph forms.

• EasyOCR / Tesseract (scanned PDFs) return text in VISUAL order with isolated
  glyph forms. These DO need reshape + bidi reordering.

Pipeline by source
──────────────────
  digital  →  NFC  →  clean  →  done          (no reshape, no bidi)
  scanned  →  NFC  →  reshape  →  bidi  →  clean
"""

from __future__ import annotations

import re
import unicodedata
import logging
from typing import Literal

logger = logging.getLogger(__name__)

Source = Literal["digital", "scanned"]

# ── Lazy imports ──────────────────────────────────────────────────────── #
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
            "Arabic text libraries missing.\n"
            "Run: pip install arabic-reshaper python-bidi"
        ) from exc


class ArabicTextNormalizer:
    """
    Normalises Arabic text with source-aware processing.

    Args:
        scanned_reshape: Apply reshape + bidi for scanned/OCR pages (default True).
                         Always False for digital pages regardless of this flag.
    """

    _NOISE_PATTERNS = [
        re.compile(r"^\s*\d+\s*$", re.MULTILINE),   # lone page numbers
        re.compile(r"[\u200b\u200c\u200d\ufeff]"),   # zero-width chars
        re.compile(r"[ \t]{3,}", re.MULTILINE),       # excessive spaces
        re.compile(r"\n{4,}", re.MULTILINE),           # excessive blank lines
    ]

    def __init__(self, scanned_reshape: bool = True):
        self.scanned_reshape = scanned_reshape

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def normalize(self, text: str, source: Source = "digital") -> str:
        """
        Normalise Arabic text.

        Args:
            text:   Raw extracted text from ingestor or OCR engine.
            source: "digital" (PyMuPDF) or "scanned" (OCR output).
        """
        if not text or not text.strip():
            return ""

        # Step 1: Unicode canonical form — always safe
        text = unicodedata.normalize("NFC", text)

        # Step 2: reshape + bidi ONLY for scanned/OCR text
        if source == "scanned" and self.scanned_reshape:
            _load_arabic_libs()
            text = self._reshape_lines(text)
            text = self._bidi_lines(text)

        # Step 3: clean noise
        text = self._clean(text)
        return text.strip()

    def normalize_pages(self, pages: list) -> list:
        """
        In-place normalisation of RawPage objects.
        Reads each page's own pdf_type to choose the correct path.
        """
        for page in pages:
            source: Source = "scanned" if page.pdf_type == "scanned" else "digital"
            before = len(page.raw_text)
            page.raw_text = self.normalize(page.raw_text, source=source)
            logger.debug(
                "Page %d [%s] normalised: %d → %d chars",
                page.page_number, source, before, len(page.raw_text),
            )
        return pages

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    def _reshape_lines(self, text: str) -> str:
        cfg = _reshaper.ArabicReshaper(configuration={
            "delete_harakat":  False,   # preserve diacritics
            "support_ligatures": True,
        })
        return "\n".join(cfg.reshape(line) for line in text.splitlines())

    def _bidi_lines(self, text: str) -> str:
        return "\n".join(
            _get_display(line, base_dir="R") for line in text.splitlines()
        )

    def _clean(self, text: str) -> str:
        for pat in self._NOISE_PATTERNS:
            if pat.pattern == r"\n{4,}":
                text = pat.sub("\n\n\n", text)
            elif pat.pattern == r"[ \t]{3,}":
                text = pat.sub("  ", text)
            else:
                text = pat.sub("", text)
        return text
