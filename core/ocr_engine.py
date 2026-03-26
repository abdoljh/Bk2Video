"""
Phase 1 — OCREngine
Runs EasyOCR (primary) or Tesseract (fallback) on scanned page images.
Both support Arabic with right-to-left text.
"""

from __future__ import annotations

import logging
from enum import Enum, auto
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .ingestor import RawPage

logger = logging.getLogger(__name__)


class OCRBackend(Enum):
    EASYOCR   = auto()
    TESSERACT = auto()


class OCREngine:
    """
    Fills in `raw_text` for pages that were flagged as scanned by PDFIngestor.

    EasyOCR is preferred — it handles Arabic script without extra config and
    has better accuracy on noisy scans. Tesseract is kept as a fallback for
    environments where EasyOCR's GPU/model download is not feasible.

    Usage::

        engine = OCREngine(backend=OCRBackend.EASYOCR)
        pages  = engine.process_pages(ingestion_result.pages)
    """

    def __init__(
        self,
        backend: OCRBackend = OCRBackend.EASYOCR,
        gpu: bool = False,
    ):
        self.backend = backend
        self.gpu = gpu
        self._reader = None   # lazy-loaded

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def process_pages(self, pages: list[RawPage]) -> list[RawPage]:
        """
        Returns the same list with `raw_text` populated for scanned pages.
        Digital pages are passed through unchanged.
        """
        scanned = [p for p in pages if p.pdf_type == "scanned"]
        if not scanned:
            logger.info("No scanned pages — OCR skipped.")
            return pages

        logger.info("Running OCR on %d scanned page(s) via %s …", len(scanned), self.backend.name)
        ocr_fn = self._easyocr_page if self.backend == OCRBackend.EASYOCR else self._tesseract_page
        self._lazy_init()

        for page in scanned:
            if page.image_bytes:
                page.raw_text = ocr_fn(page.image_bytes)
                logger.debug("Page %d OCR'd — %d chars", page.page_number, len(page.raw_text))

        return pages

    # ------------------------------------------------------------------ #
    #  Backends                                                            #
    # ------------------------------------------------------------------ #

    def _lazy_init(self):
        if self._reader is not None:
            return
        if self.backend == OCRBackend.EASYOCR:
            try:
                import easyocr  # noqa: PLC0415
                # 'ar' = Arabic; also load 'en' so mixed pages work
                self._reader = easyocr.Reader(["ar", "en"], gpu=self.gpu)
                logger.info("EasyOCR reader initialised (gpu=%s).", self.gpu)
            except ImportError as exc:
                raise ImportError(
                    "EasyOCR not installed. Run: pip install easyocr"
                ) from exc
        else:
            try:
                import pytesseract  # noqa: PLC0415 (just verify it's available)
                self._reader = pytesseract
                logger.info("Tesseract reader initialised.")
            except ImportError as exc:
                raise ImportError(
                    "pytesseract not installed. Run: pip install pytesseract"
                ) from exc

    def _easyocr_page(self, image_bytes: bytes) -> str:
        import numpy as np  # noqa: PLC0415
        from PIL import Image  # noqa: PLC0415

        img = Image.open(__import__("io").BytesIO(image_bytes)).convert("RGB")
        arr = np.array(img)
        results = self._reader.readtext(arr, detail=0, paragraph=True)
        return "\n".join(results)

    def _tesseract_page(self, image_bytes: bytes) -> str:
        from PIL import Image  # noqa: PLC0415

        img = Image.open(__import__("io").BytesIO(image_bytes))
        # osd+ara: auto-detect orientation + Arabic language
        return self._reader.image_to_string(img, lang="ara", config="--psm 3")
