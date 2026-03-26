"""
Phase 1 — ArabicTextNormalizer
Fixes the visual-order reversal that PyMuPDF produces for Arabic text,
reshapes connected glyphs, and cleans common extraction artefacts.

Pipeline per page:
  raw_text  →  bidi reorder  →  arabic-reshaper  →  clean  →  normalised_text
"""

from __future__ import annotations

import re
import unicodedata
import logging

logger = logging.getLogger(__name__)

# ── Lazy imports so the module loads even if libs are missing ──────────── #
_reshaper = None
_get_display = None


def _load_arabic_libs():
    global _reshaper, _get_display
    if _reshaper is None:
        try:
            import arabic_reshaper                    # noqa: PLC0415
            from bidi.algorithm import get_display    # noqa: PLC0415
            _reshaper   = arabic_reshaper
            _get_display = get_display
        except ImportError as exc:
            raise ImportError(
                "Arabic text libraries missing.\n"
                "Run: pip install arabic-reshaper python-bidi"
            ) from exc


class ArabicTextNormalizer:
    """
    Normalises Arabic text extracted from PDFs.

    Key operations
    ──────────────
    1. BiDi reordering  — fixes RTL text stored in visual (LTR) order by PyMuPDF.
    2. Arabic reshaping — reconnects glyphs that were split into isolated forms.
    3. Unicode NFC      — canonical decomposition + composition.
    4. Whitespace clean — collapses excessive blank lines, trims lines.
    5. Artefact removal — strips page-number patterns, running headers, etc.
    """

    # Patterns that are almost always extraction noise in Arabic books
    _NOISE_PATTERNS = [
        re.compile(r"^\s*\d+\s*$", re.MULTILINE),           # lone page numbers
        re.compile(r"[\u200b\u200c\u200d\ufeff]"),           # zero-width chars
        re.compile(r"[ \t]{3,}", re.MULTILINE),               # excessive spaces
        re.compile(r"\n{4,}", re.MULTILINE),                  # excessive blank lines
    ]

    def __init__(self, apply_bidi: bool = True, apply_reshape: bool = True):
        self.apply_bidi    = apply_bidi
        self.apply_reshape = apply_reshape
        if apply_bidi or apply_reshape:
            _load_arabic_libs()

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def normalize(self, text: str) -> str:
        """Normalize a block of extracted Arabic text."""
        if not text or not text.strip():
            return ""

        text = unicodedata.normalize("NFC", text)

        if self.apply_reshape:
            text = self._reshape_lines(text)

        if self.apply_bidi:
            text = self._bidi_lines(text)

        text = self._clean(text)
        return text.strip()

    def normalize_pages(self, pages) -> list:
        """
        Accepts a list of RawPage objects and returns them with
        raw_text replaced by normalized text (in-place mutation).
        """
        for page in pages:
            original_len = len(page.raw_text)
            page.raw_text = self.normalize(page.raw_text)
            logger.debug(
                "Page %d normalised: %d → %d chars",
                page.page_number, original_len, len(page.raw_text),
            )
        return pages

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    def _reshape_lines(self, text: str) -> str:
        config = _reshaper.ArabicReshaper(configuration={
            "delete_harakat":              False,   # preserve diacritics
            "support_ligatures":           True,
            "RIAL SIGN":                   True,
        })
        lines = text.splitlines()
        reshaped = [config.reshape(line) for line in lines]
        return "\n".join(reshaped)

    def _bidi_lines(self, text: str) -> str:
        lines = text.splitlines()
        reordered = [_get_display(line, base_dir="R") for line in lines]
        return "\n".join(reordered)

    def _clean(self, text: str) -> str:
        for pattern in self._NOISE_PATTERNS:
            if pattern.pattern == r"\n{4,}":
                text = pattern.sub("\n\n\n", text)
            elif pattern.pattern == r"[ \t]{3,}":
                text = pattern.sub("  ", text)
            else:
                text = pattern.sub("", text)
        return text
