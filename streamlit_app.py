"""
Phase 1 — Streamlit App
Arabic Book Brief Engine · Extraction & Pre-processing Interface
"""

import io
import json
import logging
import sys
import tempfile
from pathlib import Path

import streamlit as st
import pipeline

# ── ensure phase1 package is importable when running as `streamlit run app.py`
sys.path.insert(0, str(Path(__file__).parent))

#from phase1 import Phase1Pipeline, Phase1Config
from pipeline import Phase1Pipeline, Phase1Config

# ── Logging to both console and Streamlit capture buffer ──────────────── #
logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(name)s | %(message)s")

# ── Page config ───────────────────────────────────────────────────────── #
st.set_page_config(
    page_title="Arabic Book Brief — Phase 1",
    page_icon="📖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────────────────── #
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,700;1,400&family=DM+Mono:wght@400;500&family=DM+Sans:wght@300;400;500&display=swap');

html, body, [class*="css"] {
    font-family: 'DM Sans', sans-serif;
}
h1, h2, h3 { font-family: 'Playfair Display', serif !important; }

/* Header strip */
.app-header {
    background: #0e0e0e;
    color: #f5f0e8;
    padding: 2rem 2.5rem 1.6rem;
    border-radius: 8px;
    margin-bottom: 2rem;
    position: relative;
    overflow: hidden;
}
.app-header::after {
    content: '📖';
    position: absolute; right: 2rem; top: 50%;
    transform: translateY(-50%);
    font-size: 5rem; opacity: .07;
}
.app-header h1 { color: #f5f0e8 !important; margin: 0; font-size: 2rem; }
.app-header .sub { color: #b0a898; font-size: 0.85rem; margin-top: 0.4rem; }
.app-header .eyebrow {
    font-family: 'DM Mono', monospace;
    font-size: 0.65rem; letter-spacing: .18em;
    text-transform: uppercase; color: #c9a84c;
    margin-bottom: 0.5rem;
}

/* Badge pills */
.badge {
    display: inline-block;
    font-family: 'DM Mono', monospace; font-size: 0.6rem;
    letter-spacing: .1em; text-transform: uppercase;
    padding: 3px 10px; border-radius: 2px;
    border: 1px solid; margin-right: 6px; margin-top: 8px;
}
.b-gold  { border-color: #c9a84c; color: #c9a84c; }
.b-teal  { border-color: #4aadad; color: #4aadad; }
.b-rust  { border-color: #d97452; color: #d97452; }

/* Metric cards */
.metric-row { display: flex; gap: 1rem; margin: 1rem 0; flex-wrap: wrap; }
.metric-card {
    flex: 1; min-width: 120px;
    background: white; border: 1px solid #e0dbd0;
    border-top: 3px solid #c9a84c;
    border-radius: 4px; padding: 1rem 1.2rem;
    box-shadow: 3px 3px 0 #e8dfcc;
}
.metric-card .val {
    font-family: 'Playfair Display', serif;
    font-size: 2rem; font-weight: 700; color: #0e0e0e;
    line-height: 1;
}
.metric-card .lbl {
    font-family: 'DM Mono', monospace; font-size: 0.65rem;
    letter-spacing: .12em; text-transform: uppercase;
    color: #7a7060; margin-top: 4px;
}
.metric-card.teal  { border-top-color: #1e6b6b; }
.metric-card.rust  { border-top-color: #b94f2a; }
.metric-card.purple{ border-top-color: #7c5cbf; }

/* Chunk preview */
.chunk-card {
    background: #fefcf8; border: 1px solid #e0dbd0;
    border-left: 4px solid #c9a84c;
    border-radius: 0 4px 4px 0;
    padding: 1rem 1.2rem; margin-bottom: 0.8rem;
    direction: rtl; text-align: right;
    font-size: 0.9rem; line-height: 1.8;
}
.chunk-meta {
    font-family: 'DM Mono', monospace; font-size: 0.6rem;
    letter-spacing: .1em; text-transform: uppercase;
    color: #7a7060; direction: ltr; text-align: left;
    margin-bottom: 0.4rem;
}
.chunk-card.scanned { border-left-color: #1e6b6b; }

/* Warning card */
.warn-card {
    background: #fff7ec; border-left: 4px solid #c9a84c;
    border-radius: 0 4px 4px 0;
    padding: 0.8rem 1rem; margin: 0.5rem 0;
    font-size: 0.85rem; color: #5a3d00;
}

/* Step log */
.step-log {
    font-family: 'DM Mono', monospace; font-size: 0.75rem;
    background: #0e0e0e; color: #c8c0b0;
    padding: 1rem 1.2rem; border-radius: 4px;
    line-height: 1.8; max-height: 220px; overflow-y: auto;
}
.step-log .done  { color: #4aadad; }
.step-log .active{ color: #f0d98a; }

/* Sidebar tweaks */
section[data-testid="stSidebar"] {
    background: #0e0e0e !important;
}
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] .stMarkdown p,
section[data-testid="stSidebar"] span {
    color: #c8c0b0 !important;
}
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3 {
    color: #f0d98a !important;
}
</style>
""", unsafe_allow_html=True)

# ── Header ────────────────────────────────────────────────────────────── #
st.markdown("""
<div class="app-header">
  <div class="eyebrow">Arabic Book Brief Engine · Phase 1</div>
  <h1>Extraction &amp; Pre-processing</h1>
  <div class="sub">
    Auto-detect PDF type · OCR scanned pages · Normalise Arabic · Diacritize · Chunk
  </div>
  <div>
    <span class="badge b-gold">Auto-Detect</span>
    <span class="badge b-teal">Farasa Diacritizer</span>
    <span class="badge b-rust">Semantic Chunking</span>
  </div>
</div>
""", unsafe_allow_html=True)

# ── Sidebar — Configuration ───────────────────────────────────────────── #
with st.sidebar:
    st.markdown("### ⚙️ Configuration")

    st.markdown("#### OCR")
    ocr_backend = st.selectbox("OCR Backend", ["easyocr", "tesseract"], index=0)
    ocr_gpu     = st.toggle("Use GPU for OCR", value=False)
    ocr_dpi     = st.slider("Scan DPI", 150, 400, 200, step=50,
                             help="Higher DPI = better OCR accuracy but slower")

    st.markdown("#### Diacritization")
    diacritize   = st.toggle("Enable Diacritization (Harakat)", value=True)
    diac_backend = st.selectbox("Backend", ["auto", "farasa", "mishkal"], index=0,
                                 disabled=not diacritize)
    farasa_key   = st.text_input("Farasa API Key (optional)", type="password",
                                  disabled=not diacritize)

    st.markdown("#### Chunking")
    max_tokens     = st.slider("Max Tokens / Chunk", 500, 3000, 1500, step=100)
    overlap_tokens = st.slider("Overlap Tokens",       0,  500,  200, step=50)

    st.markdown("---")
    st.markdown(
        "<span style='font-family:DM Mono,monospace;font-size:0.6rem;"
        "color:#6b6355;letter-spacing:.1em'>ARABIC BOOK BRIEF ENGINE v1.0</span>",
        unsafe_allow_html=True,
    )

# ── Main — File Upload ────────────────────────────────────────────────── #
col_up, col_info = st.columns([2, 1])

with col_up:
    uploaded = st.file_uploader(
        "Upload Arabic PDF",
        type=["pdf"],
        help="Digital-born or scanned Arabic books — both supported.",
    )

with col_info:
    st.markdown("""
    **What Phase 1 produces:**
    - Detected PDF type (digital / scanned / mixed)
    - Normalised Arabic text (BiDi + reshaping fixed)
    - Diacritized text ready for TTS
    - Semantic chunks with chapter metadata
    - **JSON** + **plain text** downloads
    """)

# ── Run Pipeline ──────────────────────────────────────────────────────── #
if uploaded:
    run_btn = st.button("▶ Run Phase 1", type="primary", use_container_width=True)

    if run_btn:
        # Save upload to temp file
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(uploaded.read())
            tmp_path = Path(tmp.name)

        output_dir = tmp_path.parent / "phase1_output"
        output_dir.mkdir(exist_ok=True)

        # Progress state
        progress_bar   = st.progress(0.0)
        status_text    = st.empty()
        log_lines: list[str] = []
        log_placeholder     = st.empty()

        def on_progress(step: str, pct: float):
            progress_bar.progress(min(pct, 1.0))
            status_text.markdown(f"**{step}**")
            icon = "✓" if pct >= 1.0 else "›"
            log_lines.append(f"<span class='{'done' if pct >= 1.0 else 'active'}'>{icon} {step}</span>")
            log_placeholder.markdown(
                "<div class='step-log'>" + "<br>".join(log_lines) + "</div>",
                unsafe_allow_html=True,
            )

        # Build config
        cfg = Phase1Config(
            ocr_gpu        = ocr_gpu,
            ocr_backend    = ocr_backend,
            ocr_dpi        = ocr_dpi,
            diacritize     = diacritize,
            diac_backend   = diac_backend,
            farasa_api_key = farasa_key,
            max_tokens     = max_tokens,
            overlap_tokens = overlap_tokens,
            output_dir     = str(output_dir),
        )

        pipeline = Phase1Pipeline(config=cfg, on_progress=on_progress)

        try:
            result = pipeline.run(tmp_path)
            st.session_state["result"] = result
            st.session_state["output_dir"] = output_dir
            progress_bar.progress(1.0)
            status_text.success("Phase 1 complete ✓")

        except Exception as exc:  # noqa: BLE001
            st.error(f"Pipeline failed: {exc}")
            logging.exception("Phase 1 pipeline error")

# ── Results ───────────────────────────────────────────────────────────── #
if "result" in st.session_state:
    result     = st.session_state["result"]
    output_dir = st.session_state["output_dir"]

    st.markdown("---")
    st.markdown("### Results")

    # Warnings
    for w in result.warnings:
        st.markdown(f"<div class='warn-card'>⚠ {w}</div>", unsafe_allow_html=True)

    # Metrics
    type_colors = {"digital": "#c9a84c", "scanned": "#1e6b6b", "mixed": "#b94f2a"}
    type_color  = type_colors.get(result.pdf_type, "#c9a84c")
    total_words = sum(c.word_count for c in result.chunks)
    total_toks  = sum(c.token_est  for c in result.chunks)

    st.markdown(f"""
    <div class="metric-row">
      <div class="metric-card">
        <div class="val">{result.total_pages}</div>
        <div class="lbl">Pages</div>
      </div>
      <div class="metric-card" style="border-top-color:{type_color}">
        <div class="val" style="font-size:1.3rem;padding-top:0.3rem">{result.pdf_type.upper()}</div>
        <div class="lbl">PDF Type</div>
      </div>
      <div class="metric-card teal">
        <div class="val">{len(result.chunks)}</div>
        <div class="lbl">Chunks</div>
      </div>
      <div class="metric-card rust">
        <div class="val">{total_words:,}</div>
        <div class="lbl">Words</div>
      </div>
      <div class="metric-card purple">
        <div class="val">{result.elapsed_sec:.1f}s</div>
        <div class="lbl">Elapsed</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # Downloads
    st.markdown("#### 📥 Downloads")
    dl_col1, dl_col2 = st.columns(2)

    with dl_col1:
        json_bytes = result.json_path.read_bytes()
        st.download_button(
            "⬇ Download JSON",
            data       = json_bytes,
            file_name  = result.json_path.name,
            mime       = "application/json",
            use_container_width=True,
        )
    with dl_col2:
        txt_bytes = result.txt_path.read_bytes()
        st.download_button(
            "⬇ Download Plain Text",
            data       = txt_bytes,
            file_name  = result.txt_path.name,
            mime       = "text/plain",
            use_container_width=True,
        )

    # Chunk preview
    st.markdown("#### 🔍 Chunk Preview")
    preview_n = st.slider("Chunks to preview", 1, min(20, len(result.chunks)), 5)

    for chunk in result.chunks[:preview_n]:
        border = "scanned" if result.pdf_type == "scanned" else ""
        st.markdown(
            f"""<div class="chunk-card {border}">
              <div class="chunk-meta">
                chunk {chunk.chunk_id:04d} &nbsp;·&nbsp; {chunk.chapter}
                &nbsp;·&nbsp; pp. {chunk.page_start}–{chunk.page_end}
                &nbsp;·&nbsp; {chunk.word_count} words &nbsp;·&nbsp; ~{chunk.token_est} tokens
              </div>
              {chunk.text[:500]}{"…" if len(chunk.text) > 500 else ""}
            </div>""",
            unsafe_allow_html=True,
        )

    # JSON inspector
    with st.expander("🔎 Inspect raw JSON output"):
        json_data = json.loads(result.json_path.read_text(encoding="utf-8"))
        st.json(json_data)
