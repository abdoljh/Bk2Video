# Bk2Video — Claude Code Session Handoff

## Project goal
Convert Arabic books (PDF) into 4-5 minute video scripts, then into full videos.
Working repo: **abdoljh/Bk2Video** · Streamlit Community Cloud deployment.

---

## Phase 1 — Text Extraction & Script Generation (COMPLETE)

### Branch
`claude/review-arabic-phase-1-fnqA2`
> All Phase 1 code lives here. `main` branch is what Streamlit Cloud deploys.
> Merge this branch to main before starting Phase 2.

### What it does
1. Ingests PDF (digital or scanned Arabic)
2. OCR via Tesseract (only backend that fits Streamlit Cloud 1 GB RAM)
3. Normalises Arabic text (lam-alef fixes, Farsi Yeh → Arabic Yeh, noise removal, header/footnote stripping)
4. Semantic chunking (default 1500 tokens, 200 overlap)
5. Hierarchical summarisation: Reader (Haiku, per chunk) → Consolidator (Haiku) → Scriptwriter (Sonnet) → Editor/Scorer (Haiku, up to 2 retries)
6. Outputs: `*_phase1.json`, `*_phase1.txt`, `*_phase1_raw.txt`, `book_script.txt`, `book_script_diacritized.txt`, `book_script_metadata.json`

### Key design decisions
- **Cost strategy**: Haiku for all bulk/scoring work; Sonnet only for the final script (one call per book, ~$0.05 total for a 300-page book).
- **Word-count gate**: 625–850 words. Scripts outside this range trigger a retry with targeted feedback. Scripts in range are accepted on the first pass — no wasteful loops.
- **max_tokens = 3500** for Scriptwriter (Arabic uses ~4.2 Claude tokens/word; 850 words ≈ 3570 tokens).
- **Diacritisation**: Mishkal applied only to the final script, never to raw OCR text.
- **No hallucinated names**: Scriptwriter is forbidden from inventing author/editor/translator names not present in the provided outline.

### Script structure (4 required sections)
1. Cinematic opening hook
2. Three thematic points with examples
3. Reflective closing
4. Formal book presentation (title + call to action; names only if found in text)

### Validated on
- Al-Askari Memoirs (255-page scanned Arabic book, split into 2 PDFs)
- Score: 41/50 · 629 words · 0 retries · Chaouki (ElevenLabs Arabic voice) TTS tested

### Known limitations / future improvements
- PDF title metadata is usually empty → script file named `book_script.txt` generically. A "Book Title" input field in the UI would help.
- Mishkal diacritisation has morphological errors (~10-15% of words). Acceptable for TTS guidance; not suitable for print.
- Tesseract OCR quality is adequate but lower than EasyOCR/PaddleOCR. Scanned book quality heavily affects output.

---

## Phase 2 — Planning Notes

Phase 2 goal: **turn the script into a finished video**.

Likely components to discuss and implement:
1. **Text-to-Speech**: ElevenLabs integration (Arabic voice, diacritised script as input). User is already testing with Chaouki voice.
2. **Visual generation**: Background video/images matched to script content (AI image generation or stock footage).
3. **Subtitle/caption overlay**: Arabic subtitles time-synced to TTS audio.
4. **Video assembly**: Combine audio + visuals + subtitles into a final MP4.
5. **Streamlit UI extension**: Upload PDF → download finished video.

Start the Phase 2 session by discussing the scope with the user before writing any code.

---

## Repo structure
```
streamlit_app.py          # Streamlit entrypoint
phase1/
  __init__.py
  pipeline.py             # Phase1Pipeline orchestrator
  core/
    ingestor.py           # PDF ingestion (PyMuPDF)
    ocr_engine.py         # Tesseract / EasyOCR / PaddleOCR wrapper
    normalizer.py         # Arabic text normalisation
    chunker.py            # Semantic chunking
    output_writer.py      # Writes JSON / TXT outputs
    summarizer.py         # Hierarchical summarisation + script generation
packages.txt              # Streamlit Cloud apt deps (tesseract-ocr-ara etc.)
requirements.txt          # Python deps
PHASE1_PLAN.md            # Detailed Phase 1 design document
```

## Deployment
- Platform: Streamlit Community Cloud
- Python: 3.14 · OS: Debian trixie
- Secrets: `ANTHROPIC_API_KEY` in Streamlit Cloud secrets
- RAM limit: 1 GB (reason Tesseract was chosen over EasyOCR/PaddleOCR)
