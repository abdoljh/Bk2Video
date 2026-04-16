# Bk2Video — Master Plan & Session Handoff

## Project Vision

Convert Arabic books (PDF) into high-impact, 3-to-5-minute video summaries —
long enough to deliver real value, short enough for modern attention spans.
The output is a fully automated MP4: Arabic TTS voice, relevant background
visuals with motion, and burned-in Arabic subtitles. Every phase is built to
run on Streamlit Community Cloud (1 GB RAM, no GPU).

Working repo: **abdoljh/Bk2Video** · Streamlit Community Cloud deployment.

---

## Four-Phase Architecture

| Phase | Name | Goal | Status |
|-------|------|------|--------|
| 1 | Text Extraction & Summarisation | PDF → cleaned Arabic text → 625–850-word video script | ✅ **Complete** |
| 2 | Audio Synthesis (TTS) | Script → Arabic MP3 via gTTS (ElevenLabs next) | ✅ **Working** (gTTS) |
| 3 | Visual Generation | Script + audio → final MP4 with visuals, voice, subtitles | 🔧 **In Progress** |
| 4 | Workflow Integration | One-click pipeline: PDF → finished video | ✅ **Complete** (follows Phase 3) |

---

## Phase 1 — Text Extraction & Summarisation ✅

### What it does
1. Ingests PDF (digital or scanned Arabic)
2. OCR via Tesseract (fits Streamlit Cloud 1 GB RAM limit)
3. Normalises Arabic text (lam-alef fixes, Farsi Yeh, noise removal, header/footnote stripping)
4. Semantic chunking (default 1500 tokens, 200 overlap)
5. Hierarchical summarisation: Reader (Haiku, per chunk) → Consolidator (Haiku) → Scriptwriter (Sonnet) → Editor/Scorer (Haiku, up to 2 retries)
6. Outputs: `*_phase1.json`, `*_phase1.txt`, `*_phase1_raw.txt`, `book_script.txt`, `book_script_diacritized.txt`, `book_script_metadata.json`

### Key design decisions
- **Cost strategy**: Haiku for all bulk/scoring work; Sonnet only for the final script (~$0.05 for a 300-page book).
- **Word-count gate**: 625–850 words. Scripts outside range trigger a targeted retry.
- **max_tokens = 3500** for Scriptwriter (Arabic ~4.2 tokens/word; 850 words ≈ 3570 tokens).
- **Diacritisation**: Mishkal applied only to the final script, never to raw OCR text.
- **No hallucinated names**: Scriptwriter is forbidden from inventing names not in the outline.

### Script structure (4 required sections)
1. Cinematic opening hook
2. Three thematic points with examples
3. Reflective closing
4. Formal book presentation (title + call to action)

### Validated on
- Al-Askari Memoirs (255-page scanned Arabic book, split into 2 PDFs)
- Score: 41/50 · 629 words · 0 retries

---

## Phase 2 — Audio Synthesis ✅ (partial)

### What works
- **gTTS** (`lang='ar'`): free, no API key, produces Arabic MP3 in seconds.
- Streamlit UI: choose script source (Phase 1 session or upload `.txt`), plain vs. diacritized variant, generate + download MP3.

### What is needed next
- **ElevenLabs** integration (Chaouki voice) for broadcast-quality Arabic TTS.
  - Stub already exists in `phase2/tts.py` (`NotImplementedError`).
  - Needs: `ELEVENLABS_API_KEY` secret + voice ID in UI, then call ElevenLabs REST API.
  - Priority: implement after Phase 3 visual quality is acceptable.

---

## Phase 3 — Visual Generation 🔧 (IN PROGRESS — THE CORNERSTONE)

### What works today
- Script parsed into sections (opening, point_1–3, closing, cta)
- Claude Haiku generates Wikimedia + Pexels search terms **and key phrases** per section, using book title + character name as context
- Wikimedia Commons images downloaded (free, no key), with exclusions for diagrams/anatomy and a 400 px minimum size filter
- Pexels video clips as fallback (key optional)
- Ken Burns effect (zoom/pan) applied to each image — zoom speed proportional to clip length so motion is always visible
- Crossfade transitions between sections
- Warm/cool/neutral colour grade
- **Multi-layer ASS Arabic subtitles** (Amiri font) burned into video:
  - `TitleCard` — book title full-screen at t=0 (5 seconds)
  - `SectionMark` — chapter heading at start of each section (2.5 seconds)
  - `KeyPhrase` — most impactful Arabic sentence from each section, displayed large and centred
  - `Arabic` — regular caption flow for the full script text
