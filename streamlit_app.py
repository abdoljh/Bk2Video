"""
Arabic Book Brief Engine — Phase 1
Streamlit Community Cloud entrypoint.

Repository root is the working directory on Community Cloud, so:
  • This file lives at repo root  →  streamlit run streamlit_app.py
  • The phase1 package lives at  →  phase1/
  • Config lives at              →  .streamlit/config.toml
  • Secrets injected via         →  st.secrets  (never committed)
"""

import json
import logging
import sys
import tempfile
from pathlib import Path

import streamlit as st

# ── Secrets: read Farasa key from st.secrets (Community Cloud) or env var ──
import os
_farasa_key_default = st.secrets.get("FARASA_API_KEY", "") or os.getenv("FARASA_API_KEY", "")

# ── Phase 1 package is at ./phase1 relative to repo root ──────────────── #
sys.path.insert(0, str(Path(__file__).parent))
#from phase1 import Phase1Pipeline, Phase1Config  # noqa: E402
from phase1.pipeline import Phase1Pipeline, Phase1Config  # noqa: E402

# ── Logging ───────────────────────────────────────────────────────────── #
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

html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }
h1, h2, h3 { font-family: 'Playfair Display', serif !important; }

.app-header {
    background: #0e0e0e; color: #f5f0e8;
    padding: 2rem 2.5rem 1.6rem; border-radius: 8px;
    margin-bottom: 2rem; position: relative; overflow: hidden;
}
.app-header::after {
    content: '📖'; position: absolute; right: 2rem; top: 50%;
    transform: translateY(-50%); font-size: 5rem; opacity: .07;
}
.app-header h1 { color: #f5f0e8 !important; margin: 0; font-size: 2rem; }
.app-header .sub { color: #b0a898; font-size: 0.85rem; margin-top: 0.4rem; }
.app-header .eyebrow {
    font-family: 'DM Mono', monospace; font-size: 0.65rem;
    letter-spacing: .18em; text-transform: uppercase;
    color: #c9a84c; margin-bottom: 0.5rem;
}
.badge {
    display: inline-block; font-family: 'DM Mono', monospace;
    font-size: 0.6rem; letter-spacing: .1em; text-transform: uppercase;
    padding: 3px 10px; border-radius: 2px; border: 1px solid;
    margin-right: 6px; margin-top: 8px;
}
.b-gold { border-color: #c9a84c; color: #c9a84c; }
.b-teal { border-color: #4aadad; color: #4aadad; }
.b-rust { border-color: #d97452; color: #d97452; }
.metric-row { display: flex; gap: 1rem; margin: 1rem 0; flex-wrap: wrap; }
.metric-card {
    flex: 1; min-width: 120px; background: white;
    border: 1px solid #e0dbd0; border-top: 3px solid #c9a84c;
    border-radius: 4px; padding: 1rem 1.2rem;
    box-shadow: 3px 3px 0 #e8dfcc;
}
.metric-card .val {
    font-family: 'Playfair Display', serif; font-size: 2rem;
    font-weight: 700; color: #0e0e0e; line-height: 1;
}
.metric-card .lbl {
    font-family: 'DM Mono', monospace; font-size: 0.65rem;
    letter-spacing: .12em; text-transform: uppercase;
    color: #7a7060; margin-top: 4px;
}
.metric-card.teal  { border-top-color: #1e6b6b; }
.metric-card.rust  { border-top-color: #b94f2a; }
.metric-card.purple{ border-top-color: #7c5cbf; }
.chunk-card {
    background: #fefcf8; border: 1px solid #e0dbd0;
    border-left: 4px solid #c9a84c; border-radius: 0 4px 4px 0;
    padding: 1rem 1.2rem; margin-bottom: 0.8rem;
    direction: rtl; text-align: right;
    font-size: 0.9rem; line-height: 1.8;
}
.chunk-meta {
    font-family: 'DM Mono', monospace; font-size: 0.6rem;
    letter-spacing: .1em; text-transform: uppercase;
    color: #7a7060; direction: ltr; text-align: left; margin-bottom: 0.4rem;
}
.chunk-card.scanned { border-left-color: #1e6b6b; }
.warn-card {
    background: #fff7ec; border-left: 4px solid #c9a84c;
    border-radius: 0 4px 4px 0; padding: 0.8rem 1rem;
    margin: 0.5rem 0; font-size: 0.85rem; color: #5a3d00;
}
.step-log {
    font-family: 'DM Mono', monospace; font-size: 0.75rem;
    background: #0e0e0e; color: #c8c0b0; padding: 1rem 1.2rem;
    border-radius: 4px; line-height: 1.8;
    max-height: 220px; overflow-y: auto;
}
.step-log .done  { color: #4aadad; }
.step-log .active{ color: #f0d98a; }
section[data-testid="stSidebar"] { background: #0e0e0e !important; }
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] .stMarkdown p,
section[data-testid="stSidebar"] span { color: #c8c0b0 !important; }
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3 { color: #f0d98a !important; }
</style>
""", unsafe_allow_html=True)

# ── Header ────────────────────────────────────────────────────────────── #
st.markdown("""
<div class="app-header">
  <div class="eyebrow">Arabic Book Brief Engine · Phase 1</div>
  <h1>Extraction &amp; Pre-processing</h1>
  <div class="sub">Auto-detect PDF type · OCR scanned pages · Normalise Arabic · Diacritize · Chunk</div>
  <div>
    <span class="badge b-gold">Auto-Detect</span>
    <span class="badge b-teal">Farasa Diacritizer</span>
    <span class="badge b-rust">Semantic Chunking</span>
  </div>
</div>
""", unsafe_allow_html=True)

# ── Sidebar ───────────────────────────────────────────────────────────── #
with st.sidebar:
    st.markdown("### ⚙️ Configuration")

    st.markdown("#### OCR")
    ocr_backend = st.selectbox("OCR Backend", ["easyocr", "tesseract"], index=0)
    ocr_gpu     = st.toggle("Use GPU for OCR", value=False)
    ocr_dpi     = st.slider("Scan DPI", 150, 400, 200, step=50)

    st.markdown("#### Diacritization")
    diacritize   = st.toggle("Enable Diacritization (Harakat)", value=True)
    diac_backend = st.selectbox("Backend", ["auto", "farasa", "mishkal"],
                                 disabled=not diacritize)
    # Pre-fill from st.secrets; user can override in the sidebar
    farasa_key = st.text_input(
        "Farasa API Key",
        value=_farasa_key_default,
        type="password",
        disabled=not diacritize,
        help="Set via st.secrets['FARASA_API_KEY'] in Community Cloud Advanced Settings.",
    )

    st.markdown("#### Chunking")
    max_tokens     = st.slider("Max Tokens / Chunk", 500, 3000, 1500, step=100)
    overlap_tokens = st.slider("Overlap Tokens",       0,  500,  200, step=50)

    st.markdown("---")
    st.markdown(
        "<span style='font-family:DM Mono,monospace;font-size:0.6rem;"
        "color:#6b6355;letter-spacing:.1em'>ARABIC BOOK BRIEF ENGINE v1.0</span>",
        unsafe_allow_html=True,
    )

# ── Upload ────────────────────────────────────────────────────────────── #
col_up, col_info = st.columns([2, 1])
with col_up:
    uploaded = st.file_uploader("Upload Arabic PDF", type=["pdf"])
with col_info:
    st.markdown("""
    **What Phase 1 produces:**
    - PDF type detected (digital / scanned / mixed)
    - Normalised Arabic (BiDi + reshaping)
    - Diacritized text ready for TTS
    - Semantic chunks with chapter metadata
    - **JSON** + **plain text** downloads
    """)

# ── Run ───────────────────────────────────────────────────────────────── #
if uploaded:
    if st.button("▶ Run Phase 1", type="primary", use_container_width=True):

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path   = Path(tmp_dir) / uploaded.name
            output_dir = Path(tmp_dir) / "output"
            output_dir.mkdir()
            tmp_path.write_bytes(uploaded.read())

            progress_bar    = st.progress(0.0)
            status_text     = st.empty()
            log_lines: list[str] = []
            log_ph          = st.empty()

            def on_progress(step: str, pct: float):
                progress_bar.progress(min(pct, 1.0))
                status_text.markdown(f"**{step}**")
                cls = "done" if pct >= 1.0 else "active"
                log_lines.append(f"<span class='{cls}'>{'✓' if pct>=1.0 else '›'} {step}</span>")
                log_ph.markdown(
                    "<div class='step-log'>" + "<br>".join(log_lines) + "</div>",
                    unsafe_allow_html=True,
                )

            cfg = Phase1Config(
                ocr_gpu=ocr_gpu, ocr_backend=ocr_backend, ocr_dpi=ocr_dpi,
                diacritize=diacritize, diac_backend=diac_backend,
                farasa_api_key=farasa_key,
                max_tokens=max_tokens, overlap_tokens=overlap_tokens,
                output_dir=str(output_dir),
            )

            try:
                result = Phase1Pipeline(config=cfg, on_progress=on_progress).run(tmp_path)

                # Persist bytes to session state before temp dir is cleaned up
                st.session_state["json_bytes"] = result.json_path.read_bytes()
                st.session_state["txt_bytes"]  = result.txt_path.read_bytes()
                st.session_state["json_name"]  = result.json_path.name
                st.session_state["txt_name"]   = result.txt_path.name
                st.session_state["result_meta"] = {
                    "pdf_type":    result.pdf_type,
                    "total_pages": result.total_pages,
                    "elapsed_sec": result.elapsed_sec,
                    "warnings":    result.warnings,
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
                        for c in result.chunks
                    ],
                }
                status_text.success("Phase 1 complete ✓")

            except Exception as exc:
                st.error(f"Pipeline failed: {exc}")
                logging.exception("Phase 1 error")

# ── Results ───────────────────────────────────────────────────────────── #
if "result_meta" in st.session_state:
    meta   = st.session_state["result_meta"]
    chunks = meta["chunks"]

    st.markdown("---")
    st.markdown("### Results")

    for w in meta["warnings"]:
        st.markdown(f"<div class='warn-card'>⚠ {w}</div>", unsafe_allow_html=True)

    type_colors = {"digital": "#c9a84c", "scanned": "#1e6b6b", "mixed": "#b94f2a"}
    tc = type_colors.get(meta["pdf_type"], "#c9a84c")
    total_words = sum(c["word_count"] for c in chunks)

    st.markdown(f"""
    <div class="metric-row">
      <div class="metric-card">
        <div class="val">{meta['total_pages']}</div><div class="lbl">Pages</div>
      </div>
      <div class="metric-card" style="border-top-color:{tc}">
        <div class="val" style="font-size:1.3rem;padding-top:.3rem">{meta['pdf_type'].upper()}</div>
        <div class="lbl">PDF Type</div>
      </div>
      <div class="metric-card teal">
        <div class="val">{len(chunks)}</div><div class="lbl">Chunks</div>
      </div>
      <div class="metric-card rust">
        <div class="val">{total_words:,}</div><div class="lbl">Words</div>
      </div>
      <div class="metric-card purple">
        <div class="val">{meta['elapsed_sec']:.1f}s</div><div class="lbl">Elapsed</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # Downloads
    st.markdown("#### 📥 Downloads")
    c1, c2 = st.columns(2)
    with c1:
        st.download_button("⬇ Download JSON", data=st.session_state["json_bytes"],
                           file_name=st.session_state["json_name"],
                           mime="application/json", use_container_width=True)
    with c2:
        st.download_button("⬇ Download Plain Text", data=st.session_state["txt_bytes"],
                           file_name=st.session_state["txt_name"],
                           mime="text/plain", use_container_width=True)

    # Chunk preview
    st.markdown("#### 🔍 Chunk Preview")
    n = st.slider("Chunks to preview", 1, min(20, len(chunks)), 5)
    for c in chunks[:n]:
        border = "scanned" if meta["pdf_type"] == "scanned" else ""
        st.markdown(
            f"""<div class="chunk-card {border}">
              <div class="chunk-meta">
                chunk {c['chunk_id']:04d} · {c['chapter']}
                · pp. {c['page_start']}–{c['page_end']}
                · {c['word_count']} words · ~{c['token_est']} tokens
              </div>
              {c['text'][:500]}{"…" if len(c['text']) > 500 else ""}
            </div>""",
            unsafe_allow_html=True,
        )

    with st.expander("🔎 Inspect raw JSON"):
        st.json(json.loads(st.session_state["json_bytes"]))
