# Phase 1 — Extraction & Pre-processing
**Arabic Book Brief Engine**

Transforms a raw Arabic PDF (digital or scanned) into clean, diacritized,
semantically-chunked text ready for Phase 2 (multi-agent script generation).

---

## Quick Start

```bash
pip install -r requirements.txt
streamlit run app.py
```

Then open http://localhost:8501, upload an Arabic PDF, and click **Run Phase 1**.

---

## Module Structure

```
phase1/
├── app.py                  ← Streamlit UI entry point
├── pipeline.py             ← Phase1Pipeline orchestrator
├── requirements.txt
└── core/
    ├── ingestor.py         ← PDF type detection + text/image extraction
    ├── ocr_engine.py       ← EasyOCR / Tesseract for scanned pages
    ├── normalizer.py       ← BiDi + reshaper + cleaning
    ├── diacritizer.py      ← Farasa API + Mishkal fallback
    ├── chunker.py          ← Chapter-aware semantic chunking
    └── output_writer.py    ← JSON + plain text serialisation
```

---

## Using as a Library

```python
from phase1 import Phase1Pipeline, Phase1Config

cfg = Phase1Config(
    diacritize     = True,
    diac_backend   = "auto",   # tries Farasa, falls back to Mishkal
    max_tokens     = 1500,
    overlap_tokens = 200,
    output_dir     = "output",
)

pipeline = Phase1Pipeline(config=cfg)
result   = pipeline.run("my_arabic_book.pdf")

print(f"PDF type : {result.pdf_type}")
print(f"Pages    : {result.total_pages}")
print(f"Chunks   : {len(result.chunks)}")
print(f"JSON     : {result.json_path}")
print(f"Text     : {result.txt_path}")

# Iterate chunks
for chunk in result.chunks:
    print(chunk.chapter, chunk.word_count, chunk.text[:80])
```

---

## Output Formats

### JSON (`*_phase1.json`)
```json
{
  "source": "book.pdf",
  "pdf_type": "digital",
  "total_pages": 312,
  "metadata": { "title": "...", "author": "..." },
  "chunk_count": 87,
  "chunks": [
    {
      "chunk_id": 0,
      "chapter": "الفصل الأول",
      "page_start": 1,
      "page_end": 4,
      "word_count": 312,
      "token_est": 437,
      "text": "..."
    }
  ]
}
```

### Plain Text (`*_phase1.txt`)
Human-readable with chapter markers and chunk separators. Use as
an audit trail or direct input to Phase 2 without JSON parsing.

---

## Configuration Reference

| Parameter | Default | Description |
|---|---|---|
| `ocr_backend` | `easyocr` | `easyocr` or `tesseract` |
| `ocr_gpu` | `False` | Enable GPU for EasyOCR |
| `ocr_dpi` | `200` | Page render DPI for scanned PDFs |
| `diacritize` | `True` | Add Harakat before TTS |
| `diac_backend` | `auto` | `farasa`, `mishkal`, or `auto` |
| `farasa_api_key` | `""` | QCRI API key (optional) |
| `max_tokens` | `1500` | Max tokens per chunk |
| `overlap_tokens` | `200` | Overlap between chunks |
| `output_dir` | `output` | Directory for output files |

---

## Arabic-Specific Notes

- **BiDi / reshaping**: PyMuPDF extracts Arabic in visual (reversed) order.
  `ArabicTextNormalizer` fixes this automatically on every page.
- **Diacritization priority**: Always enabled for production. Farasa (QCRI)
  gives the best MSA accuracy; Mishkal is the offline fallback.
- **Chunking separators**: The chunker uses Arabic sentence terminators
  (`،`, `.`, `؟`, `!`) in addition to standard newlines.
