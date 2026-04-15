"""
Phase 3 — Per-section visual keyword generator.

Uses Claude Haiku to produce Wikimedia Commons + Pexels search terms
for each script section, given the section text and book genre.
Falls back to genre-based defaults if the API call fails.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from .parser import ScriptSection

log = logging.getLogger(__name__)

_SYSTEM = (
    "You generate visual search keywords for Arabic book summary videos. "
    "Return ONLY valid JSON — no markdown fences, no explanation."
)

_USER_TMPL = """\
Book title: {book_title}
Main character / subject: {character_name}
Book genre: {genre}
Section ID: {section_id}
Section title: {title}
Section text (first 400 chars): {excerpt}

Generate two keyword lists to find compelling visuals for this section:
1. "wikimedia": 3-4 specific search terms for Wikimedia Commons historical/documentary photographs
2. "pexels":    2-3 cinematic search terms for Pexels stock video footage

Rules:
- Terms must be in English (Wikimedia and Pexels index in English)
- For history/biography genres prefer real historical photographs of people and places
- If a main character is named, the FIRST wikimedia term must be the character's full name
  (e.g. "Jafar al-Askari" or "Jafar Pasha") to retrieve a portrait photograph
- Be specific: "Arab Revolt 1916" beats "revolution"; "Jafar al-Askari 1921" beats "Arab officer"
- NEVER use a single generic word alone — always combine with a person, place, event, or year:
  BAD: "horse", "army", "soldier"   GOOD: "Arab cavalry 1916", "Ottoman officer uniform WWI"
- Avoid terms that return anatomical diagrams, manuscript illustrations, or charts
- Pexels terms should be cinematic: "desert landscape dawn", "Baghdad historical"

Return ONLY this JSON (no other text):
{{"wikimedia": ["...", "..."], "pexels": ["...", "..."]}}"""


@dataclass
class KeywordSet:
    section_id: str
    wikimedia: list[str]
    pexels: list[str]


def generate_keywords(
    sections: list[ScriptSection],
    genre: str,
    anthropic_api_key: str,
    book_title: str = "",
    character_name: str = "",
) -> list[KeywordSet]:
    """
    Call Claude Haiku once per section to produce per-section keyword sets.
    Falls back to genre-based defaults on any failure.
    """
    from anthropic import Anthropic

    client = Anthropic(api_key=anthropic_api_key)
    results: list[KeywordSet] = []

    for section in sections:
        try:
            prompt = _USER_TMPL.format(
                book_title=book_title or "unknown",
                character_name=character_name or "not specified",
                genre=genre,
                section_id=section.section_id,
                title=section.title,
                excerpt=section.text[:400],
            )
            msg = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=300,
                system=_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = msg.content[0].text.strip()
            # Strip accidental markdown fences
            raw = (raw
                   .removeprefix("```json")
                   .removeprefix("```")
                   .removesuffix("```")
                   .strip())
            data = json.loads(raw)
            results.append(KeywordSet(
                section_id=section.section_id,
                wikimedia=data.get("wikimedia", [])[:4],
                pexels=data.get("pexels", [])[:3],
            ))
            log.debug("Keywords for %s: %s", section.section_id, data)
        except Exception as exc:
            log.warning("Keyword gen failed for '%s': %s", section.section_id, exc)
            results.append(_fallback(section, genre))

    return results


# ── Fallback keyword sets by genre ──────────────────────────────────────── #
_FALLBACKS: dict[str, dict[str, list[str]]] = {
    "history": {
        "wikimedia": ["Arabic history photograph", "Ottoman Empire", "historical Arab"],
        "pexels":    ["history", "ancient ruins"],
    },
    "biography": {
        "wikimedia": ["historical portrait", "Arab leader photograph"],
        "pexels":    ["biography", "person contemplating"],
    },
    "non-fiction": {
        "wikimedia": ["book library historical", "Arabic manuscript"],
        "pexels":    ["library", "reading"],
    },
    "philosophy": {
        "wikimedia": ["Islamic philosophy manuscript", "Arabic calligraphy"],
        "pexels":    ["philosophy", "thinking"],
    },
    "science": {
        "wikimedia": ["Arabic science manuscript", "Islamic golden age"],
        "pexels":    ["science", "discovery"],
    },
    "religion": {
        "wikimedia": ["Islamic art calligraphy", "mosque architecture"],
        "pexels":    ["mosque", "spiritual"],
    },
    "novel": {
        "wikimedia": ["Arabic literature", "storytelling art"],
        "pexels":    ["storytelling", "dramatic"],
    },
}
_DEFAULT_FALLBACK = {
    "wikimedia": ["Arabic manuscript", "book", "library historical"],
    "pexels":    ["library", "books"],
}


def _fallback(section: ScriptSection, genre: str) -> KeywordSet:
    kw = _FALLBACKS.get(genre, _DEFAULT_FALLBACK)
    return KeywordSet(
        section_id=section.section_id,
        wikimedia=list(kw["wikimedia"]),
        pexels=list(kw["pexels"]),
    )
