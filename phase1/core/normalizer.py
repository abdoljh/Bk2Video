"""
Phase 1 — ArabicTextNormalizer
Cleans normalised Arabic text after RTL-correct extraction.

After the ingestor fix (dict-mode span reordering), digital PDF text
arrives in correct logical RTL order — no bidi manipulation needed.
Scanned/OCR text still needs reshape + bidi because EasyOCR/Tesseract
return isolated glyphs in visual LTR order.

Pipeline by source
──────────────────
  digital  →  NFC  →  clean
  scanned  →  NFC  →  reshape  →  bidi  →  clean
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
    Source-aware Arabic text normaliser.

    digital: NFC + clean only  (ingestor already delivers correct order)
    scanned: NFC + reshape + bidi + clean
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

        text = unicodedata.normalize("NFC", text)

        if source == "scanned":
            _load_arabic_libs()
            cfg = _reshaper.ArabicReshaper(configuration={
                "delete_harakat":    False,
                "support_ligatures": True,
            })
            text = "\n".join(cfg.reshape(line) for line in text.splitlines())
            text = "\n".join(
                _get_display(line, base_dir="R") for line in text.splitlines()
            )

        return self._clean(text).strip()

    def normalize_pages(self, pages: list) -> list:
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
