"""
Phase 3 — Wikimedia Commons image fetcher.

Uses the MediaWiki API (no API key required) to search for freely
licensed (CC / Public Domain) photographs relevant to each script
section. Pre-1928 photographs are public domain worldwide.
"""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

_API     = "https://commons.wikimedia.org/w/api.php"
_HEADERS = {"User-Agent": "Bk2Video/1.0 (https://github.com/abdoljh/Bk2Video; bot)"}

# CirrusSearch exclusions appended to every query to keep out diagrams and
# anatomical illustrations.  Do NOT exclude -manuscript or -drawing — those
# terms also block legitimate historical photographs.
_SEARCH_EXCLUSIONS = "-diagram -anatomy -chart -schematic"

# Minimum acceptable dimension in pixels — rejects postage-stamp thumbnails.
_MIN_DIMENSION = 400

# License short-names we accept (case-insensitive prefix match)
_FREE_PREFIXES = ("cc-", "cc0", "pd", "public domain", "attribution")
# Sub-strings that mark non-free licenses
_NONFREE_TERMS = ("nc", "nd", "non-commercial", "no derivative", "no deriv")


@dataclass
class WikiImage:
    title: str
    thumb_url: str
    license_short: str
    width: int
    height: int


# ── API helpers ─────────────────────────────────────────────────────────── #

def _api_get(params: dict) -> dict:
    params["format"] = "json"
    url = _API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


def _is_free(license_str: str) -> bool:
    ls = license_str.lower().strip()
    if any(t in ls for t in _NONFREE_TERMS):
        return False
    return any(ls.startswith(p) for p in _FREE_PREFIXES) or ls == ""


def _ext_from_url(url: str) -> str:
    path = urllib.parse.urlparse(url).path.lower().split("?")[0]
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"):
        if path.endswith(ext):
            return ".jpg" if ext == ".jpeg" else ext
    return ".jpg"


# ── Public interface ─────────────────────────────────────────────────────── #

def search_images(
    query: str,
    limit: int = 10,
    thumb_width: int = 1280,
) -> list[WikiImage]:
    """
    Search Wikimedia Commons for freely licensed bitmap images.

    Returns up to `limit` WikiImage objects with thumbnail URLs
    at approximately `thumb_width` pixels wide.
    """
    try:
        data = _api_get({
            "action":      "query",
            "generator":   "search",
            "gsrsearch":   f"{query} filetype:bitmap {_SEARCH_EXCLUSIONS}",
            "gsrnamespace": "6",                    # File: namespace
            "gsrlimit":    str(min(limit * 3, 30)), # over-fetch, then filter
            "prop":        "imageinfo",
            "iiprop":      "url|size|extmetadata|mime",
            "iiurlwidth":  str(thumb_width),
        })
    except Exception as exc:
        log.warning("Wikimedia search failed for %r: %s", query, exc)
        return []

    pages = data.get("query", {}).get("pages", {})
    results: list[WikiImage] = []

    for page in pages.values():
        ii_list = page.get("imageinfo", [])
        if not ii_list:
            continue
        ii = ii_list[0]

        # Only bitmap images
        mime = ii.get("mime", "")
        if not mime.startswith("image/") or "gif" in mime:
            continue

        # Prefer thumbnail URL; fall back to original
        url = ii.get("thumburl") or ii.get("url", "")
        if not url:
            continue

        # License check
        meta    = ii.get("extmetadata", {})
        lic_val = meta.get("LicenseShortName", {})
        lic     = lic_val.get("value", "") if isinstance(lic_val, dict) else ""
        if not _is_free(lic):
            continue

        # Skip images that are too small to look good on 720p video
        orig_w = ii.get("thumbwidth") or ii.get("width", 0)
        orig_h = ii.get("thumbheight") or ii.get("height", 0)
        if orig_w < _MIN_DIMENSION or orig_h < _MIN_DIMENSION:
            continue

        results.append(WikiImage(
            title=page.get("title", ""),
            thumb_url=url,
            license_short=lic,
            width=ii.get("thumbwidth") or ii.get("width", 0),
            height=ii.get("thumbheight") or ii.get("height", 0),
        ))

        if len(results) >= limit:
            break

    return results


def download_images(
    images: list[WikiImage],
    dest_dir: Path,
    prefix: str = "wiki",
) -> list[Path]:
    """
    Download a list of WikiImage thumbnails to dest_dir.
    Skips any that fail. Returns paths of successfully saved files.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    for i, img in enumerate(images):
        ext  = _ext_from_url(img.thumb_url)
        dest = dest_dir / f"{prefix}_{i:02d}{ext}"
        try:
            req = urllib.request.Request(img.thumb_url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
            if len(data) < 1024:        # skip suspiciously small files
                log.debug("Skipping tiny file for %s", img.title)
                continue
            dest.write_bytes(data)
            paths.append(dest)
            log.debug("Wikimedia ↓ %s → %s", img.title[:60], dest.name)
        except Exception as exc:
            log.warning("Failed to download %s: %s", img.thumb_url[:80], exc)

    return paths


def fetch_section_images(
    queries: list[str],
    dest_dir: Path,
    n_per_query: int = 2,
    max_total: int = 4,
) -> list[Path]:
    """
    Try each query in sequence until `max_total` images are collected.
    Downloads them and returns their local paths.
    """
    collected: list[WikiImage] = []

    for query in queries:
        if len(collected) >= max_total:
            break
        remaining = max_total - len(collected)
        imgs = search_images(query, limit=min(n_per_query + 2, remaining + 2))
        collected.extend(imgs[:remaining])

    if not collected:
        log.info("No Wikimedia images found for queries: %s", queries)
        return []

    return download_images(collected[:max_total], dest_dir)
