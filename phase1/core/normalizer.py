"""
Phase 1 — ArabicTextNormalizer
Post-extraction text normalisation.

Applies:
  1. fix_article()  — repairs lam-alef encoding errors from PDF font ToUnicode tables.
  2. Scanned-only:  arabic-reshaper + python-bidi (OCR output only).
  3. Noise cleaning — lone page numbers, zero-width chars, excessive whitespace.

fix_article rules
─────────────────
Arabic PDF fonts frequently encode the lam-alef ligature glyph incorrectly,
producing words like:
  امل   instead of  الم   (plain alef + consonant + lam → swap consonant and lam)
  اآلن  instead of  الآن  (alef + madda-alef + lam → swap last two)
  ألدوات instead of الأدوات (hamza-alef + lam + consonant → insert plain alef)
  ألي    instead of لأي    (short hamza-alef + lam → swap)

Known limitation: the root-internal case اإلعالمية → الإعالمية (not الإعلامية)
cannot be fixed without a lexicon. The output is readable.
"""

from __future__ import annotations

import re
import unicodedata
import logging
from typing import Literal

logger = logging.getLogger(__name__)

Source = Literal["digital", "scanned"]

# ── Arabic character constants ──────────────────────────────────────── #
_ALEF     = '\u0627'   # ا
_ALEF_HA  = '\u0623'   # أ
_ALEF_HB  = '\u0625'   # إ
_ALEF_MA  = '\u0622'   # آ
_LAM      = '\u0644'   # ل
_ALL_ALEF = {_ALEF, _ALEF_HA, _ALEF_HB, _ALEF_MA}

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
        raise ImportError("Run: pip install arabic-reshaper python-bidi") from exc


def fix_article(word: str) -> str:
    """
    Fix lam-alef article encoding errors from Arabic PDF font ToUnicode tables.

    Rule B — word starts with [hamza/madda-alef][lam]:
      len==2:                    swap  (standalone أل → لأ)
      len==3 + إ at pos 0:       leave alone  (إلى, إلا are prepositions)
      len==3 + أ/آ at pos 0:     swap  (ألي → لأي)
      len≥4 + alef after lam:    insert plain alef  (اإل → الإ)
      len≥4 + consonant after:   insert plain alef  (ألدوات → الأدوات)

    Rule A — word starts with [ا][non-lam][ل] at positions 0,1,2 → swap 1 and 2:
      Fixes: امل→الم, اآلن→الآن, اإلنترنت→الإنترنت
      Restricted to word-START only (positions 0-2) to avoid corrupting
      genuine Arabic roots like كامل, عامل that contain ا+م+ل internally.

    Standalone "ال" → "لا"  (negation/emphasis particle).

    Known limitation: inner root-level لا encoding in compound words like
    الإعلامية cannot be fixed without a lexicon (produces الإعالمية).
    """
    if len(word) < 2:
        return word
    c = list(word)

    # Rule B
    if c[0] in (_ALEF_HA, _ALEF_HB, _ALEF_MA) and c[1] == _LAM:
        after_lam = c[2] if len(c) > 2 else None
        if len(word) == 2:
            c[0], c[1] = c[1], c[0]                      # standalone → swap
        elif len(word) == 3:
            if c[0] != _ALEF_HB:                          # إ = preposition → leave
                c[0], c[1] = c[1], c[0]                  # أ/آ → swap (ألي → لأي)
        else:
            c = [_ALEF, _LAM] + c[0:1] + c[2:]           # long → insert plain alef

    # Rule A — word-start ONLY (positions 0,1,2)
    if len(c) >= 3 and c[0] == _ALEF and c[1] != _LAM and c[2] == _LAM:
        c[1], c[2] = c[2], c[1]

    # Standalone ال → لا
    if len(c) == 2 and c[0] == _ALEF and c[1] == _LAM:
        c[0], c[1] = c[1], c[0]

    return ''.join(c)


class ArabicTextNormalizer:
    """
    Source-aware Arabic text normaliser.

    digital: fix_article per word + NFC + noise clean
    scanned: fix_article per word + NFC + reshape + bidi + noise clean
    """

    _NOISE_PATTERNS = [
        re.compile(r"^\s*\d+\s*$", re.MULTILINE),
        re.compile(r"[\u200b\u200c\u200d\ufeff]"),
        re.compile(r"[ \t]{3,}", re.MULTILINE),
        re.compile(r"\n{4,}", re.MULTILINE),
    ]

    def normalize(self, text: str, source: Source = "digital") -> str:
        if not text or not text.strip():
            return ""

        text = unicodedata.normalize("NFC", text)

        # Apply article fix word-by-word
        text = " ".join(fix_article(w) for w in text.split(" "))

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
            logger.debug("Page %d [%s] normalised: %d → %d chars",
                         page.page_number, source, before, len(page.raw_text))
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
