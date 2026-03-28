"""
Phase 1 — Pipeline
Top-level orchestrator. Captures a raw-text snapshot after extraction
(before normalisation/diacritization) so both versions are saved.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .core.ingestor      import PDFIngestor
from .core.ocr_engine    import OCREngine, OCRBackend
from .core.normalizer    import ArabicTextNormalizer
from .core.diacritizer   import FarasaDiacritizer
from .core.chunker       import SemanticChunker, Chunk
from .core.output_writer import OutputWriter

logger = logging.getLogger(__name__)


@dataclass
class Phase1Config:
    ocr_gpu:        bool   = False
    ocr_backend:    str    = "easyocr"
    ocr_dpi:        int    = 200
    diacritize:     bool   = True
    diac_backend:   str    = "auto"
    farasa_api_key: str    = ""
    max_tokens:     int    = 1500
    overlap_tokens: int    = 200
    output_dir:     str    = "output"


@dataclass
class Phase1Result:
    source_path:  str
    pdf_type:     str
    total_pages:  int
    chunks:       list[Chunk]
    json_path:    Path
    txt_path:     Path
    raw_txt_path: Path          # ← new: pre-processing snapshot
    elapsed_sec:  float
    warnings:     list[str] = field(default_factory=list)


class Phase1Pipeline:

    def __init__(
        self,
        config: Phase1Config | None = None,
        on_progress: Callable[[str, float], None] | None = None,
    ):
        self.cfg         = config or Phase1Config()
        self.on_progress = on_progress or (lambda s, p: None)

    def run(self, pdf_path: str | Path) -> Phase1Result:
        t0       = time.perf_counter()
        warnings = []

        # ── Step 1: Ingest ───────────────────────────────────────────── #
        self._progress("Ingesting PDF …", 0.0)
        ingestor  = PDFIngestor(dpi=self.cfg.ocr_dpi)
        ingestion = ingestor.ingest(pdf_path)
        logger.info("PDF type: %s (%d pages)", ingestion.pdf_type, ingestion.total_pages)

        # ── Step 2: OCR (scanned pages only) ─────────────────────────── #
        self._progress("Running OCR on scanned pages …", 0.18)
        has_scanned = any(p.pdf_type == "scanned" for p in ingestion.pages)
        if has_scanned:
            backend = OCRBackend.EASYOCR if self.cfg.ocr_backend == "easyocr" else OCRBackend.TESSERACT
            ocr = OCREngine(backend=backend, gpu=self.cfg.ocr_gpu)
            try:
                ingestion.pages = ocr.process_pages(ingestion.pages)
            except ImportError as exc:
                warnings.append(f"OCR skipped — library missing: {exc}")
                logger.warning(warnings[-1])

        # ── Snapshot: capture raw text BEFORE any text processing ─────── #
        # For scanned pages the OCR output is the raw baseline;
        # for digital pages it was already stored in raw_text_pre by ingestor.
        # Here we ensure scanned pages also get their pre-norm snapshot.
        for page in ingestion.pages:
            if page.pdf_type == "scanned" and not page.raw_text_pre:
                page.raw_text_pre = page.raw_text   # OCR output = raw baseline

        # ── Step 3: Normalise ─────────────────────────────────────────── #
        self._progress("Normalising Arabic text …", 0.40)
        normalizer = ArabicTextNormalizer()
        ingestion.pages = normalizer.normalize_pages(ingestion.pages)

        # ── Step 4: Diacritize ────────────────────────────────────────── #
        if self.cfg.diacritize:
            self._progress("Diacritizing (adding Harakat) …", 0.58)
            diacritizer = FarasaDiacritizer(
                backend        = self.cfg.diac_backend,
                farasa_api_key = self.cfg.farasa_api_key,
            )
            try:
                ingestion.pages = diacritizer.diacritize_pages(ingestion.pages)
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"Diacritization failed — skipped: {exc}")
                logger.warning(warnings[-1])

        # ── Step 5: Chunk ─────────────────────────────────────────────── #
        self._progress("Chunking into LLM-ready pieces …", 0.76)
        chunker = SemanticChunker(
            max_tokens     = self.cfg.max_tokens,
            overlap_tokens = self.cfg.overlap_tokens,
        )
        chunks = chunker.chunk_pages(ingestion.pages)

        # ── Step 6: Write output ──────────────────────────────────────── #
        self._progress("Writing output files …", 0.90)
        writer = OutputWriter(output_dir=self.cfg.output_dir)
        json_path, txt_path, raw_txt_path = writer.write(ingestion, chunks)

        elapsed = time.perf_counter() - t0
        self._progress("Done ✓", 1.0)
        logger.info("Phase 1 complete in %.1fs — %d chunks.", elapsed, len(chunks))

        return Phase1Result(
            source_path  = str(pdf_path),
            pdf_type     = ingestion.pdf_type,
            total_pages  = ingestion.total_pages,
            chunks       = chunks,
            json_path    = json_path,
            txt_path     = txt_path,
            raw_txt_path = raw_txt_path,
            elapsed_sec  = elapsed,
            warnings     = warnings,
        )

    def _progress(self, step: str, pct: float):
        logger.debug("[%.0f%%] %s", pct * 100, step)
        self.on_progress(step, pct)
