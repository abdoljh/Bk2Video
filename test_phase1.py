#!/usr/bin/env python3
"""
Standalone Phase 1 test — runs the full pipeline without Streamlit.

Pipeline: pdf2image (300 DPI) → Tesseract OCR → Claude Haiku correction
          → Arabic normalizer → chunker → (optional) script generation

Usage:
    python test_phase1.py <pdf_path> [options]

    # Extract + LLM correction only (no script):
    python test_phase1.py output/ph1/page_5.pdf

    # Full pipeline including script generation:
    python test_phase1.py output/ph1/pages_5_22.pdf --script

    # Skip LLM correction (Tesseract only):
    python test_phase1.py output/ph1/page_5.pdf --no-correction

Environment variables:
    ANTHROPIC_API_KEY   Required for LLM correction and script generation.
"""

import argparse
import logging
import os
import sys
from pathlib import Path

# ── Logging ──────────────────────────────────────────────────────────────── #
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)

# Ensure repo root is importable when run from any working directory
sys.path.insert(0, str(Path(__file__).resolve().parent))

from phase1 import Phase1Pipeline, Phase1Config  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Test Phase 1 pipeline (no Streamlit required)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("pdf", help="Path to the PDF file to process")
    p.add_argument(
        "--api-key",
        default=os.environ.get("ANTHROPIC_API_KEY", ""),
        help="Anthropic API key (default: $ANTHROPIC_API_KEY)",
    )
    p.add_argument(
        "--output-dir", "-o",
        default=None,
        help="Output directory (default: <pdf_dir>/phase1_out/)",
    )
    p.add_argument(
        "--dpi",
        type=int,
        default=300,
        help="Render DPI for scanned pages (default: 300)",
    )
    p.add_argument(
        "--mode",
        choices=["auto", "ocr", "digital"],
        default="auto",
        help="PDF processing mode (default: auto)",
    )
    p.add_argument(
        "--no-correction",
        action="store_true",
        help="Skip the LLM OCR correction step",
    )
    p.add_argument(
        "--script",
        action="store_true",
        help="Also generate the video script (needs API key)",
    )
    p.add_argument(
        "--genre",
        default="non-fiction",
        help="Book genre hint for script generation (default: non-fiction)",
    )
    p.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show DEBUG-level log output",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    pdf_path   = Path(args.pdf).resolve()
    output_dir = Path(args.output_dir).resolve() if args.output_dir \
                 else pdf_path.parent / "phase1_out"
    output_dir.mkdir(parents=True, exist_ok=True)

    if not pdf_path.exists():
        print(f"ERROR: PDF not found: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    api_key = args.api_key
    if not api_key and not args.no_correction:
        print(
            "WARNING: ANTHROPIC_API_KEY not set — LLM correction will be skipped.\n"
            "         Set the env var or pass --api-key KEY.\n"
            "         To suppress this warning use --no-correction.\n",
            file=sys.stderr,
        )

    cfg = Phase1Config(
        ocr_backend       = "tesseract",
        ocr_dpi           = args.dpi,
        pdf_mode          = args.mode,
        ocr_correction    = (not args.no_correction) and bool(api_key),
        output_dir        = str(output_dir),
        anthropic_api_key = api_key if args.script else "",
        script_genre      = args.genre,
    )
    # Pass key for correction even when not generating a script
    if cfg.ocr_correction and not cfg.anthropic_api_key:
        cfg.anthropic_api_key = api_key

    # ── Progress display ─────────────────────────────────────────────── #
    last_pct = [-1]

    def on_progress(step: str, pct: float) -> None:
        pct_int = int(pct * 100)
        if pct_int != last_pct[0]:
            print(f"  [{pct_int:3d}%] {step}", flush=True)
            last_pct[0] = pct_int

    # ── Run ──────────────────────────────────────────────────────────── #
    print(f"\n{'─'*60}")
    print(f"  PDF      : {pdf_path.name}")
    print(f"  Output   : {output_dir}")
    print(f"  DPI      : {cfg.ocr_dpi}")
    print(f"  Mode     : {cfg.pdf_mode}")
    print(f"  LLM fix  : {'ON  (Claude Haiku)' if cfg.ocr_correction else 'OFF (Tesseract only)'}")
    print(f"  Script   : {'ON' if args.script and api_key else 'OFF'}")
    print(f"{'─'*60}\n")

    result = Phase1Pipeline(config=cfg, on_progress=on_progress).run(pdf_path)

    # ── Summary ──────────────────────────────────────────────────────── #
    print(f"\n{'='*60}")
    print(
        f"  Done in {result.elapsed_sec:.1f}s — "
        f"{result.total_pages} page(s), {len(result.chunks)} chunk(s)"
    )
    print(f"  PDF type : {result.pdf_type}")
    print(f"\n  Files written:")
    print(f"    raw OCR text : {result.raw_txt_path}")
    print(f"    clean text   : {result.txt_path}")
    if result.script_path:
        print(f"    script       : {result.script_path}")
    if result.script_diac_path:
        print(f"    script+diac  : {result.script_diac_path}")

    if result.warnings:
        print(f"\n  Warnings ({len(result.warnings)}):")
        for w in result.warnings:
            print(f"    ⚠  {w}")

    # ── Quick preview (first 500 chars of clean text) ─────────────── #
    try:
        preview = result.txt_path.read_text(encoding="utf-8")[:500]
        print(f"\n  ── Clean text preview ──────────────────────────────")
        print(preview)
        print(f"  ────────────────────────────────────────────────────")
    except Exception:
        pass

    print()


if __name__ == "__main__":
    main()
