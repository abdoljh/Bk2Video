"""
Phase 1 — OutputWriter
Serialises Phase 1 results to both JSON (structured) and plain text formats.

JSON schema
───────────
{
  "source":       "book.pdf",
  "pdf_type":     "digital" | "scanned" | "mixed",
  "total_pages":  int,
  "metadata":     { title, author, subject, creator, pages },
  "chunks": [
    {
      "chunk_id":   int,
      "chapter":    str,
      "page_start": int,
      "page_end":   int,
      "word_count": int,
      "token_est":  int,
      "text":       str          ← normalised + diacritized
    },
    …
  ]
}

Plain text
──────────
A human-readable file with chapter markers and chunk separators,
suitable as a diff-able audit trail or direct downstream input.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .chunker import Chunk
    from .ingestor import IngestionResult

logger = logging.getLogger(__name__)

_CHUNK_SEPARATOR = "\n" + "─" * 60 + "\n"


class OutputWriter:
    """
    Writes Phase 1 output to disk.

    Args:
        output_dir: Directory where output files are written.
                    Created automatically if it does not exist.
    """

    def __init__(self, output_dir: str | Path = "output"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def write(
        self,
        ingestion: IngestionResult,
        chunks: list[Chunk],
        stem: str | None = None,
    ) -> tuple[Path, Path]:
        """
        Write both output formats and return (json_path, txt_path).

        Args:
            ingestion: Result from PDFIngestor.ingest().
            chunks:    Result from SemanticChunker.chunk_pages().
            stem:      Base filename without extension. Defaults to PDF stem.
        """
        base = stem or Path(ingestion.source_path).stem
        json_path = self.output_dir / f"{base}_phase1.json"
        txt_path  = self.output_dir / f"{base}_phase1.txt"

        self._write_json(ingestion, chunks, json_path)
        self._write_txt(ingestion, chunks, txt_path)

        logger.info("Phase 1 output written → %s, %s", json_path, txt_path)
        return json_path, txt_path

    # ------------------------------------------------------------------ #
    #  JSON                                                                #
    # ------------------------------------------------------------------ #

    def _write_json(
        self,
        ingestion: IngestionResult,
        chunks: list[Chunk],
        path: Path,
    ) -> None:
        payload = {
            "source":      ingestion.source_path,
            "pdf_type":    ingestion.pdf_type,
            "total_pages": ingestion.total_pages,
            "metadata":    ingestion.metadata,
            "chunk_count": len(chunks),
            "chunks": [
                {
                    "chunk_id":   c.chunk_id,
                    "chapter":    c.chapter,
                    "page_start": c.page_start,
                    "page_end":   c.page_end,
                    "word_count": c.word_count,
                    "token_est":  c.token_est,
                    "text":       c.text,
                }
                for c in chunks
            ],
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------ #
    #  Plain text                                                          #
    # ------------------------------------------------------------------ #

    def _write_txt(
        self,
        ingestion: IngestionResult,
        chunks: list[Chunk],
        path: Path,
    ) -> None:
        lines = [
            f"# Phase 1 Output — {Path(ingestion.source_path).name}",
            f"# PDF Type   : {ingestion.pdf_type}",
            f"# Total pages: {ingestion.total_pages}",
            f"# Chunks     : {len(chunks)}",
            f"# Title      : {ingestion.metadata.get('title', 'N/A')}",
            f"# Author     : {ingestion.metadata.get('author', 'N/A')}",
            "",
        ]

        for chunk in chunks:
            lines.append(
                f"[Chunk {chunk.chunk_id:04d} | {chunk.chapter} | "
                f"pp. {chunk.page_start}–{chunk.page_end} | "
                f"{chunk.word_count} words / ~{chunk.token_est} tokens]"
            )
            lines.append(chunk.text)
            lines.append(_CHUNK_SEPARATOR)

        path.write_text("\n".join(lines), encoding="utf-8")