- Phase 2 TTS audio muxed into final MP4
- Output: complete 720p MP4
- Styled dark-navy fallback background when no images are found

### Current weaknesses (what still needs work)

#### 1. Image accuracy
Wikimedia returns topically adjacent but not precisely relevant images.
A search for "Jafar al-Askari" may return anything from the right era but not
the right person. The `-diagram -anatomy` exclusions help but do not guarantee
subject specificity.

**Root cause**: Wikimedia text search has no visual understanding — it matches
file names and descriptions, not image content.

**Next step (Tier 2)**: Claude vision scoring — after downloading each image,
send it (resized to ≤ 800 px wide) to Claude Haiku vision with a binary
yes/no relevance question. Discard "no" images before assembly.
**IMPORTANT**: Always resize to ≤ 800 px before sending to Claude vision.
Oversized images cause `400 "Could not process image"` API errors.

#### 2. Visual narrative quality
Ken Burns + images + subtitles is functional but not yet cinematic.
The Tier 2 and Tier 3 items below address this progressively.

### Phase 3 Visual Strategy — Tiered Roadmap

#### Tier 1 — Implemented ✅
| Feature | Implementation |
|---------|---------------|
| Title card (book title + author) | ASS `TitleCard` style, t=0 to t=5 |
| Section markers | ASS `SectionMark` style at each section boundary |
| Key phrase overlays | Claude Haiku extracts 1-2 per section; ASS `KeyPhrase` style, centred |
| Regular captions | ASS `Arabic` style, bottom of screen |
| Ken Burns zoom fix | Zoom step = 0.5/n_frames (always spans 1.0→1.5 regardless of clip length) |
| Dark fallback background | Navy (#1a1a2e) instead of black |
| Wikimedia exclusions | `-diagram -anatomy -chart -schematic` in every search query |
| Min image size | 400 px minimum dimension filter |

#### Tier 2 — Next session priority
1. **Claude vision image scoring** (closes the accuracy gap):
   - After `download_images()`, call `score_images(images, character_name, book_title)`
   - Resize each to ≤ 800 px wide (PIL thumbnail) before sending to Claude Haiku vision
   - Discard images where Claude says "no"
   - Cost: ~$0.001 per image (Haiku vision pricing)

2. **ElevenLabs TTS** (biggest single quality jump):
   - Implement the stub in `phase2/tts.py`
   - Chaouki voice (or similar high-quality Arabic voice)
   - The voice quality transforms the perceived quality of the entire video

3. **Pillow text cards** (for sections with no usable images):
   - Render a styled typography card: gradient background + key phrase in Amiri
   - Use `arabic_reshaper` + `python-bidi` for correct RTL shaping in Pillow
   - This replaces the navy fallback with something visually informative

#### Tier 3 — Future
- Animated word-by-word text reveal
- Custom intro/outro jingle
- Auto-generated book cover placeholder
- Multiple visual themes (documentary, cinematic, minimal)
- AI-generated images (DALL-E / Stable Diffusion) for scenes with no stock equivalent

### Phase 3 File Map

```
phase3/
  __init__.py      — generate_background_video() full pipeline orchestrator
  parser.py        — split script into sections; estimate per-section durations
  keywords.py      — Claude Haiku: Wikimedia/Pexels search terms + key phrases
  wikimedia.py     — MediaWiki API: search free images, filter, download
  pexels.py        — Pexels Video API: fallback clips
  effects.py       — Ken Burns (zoompan); trim_clip; probe_duration
  compositor.py    — section clips → crossfade → colour grade → mux_final_video
  subtitler.py     — ASS generator: TitleCard/SectionMark/KeyPhrase/captions
```

---

## Phase 4 — Workflow Integration ✅

The Streamlit UI chains all phases in one session:

1. **Phase 1** tab: Upload PDF → Run → Download script files
2. **Phase 2** tab: Choose script → Generate Audio → Download MP3
3. **Phase 3** tab: Enter book title + character name → Generate Final Video → Download MP4

Each phase's output automatically feeds the next within the same session.
Phase 4 is considered complete once Phase 3 produces broadcast-quality output.

---

## Immediate Next Steps (start here next session)

1. **Verify current build** on Streamlit Cloud — confirm `fonts-hosny-amiri` installs
   and the multi-layer ASS subtitle pipeline (TitleCard + SectionMark + KeyPhrase)
   renders correctly in the downloaded video.

2. **Implement Claude vision image scoring** (Tier 2, highest ROI):
   - File to edit: `phase3/wikimedia.py`
   - Add `score_images(paths, character_name, book_title, api_key)` function
   - Resize each image: `img.thumbnail((800, 800))` before encoding to base64
   - Call `anthropic.messages.create` with `image` content block
   - Prompt: "Does this image show [character_name] or a scene directly related
     to [book_title]? Answer only yes or no."
   - Return only the "yes" images

3. **Implement ElevenLabs TTS** (Tier 2):
   - File to edit: `phase2/tts.py`
   - Fill in the `NotImplementedError` stub
   - Add `ELEVENLABS_API_KEY` to Streamlit Cloud secrets
   - Test with Chaouki voice

4. **End-to-end validation** on al-Askari Memoirs, both PDF parts,
   and upload sample to `Video4/` in the repo.

---

## Repo Structure

```
streamlit_app.py          # Streamlit entrypoint (Phases 1–3 UI)
phase1/
  __init__.py
  pipeline.py             # Phase1Pipeline orchestrator
  core/
    ingestor.py           # PDF ingestion (PyMuPDF) — digital + scanned
    ocr_engine.py         # Tesseract / EasyOCR / PaddleOCR wrapper
    normalizer.py         # Arabic text normalisation
    chunker.py            # Semantic chunking
    output_writer.py      # Writes JSON / TXT outputs
    summarizer.py         # Hierarchical summarisation + script generation
phase2/
  __init__.py
  tts.py                  # gTTS backend; ElevenLabs stub (implement next)
phase3/
  __init__.py             # generate_background_video() full pipeline
  parser.py               # Script section splitter + duration estimator
  keywords.py             # Claude Haiku: search terms + key phrases per section
  wikimedia.py            # Wikimedia Commons image fetcher + filter
  pexels.py               # Pexels video clip fetcher
  effects.py              # Ken Burns (zoompan) + trim + probe_duration
  compositor.py           # Section clips → crossfade → grade → mux
  subtitler.py            # Multi-layer ASS subtitle generator
packages.txt              # Streamlit Cloud apt deps (ffmpeg, fonts-hosny-amiri, etc.)
requirements.txt          # Python deps
PHASE1_PLAN.md            # Phase 1 detailed design document
```

---

## Key Technical Constraints

| Constraint | Detail |
|-----------|--------|
| Streamlit Cloud RAM | 1 GB — no PyTorch; Tesseract OCR only |
| No GPU | All ML inference via API; local tools CPU-only |
| Arabic RTL in video | Use ASS + libass (correct bidi); never FFmpeg `drawtext` (no Arabic bidi) |
| Claude vision image size | Always resize to ≤ 800 px wide before sending — oversized → `400 Could not process image` |
| Streamlit Cloud Python | 3.14 — PaddleOCR needs ≤ 3.12, do not use it |
| Arabic font for FFmpeg | `fonts-hosny-amiri` (Debian trixie) → font family name `Amiri` |
| Do NOT use | `fonts-noto-arabic` — does not exist in Debian trixie repos |

---

## Model & Cost Strategy

| Task | Model | Cost per book |
|------|-------|---------------|
| Reader per chunk | claude-haiku-4-5 | ~$0.01 |
| Consolidator | claude-haiku-4-5 | ~$0.001 |
| Scriptwriter | claude-sonnet-4-6 | ~$0.04 |
| Editor/Scorer | claude-haiku-4-5 | ~$0.002 |
| Keyword + key phrase gen (Phase 3) | claude-haiku-4-5-20251001 | ~$0.003 |
| Image relevance scoring (next) | claude-haiku-4-5-20251001 vision | ~$0.005 |
| **Total (current)** | | **~$0.05** |
| TTS (gTTS) | Free | $0 |
| TTS (ElevenLabs target) | Chaouki voice | ~$0.10–0.30 |
