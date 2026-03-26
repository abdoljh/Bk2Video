"""
Phase 1 — FarasaDiacritizer
Adds Harakat (diacritical marks) to normalised Arabic text before TTS.

Primary  : Farasa Diacritizer REST API (QCRI) — best MSA accuracy.
Fallback : Mishkal (local Python library) — fully offline, slightly lower accuracy.

Why diacritization matters here
────────────────────────────────
Arabic TTS engines read diacritized text far more accurately. Without Harakat,
the TTS engine must guess vowels from context — it will make mistakes on
uncommon words, names, and literary vocabulary. Adding this step is the single
highest-ROI quality improvement in the audio pipeline.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Literal

logger = logging.getLogger(__name__)

Backend = Literal["farasa", "mishkal", "auto"]

# Farasa public REST endpoint (no API key required for non-commercial use)
_FARASA_URL = "https://farasa.qcri.org/webapi/diacritize/"


class FarasaDiacritizer:
    """
    Adds Harakat to Arabic text.

    Args:
        backend: "farasa" | "mishkal" | "auto"
                 "auto" tries Farasa first; falls back to Mishkal on failure.
        farasa_api_key: Optional — if QCRI provides a key for your account.
        chunk_size: Max characters per API call (Farasa has a payload limit).
        retry_delay: Seconds to wait between retries on transient errors.
    """

    def __init__(
        self,
        backend: Backend = "auto",
        farasa_api_key: str | None = None,
        chunk_size: int = 1500,
        retry_delay: float = 1.5,
    ):
        self.backend        = backend
        self.api_key        = farasa_api_key or os.getenv("FARASA_API_KEY", "")
        self.chunk_size     = chunk_size
        self.retry_delay    = retry_delay

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def diacritize(self, text: str) -> str:
        """Return diacritized version of `text`."""
        if not text.strip():
            return text

        if self.backend == "farasa":
            return self._diacritize_farasa(text)
        elif self.backend == "mishkal":
            return self._diacritize_mishkal(text)
        else:  # auto
            try:
                result = self._diacritize_farasa(text)
                logger.info("Diacritization: Farasa succeeded.")
                return result
            except Exception as exc:  # noqa: BLE001
                logger.warning("Farasa failed (%s) — falling back to Mishkal.", exc)
                return self._diacritize_mishkal(text)

    def diacritize_pages(self, pages) -> list:
        """In-place diacritization of a list of RawPage objects."""
        for page in pages:
            if page.raw_text.strip():
                page.raw_text = self.diacritize(page.raw_text)
                logger.debug("Page %d diacritized.", page.page_number)
        return pages

    # ------------------------------------------------------------------ #
    #  Farasa backend                                                      #
    # ------------------------------------------------------------------ #

    def _diacritize_farasa(self, text: str) -> str:
        import requests  # noqa: PLC0415

        chunks  = self._split_chunks(text)
        results = []

        for i, chunk in enumerate(chunks):
            payload = {"text": chunk}
            if self.api_key:
                payload["api_key"] = self.api_key

            for attempt in range(3):
                try:
                    resp = requests.post(
                        _FARASA_URL,
                        data=payload,
                        timeout=30,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    # Farasa returns {"text": "...", ...}
                    results.append(data.get("text", chunk))
                    break
                except Exception as exc:  # noqa: BLE001
                    if attempt == 2:
                        raise
                    logger.warning("Farasa attempt %d failed: %s — retrying…", attempt + 1, exc)
                    time.sleep(self.retry_delay)

            if i < len(chunks) - 1:
                time.sleep(0.2)   # be polite to the public API

        return " ".join(results)

    # ------------------------------------------------------------------ #
    #  Mishkal fallback                                                    #
    # ------------------------------------------------------------------ #

    def _diacritize_mishkal(self, text: str) -> str:
        try:
            from mishkal.tashkeel import TashkeelClass  # noqa: PLC0415
        except ImportError as exc:
            raise ImportError(
                "Mishkal not installed. Run: pip install mishkal"
            ) from exc

        tashkeel = TashkeelClass()
        chunks   = self._split_chunks(text)
        results  = [tashkeel.tashkeel(chunk) for chunk in chunks]
        return " ".join(results)

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    def _split_chunks(self, text: str) -> list[str]:
        """Split on sentence boundaries, respecting chunk_size."""
        sentences = text.replace(".", ".\n").replace("،", "،\n").splitlines()
        chunks, current = [], ""
        for sent in sentences:
            if len(current) + len(sent) > self.chunk_size:
                if current:
                    chunks.append(current.strip())
                current = sent
            else:
                current += " " + sent
        if current.strip():
            chunks.append(current.strip())
        return chunks or [text]
