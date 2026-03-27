"""
Phase 1 — PDFIngestor
Detects whether a PDF is digitally-born or scanned, then routes to the
appropriate extraction backend.

Arabic RTL extraction strategy
────────────────────────────────
page.get_text("text") loses directionality — Arabic words come out in
visual left-to-right order. We use get_text("dict") for span-level
bounding boxes, then:

  1. Group spans into visual lines by y-coordinate.
  2. Within each line, separate punctuation-only spans from word spans.
     Punctuation (.,،؛؟!) is LTR-neutral and must be reattached to the
     word immediately to its left in the VISUAL layout (which is the
     word to its right in reading order) rather than being sorted with
     the RTL word spans.
  3. Sort word spans right-to-left (descending x).
  4. Re-attach punctuation to the correct word.
  5. Join lines into paragraphs: lines that end mid-sentence (no sentence-
     terminal punctuation) are joined with a space rather than a newline,
     so that PDF line-wrap artefacts don't fragment sentences.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

PDFType = Literal["digital", "scanned", "mixed"]

_DIGITAL_CHARS_THRESHOLD = 100

# Punctuation that is direction-neutral and must be reattached, not sorted
_PUNCT_ONLY = re.compile(r'^[\s\.,،؛؟!:\-–—()«»\[\]]+$')

# Sentence-terminal characters — a line ending with these gets a newline;
# otherwise it is joined to the next line with a space.
_SENT_TERMINAL = re.compile(r'[.؟!\n]\s*$')


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

    Digital PDFs → dict-mode extraction with RTL span reordering.
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
        Extract page text in correct RTL reading order.

        Steps
        ─────
        1. Collect spans from all text blocks via dict mode.
        2. Group into visual lines by rounded y-coordinate.
        3. Per line: separate punctuation spans from word spans.
           Sort word spans right-to-left (descending x).
           Re-attach each punctuation span to the nearest word span
           on its left in the VISUAL layout (right in reading order).
        4. Join lines: lines without a sentence-terminal character are
           soft-joined to the next line with a space to undo PDF wrapping.
        """
        data = page.get_text(
            "dict",
            flags=fitz.TEXT_PRESERVE_WHITESPACE | fitz.TEXT_MEDIABOX_CLIP,
        )

        # ── 1. Bucket spans by visual line (y rounded to 1 dp) ────────
        # Each bucket entry: (x_origin, text, is_punct)
        buckets: dict[float, list[tuple[float, str, bool]]] = {}

        for block in data.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                y_key = round(line["bbox"][1], 1)
                for span in line.get("spans", []):
                    txt = span.get("text", "")
                    if not txt.strip():
                        continue
                    x   = span["origin"][0]
                    is_punct = bool(_PUNCT_ONLY.match(txt.strip()))
                    buckets.setdefault(y_key, []).append((x, txt.strip(), is_punct))

        # ── 2. Reconstruct each line in RTL order ─────────────────────
        visual_lines: list[str] = []

        for y_key in sorted(buckets):
            spans      = buckets[y_key]
            word_spans = [(x, t) for x, t, p in spans if not p]
            punct_spans= [(x, t) for x, t, p in spans if p]

            # Sort words right-to-left
            word_spans.sort(key=lambda s: s[0], reverse=True)

            # Attach each punctuation span to the word whose visual-left
            # edge is closest (i.e. the word just to its right in reading order)
            # Build a mutable list of (x, text) for words
            words: list[list] = [[x, t] for x, t in word_spans]

            for px, pt in punct_spans:
                if not words:
                    # No words on line — append punct at end
                    words.append([px, pt])
                    continue
                # Find the word span whose x is just greater than punct x
                # (the word to the right of the punct in visual space =
                #  the word to the left in reading order, so punct trails it)
                best_idx = 0
                best_diff = float("inf")
                for idx, (wx, _) in enumerate(words):
                    diff = abs(wx - px)
                    if diff < best_diff:
                        best_diff = diff
                        best_idx = idx
                # Append punct to that word's text
                words[best_idx][1] = words[best_idx][1] + pt

            line_text = " ".join(t for _, t in words)
            visual_lines.append(line_text)

        # ── 3. Soft-join wrapped lines into paragraphs ─────────────────
        if not visual_lines:
            return ""

        paragraphs: list[str] = []
        buffer = visual_lines[0]

        for line in visual_lines[1:]:
            if _SENT_TERMINAL.search(buffer):
                # Previous line ended a sentence → hard break
                paragraphs.append(buffer)
                buffer = line
            else:
                # Mid-sentence wrap → join with space
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
