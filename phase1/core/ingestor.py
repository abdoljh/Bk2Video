"""
Phase 1 — PDFIngestor
Detects whether a PDF is digitally-born or scanned, then routes to the
appropriate extraction backend.

Arabic RTL extraction — known PDF rendering artefacts handled
──────────────────────────────────────────────────────────────
1. Presentation Forms ligatures (U+FB50–U+FDFF, U+FE70–U+FEFF)
   PDF renderers store lam-alef and similar ligatures as single glyphs
   from the Arabic Presentation Forms blocks.  These must be mapped back
   to their canonical two-character sequences BEFORE any further processing:
     ﻷ (U+FBB7 lam+alef-hamza-above) → لأ
     ﻹ (lam+alef-hamza-below)         → لإ
     ﻻ (lam+alef)                     → لا
     ﻼ (lam+alef+shadda)              → لا + shadda
     ﺍ isolated alef forms            → ا  etc.
   unicodedata.normalize("NFKC") handles the bulk of these.

2. Word-order reversal
   get_text("dict") gives spans in visual left-to-right order.
   We sort word spans right-to-left (descending x) per line.

3. Punctuation attachment
   Punctuation spans are direction-neutral.  We determine whether each
   punctuation span trails (follows in reading order) its neighbouring
   word by comparing x-positions:
     - punct x  <  word x  →  punct is to the LEFT visually
                            →  in RTL it FOLLOWS the word  →  append
     - punct x  >  word x  →  punct is to the RIGHT visually
                            →  in RTL it PRECEDES the word →  prepend

4. Soft line-joining
   PDF layout wraps lines at the page margin.  Lines that do not end
   with a sentence-terminal character are joined to the next with a
   space.  Genuine paragraph breaks (blank lines in the source) produce
   double newlines in the output so the chunker can detect them.
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

# Spans that are purely punctuation / whitespace (no Arabic letters)
_PUNCT_ONLY = re.compile(r'^[\s\.,،؛؟!:\-–—()\[\]«»"\']+$')

# A line ends a sentence if its last non-space character is one of these
_SENT_TERMINAL = re.compile(r'[.؟!]\s*$')

# Arabic Presentation Forms that NFKC does not fully resolve
# Maps single ligature code points → canonical string
_LIGATURE_MAP: dict[str, str] = {
    '\uFB50': 'ا',   # ARABIC LETTER ALEF WASLA ISOLATED FORM
    '\uFB51': 'ا',
    '\uFB52': 'ب',   '\uFB53': 'ب', '\uFB54': 'ب', '\uFB55': 'ب',
    '\uFB56': 'پ',   '\uFB57': 'پ', '\uFB58': 'پ', '\uFB59': 'پ',
    '\uFB6A': 'و',   '\uFB6B': 'و',
    '\uFB70': 'ڈ',
    '\uFB8A': 'ژ',   '\uFB8B': 'ژ',
    '\uFB8C': 'ر',
    '\uFB8E': 'ک',   '\uFB8F': 'ک', '\uFB90': 'ک', '\uFB91': 'ک',
    '\uFB92': 'گ',   '\uFB93': 'گ', '\uFB94': 'گ', '\uFB95': 'گ',
    '\uFBFC': 'ی',   '\uFBFD': 'ی', '\uFBFE': 'ی', '\uFBFF': 'ی',
    # Lam-Alef ligatures (the most common source of ألـ / املـ artefacts)
    '\uFEF5': 'لآ',  # LAM WITH ALEF WITH MADDA ABOVE
    '\uFEF6': 'لآ',
    '\uFEF7': 'لأ',  # LAM WITH ALEF WITH HAMZA ABOVE  ← fixes ألدوات→الأدوات
    '\uFEF8': 'لأ',
    '\uFEF9': 'لإ',  # LAM WITH ALEF WITH HAMZA BELOW
    '\uFEFA': 'لإ',
    '\uFEFB': 'لا',  # LAM WITH ALEF  ← fixes املعنى→المعنى
    '\uFEFC': 'لا',
}

# Build a single translation table for fast replacement
_LIGATURE_TABLE = str.maketrans(_LIGATURE_MAP)


def _normalize_presentation_forms(text: str) -> str:
    """
    Two-pass normalisation of Arabic Presentation Forms:
    1. NFKC handles most compatibility decompositions.
    2. Manual table for lam-alef ligatures that NFKC leaves intact.
    """
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(_LIGATURE_TABLE)
    return text


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
    #  RTL-aware text extraction                                           #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _extract_rtl_text(page: fitz.Page) -> str:
        """
        Extract page text in correct RTL reading order with ligatures resolved.
        """
        data = page.get_text(
            "dict",
            flags=fitz.TEXT_PRESERVE_WHITESPACE | fitz.TEXT_MEDIABOX_CLIP,
        )

        # ── Step 1: Collect spans bucketed by visual line (y rounded) ──
        # Each entry: (x_origin, text, is_punct)
        buckets: dict[float, list[tuple[float, str, bool]]] = {}

        for block in data.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                y_key = round(line["bbox"][1], 1)
                for span in line.get("spans", []):
                    raw = span.get("text", "")
                    if not raw.strip():
                        continue
                    # Resolve ligatures immediately at extraction
                    txt      = _normalize_presentation_forms(raw.strip())
                    x        = span["origin"][0]
                    is_punct = bool(_PUNCT_ONLY.match(txt))
                    buckets.setdefault(y_key, []).append((x, txt, is_punct))

        # ── Step 2: Reconstruct each visual line in RTL reading order ──
        visual_lines: list[str] = []

        for y_key in sorted(buckets):
            entries    = buckets[y_key]
            word_spans = [(x, t) for x, t, p in entries if not p]
            punct_spans= [(x, t) for x, t, p in entries if p]

            # Sort word spans right-to-left
            word_spans.sort(key=lambda s: s[0], reverse=True)
            words: list[list] = [[x, t] for x, t in word_spans]

            if not words:
                # Punct-only line — just emit it
                visual_lines.append(" ".join(t for _, t, _ in entries))
                continue

            # Attach punctuation based on visual position:
            #   punct visually LEFT of nearest word  → append (follows in RTL)
            #   punct visually RIGHT of nearest word → prepend (precedes in RTL)
            for px, pt in punct_spans:
                # Find nearest word by x distance
                nearest_idx  = min(range(len(words)), key=lambda i: abs(words[i][0] - px))
                nearest_x    = words[nearest_idx][0]

                if px < nearest_x:
                    # Punct is to the LEFT of the word visually
                    # → it follows the word in RTL reading order → append
                    words[nearest_idx][1] = words[nearest_idx][1] + pt
                else:
                    # Punct is to the RIGHT of the word visually
                    # → it precedes the word in RTL reading order → prepend
                    words[nearest_idx][1] = pt + words[nearest_idx][1]

            line_text = " ".join(t for _, t in words)
            visual_lines.append(line_text)

        # ── Step 3: Soft-join mid-sentence line wraps ──────────────
        # Rules:
        #   a) Short line (<=60 chars, no sentence punct) -> heading.
        #      Wrap with blank lines so the chunker sees paragraph breaks.
        #   b) Line ending with . ? ! -> sentence end -> single newline.
        #   c) Everything else -> wrap continuation -> join with space.
        if not visual_lines:
            return ""

        _IS_HEADING = re.compile(r'^(?!.*[.،؛؟!]).{4,60}$')

        def is_heading(s: str) -> bool:
            s = s.strip()
            return bool(_IS_HEADING.match(s)) and len(s) <= 60

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
