"""
Phase 2 — Text-to-Speech module.

Backends
--------
gtts        Google TTS (gTTS). Free, no API key required.
            Arabic support via lang='ar'. Output: MP3.
            Use for development and cost minimisation during testing.

elevenlabs  ElevenLabs API. Premium Arabic voices (e.g. Chaouki).
            Requires API key + voice ID.
            Planned for production use — not yet implemented.
"""

from __future__ import annotations

import io
from typing import Literal

TtsBackend = Literal["gtts", "elevenlabs"]


def synthesize_gtts(text: str) -> bytes:
    """Synthesize Arabic text to MP3 via Google TTS. Returns MP3 bytes."""
    from gtts import gTTS  # lazy import — keeps app startup fast when unused

    buf = io.BytesIO()
    gTTS(text=text, lang="ar", slow=False).write_to_fp(buf)
    return buf.getvalue()


def synthesize(
    text: str,
    backend: TtsBackend = "gtts",
    *,
    elevenlabs_api_key: str = "",
    elevenlabs_voice_id: str = "",
) -> bytes:
    """
    Synthesize Arabic script text to MP3.

    Parameters
    ----------
    text                  Arabic script (plain or diacritized).
    backend               'gtts' or 'elevenlabs'.
    elevenlabs_api_key    Required for 'elevenlabs' backend.
    elevenlabs_voice_id   Required for 'elevenlabs' backend.

    Returns
    -------
    bytes — MP3 audio.
    """
    if backend == "gtts":
        return synthesize_gtts(text)

    if backend == "elevenlabs":
        raise NotImplementedError(
            "ElevenLabs integration is planned for a later Phase 2 sprint. "
            "Select gTTS for development use."
        )

    raise ValueError(f"Unknown TTS backend: {backend!r}")
