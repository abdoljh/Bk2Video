"""
Phase 1 — BookSummarizer
Hierarchical summarization pipeline:

  Step 4  Reader agent      (Haiku, per chunk) — extract key ideas
  Step 4  Consolidator      (Haiku, one call)  — merge into book outline
  Step 5  Scriptwriter      (Sonnet, one call) — 700-800 word Arabic script
  Step 6  Editor/Scorer     (Haiku, 1-2 calls) — score + refine if needed
  Step 7  Diacritizer       (Mishkal, local)   — add harakat to final script

Cost strategy: Haiku for all bulk/scoring work; Sonnet only for script
generation.  A 300-page book costs < $0.05 at current API pricing.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

# ── Model constants ──────────────────────────────────────────────────── #
_HAIKU  = "claude-haiku-4-5"
_SONNET = "claude-sonnet-4-6"

_SCORE_PASS = 35   # out of 50
_MAX_RETRIES = 2

# ── Genre → tone mapping ─────────────────────────────────────────────── #
_GENRE_TONE: dict[str, str] = {
    "non-fiction": "تحليلية رصينة، واضحة وموضوعية",
    "history":     "سردية تاريخية، تستحضر الأحداث بحيوية",
    "biography":   "إنسانية دافئة، تُبرز شخصية البطل",
    "novel":       "أدبية رشيقة، تثير المشاعر وتستدعي الخيال",
    "philosophy":  "تأملية عميقة، تُبسّط الأفكار دون إخلال بثرائها",
    "science":     "علمية ميسّرة، تربط المفاهيم بالحياة اليومية",
    "religion":    "روحية هادئة، تجمع بين العلم والإيمان",
}


@dataclass
class ScriptResult:
    script:          str
    script_diac:     str
    scores:          dict[str, int]
    total_score:     int
    word_count:      int
    retries_used:    int
    editor_feedback: str = ""
    warnings:        list[str] = field(default_factory=list)


class BookSummarizer:
    """
    Full summarization pipeline: chunks → Arabic video script (plain + diacritized).

    Args:
        api_key:    Anthropic API key.
        genre:      Book genre tag (see _GENRE_TONE).
        output_dir: Directory to write output files.
    """

    def __init__(
        self,
        api_key:    str,
        genre:      str = "non-fiction",
        output_dir: str | Path = "output",
    ):
        self.api_key    = api_key
        self.genre      = genre
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._client    = None   # lazy

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def run(
        self,
        chunks: list,
        title:  str = "",
        on_progress: Callable[[str, float], None] | None = None,
    ) -> tuple[Path, Path, Path]:
        """
        Returns (script_path, script_diac_path, script_meta_path).
        """
        _prog = on_progress or (lambda s, p: None)

        # Step 4a: Reader per chunk
        _prog("Extracting key ideas per chunk …", 0.72)
        notes = self._reader_pass(chunks)

        # Step 4b: Consolidator
        _prog("Consolidating book outline …", 0.76)
        outline = self._consolidator(notes, title)

        # Step 5 + 6: Scriptwriter + Editor loop
        _prog("Writing script …", 0.80)
        result = self._scriptwriter_editor_loop(outline, title)

        # Step 7: Diacritize
        _prog("Diacritizing script …", 0.92)
        result.script_diac = self._diacritize(result.script)

        # Write files
        stem        = Path(title).stem if title else "book"
        safe_stem   = re.sub(r'[^\w\u0600-\u06FF\-]', '_', stem)[:50] or "book"
        script_path      = self.output_dir / f"{safe_stem}_script.txt"
        script_diac_path = self.output_dir / f"{safe_stem}_script_diacritized.txt"
        script_meta_path = self.output_dir / f"{safe_stem}_script_metadata.json"

        script_path.write_text(result.script, encoding="utf-8")
        script_diac_path.write_text(result.script_diac, encoding="utf-8")
        script_meta_path.write_text(
            json.dumps({
                "title":          title,
                "genre":          self.genre,
                "word_count":     result.word_count,
                "scores":         result.scores,
                "total_score":    result.total_score,
                "retries_used":   result.retries_used,
                "editor_feedback": result.editor_feedback,
                "warnings":       result.warnings,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        logger.info(
            "Script written: %d words, score %d/50, %d retries.",
            result.word_count, result.total_score, result.retries_used,
        )
        return script_path, script_diac_path, script_meta_path

    # ------------------------------------------------------------------ #
    #  Step 4a — Reader agent (Haiku, per chunk)                          #
    # ------------------------------------------------------------------ #

    def _reader_pass(self, chunks: list) -> list[str]:
        """Extract 3-5 key ideas from each chunk. Uses Haiku for low cost."""
        notes = []
        # For very large books, group chunks to avoid too many API calls.
        # Target: ~40 API calls max regardless of book size.
        group_size = max(1, len(chunks) // 40)
        grouped = self._group_chunks(chunks, group_size)

        for i, group_text in enumerate(grouped):
            logger.debug("Reader: group %d/%d", i + 1, len(grouped))
            prompt = (
                "استخرج من هذا المقطع 3-5 أفكار رئيسية بالعربية الفصحى "
                "في شكل نقاط مختصرة. أجب بالنقاط فقط دون مقدمة.\n\n"
                f"{group_text[:3000]}"   # cap to avoid overrun
            )
            try:
                response = self._call(prompt, model=_HAIKU, max_tokens=200)
                notes.append(response)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Reader failed for group %d: %s", i + 1, exc)
        return notes

    # ------------------------------------------------------------------ #
    #  Step 4b — Consolidator (Haiku, one call)                           #
    # ------------------------------------------------------------------ #

    def _consolidator(self, notes: list[str], title: str) -> str:
        """Merge chunk notes into a structured book outline."""
        notes_text = "\n\n".join(notes) if notes else "لا توجد ملاحظات متاحة."
        prompt = (
            f"أنت محرر أدبي. فيما يلي ملاحظات من كتاب بعنوان «{title}».\n"
            "اصنع منها مخططاً منظماً للكتاب يشمل:\n"
            "- الفكرة المحورية الرئيسية\n"
            "- ثلاث إلى خمس نقاط جوهرية\n"
            "- لحظة أو مشهد بارز يمكن استخدامه كخطاف\n"
            "- الخاتمة أو الدرس الذي يتركه الكتاب\n"
            "أجب بالعربية الفصحى في 200-300 كلمة.\n\n"
            f"الملاحظات:\n{notes_text[:4000]}"
        )
        try:
            return self._call(prompt, model=_HAIKU, max_tokens=500)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Consolidator failed: %s", exc)
            return notes_text[:2000]   # fall back to raw notes

    # ------------------------------------------------------------------ #
    #  Step 5 — Scriptwriter (Sonnet, one call)                           #
    # ------------------------------------------------------------------ #

    def _write_script(self, outline: str, title: str, feedback: str = "") -> str:
        tone = _GENRE_TONE.get(self.genre, _GENRE_TONE["non-fiction"])
        revision_note = (
            f"\nملاحظات المحرر للمراجعة:\n{feedback}\n" if feedback else ""
        )
        prompt = (
            f"أنت كاتب سيناريو محترف متخصص في المحتوى الثقافي العربي.\n"
            f"بناءً على المخطط التالي لكتاب «{title}» من نوع {self.genre}،\n"
            "اكتب سكريبت بالعربية الفصحى لفيديو مدته 4-5 دقائق (700-800 كلمة) يشتمل على:\n"
            "1. خطاف افتتاحي مشوّق — الجملة الأولى تجذب الانتباه فوراً\n"
            "2. ثلاث نقاط محورية من الكتاب مع أمثلة أو لحظات بارزة\n"
            "3. خاتمة تدفع المستمع للتفكير أو القراءة\n"
            f"النبرة: {tone}.\n"
            "لا تبدأ بـ'في هذا الفيديو' أو ما شابهها. لا تذكر كلمة 'سكريبت'.\n"
            f"{revision_note}"
            f"\nمخطط الكتاب:\n{outline}"
        )
        return self._call(prompt, model=_SONNET, max_tokens=1200)

    # ------------------------------------------------------------------ #
    #  Step 6 — Editor / Scorer (Haiku, up to 2 retries)                  #
    # ------------------------------------------------------------------ #

    def _score_script(self, script: str) -> tuple[dict[str, int], str]:
        """Score script on 5 criteria (0-10 each). Returns (scores, feedback)."""
        word_count = len(script.split())
        prompt = (
            "أنت محرر محترف. قيّم هذا السكريبت العربي على المعايير التالية،\n"
            "وأعط لكل معيار درجة من 0 إلى 10، ثم اشرح سبب التقييم باختصار.\n"
            "أجب بتنسيق JSON فقط بالمفاتيح التالية:\n"
            '{"hook": <0-10>, "structure": <0-10>, "pacing": <0-10>, '
            '"clarity": <0-10>, "tone": <0-10>, "feedback": "<نص>"}\n\n'
            f"عدد الكلمات: {word_count} (المطلوب: 700-800)\n\n"
            f"السكريبت:\n{script[:2500]}"
        )
        try:
            raw = self._call(prompt, model=_HAIKU, max_tokens=400)
            # Extract JSON from response
            m = re.search(r'\{.*\}', raw, re.DOTALL)
            data = json.loads(m.group()) if m else {}
            scores = {
                "hook":      int(data.get("hook", 5)),
                "structure": int(data.get("structure", 5)),
                "pacing":    int(data.get("pacing", 5)),
                "clarity":   int(data.get("clarity", 5)),
                "tone":      int(data.get("tone", 5)),
            }
            feedback = str(data.get("feedback", ""))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Scorer failed: %s", exc)
            scores   = {"hook": 5, "structure": 5, "pacing": 5, "clarity": 5, "tone": 5}
            feedback = ""
        return scores, feedback

    def _scriptwriter_editor_loop(
        self, outline: str, title: str
    ) -> ScriptResult:
        """Write → score → revise loop (max _MAX_RETRIES revisions)."""
        feedback   = ""
        script     = ""
        scores     = {}
        total      = 0
        retries    = 0

        for attempt in range(_MAX_RETRIES + 1):
            try:
                script = self._write_script(outline, title, feedback)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Scriptwriter failed (attempt %d): %s", attempt, exc)
                break

            scores, feedback = self._score_script(script)
            total = sum(scores.values())
            logger.info(
                "Script attempt %d — score %d/50, words %d",
                attempt + 1, total, len(script.split()),
            )
            if total >= _SCORE_PASS:
                break
            retries += 1

        return ScriptResult(
            script       = script,
            script_diac  = "",   # filled in after
            scores       = scores,
            total_score  = total,
            word_count   = len(script.split()),
            retries_used = retries,
            editor_feedback = feedback,
        )

    # ------------------------------------------------------------------ #
    #  Step 7 — Diacritize (Mishkal, local, no API cost)                  #
    # ------------------------------------------------------------------ #

    def _diacritize(self, text: str) -> str:
        if not text.strip():
            return text
        try:
            from mishkal.tashkeel import TashkeelClass  # noqa: PLC0415
            tashkeel = TashkeelClass()
            # Process in sentence-level chunks to avoid Mishkal memory issues
            sentences = re.split(r'(?<=[.؟!\n])', text)
            results   = [tashkeel.tashkeel(s) for s in sentences if s.strip()]
            return " ".join(results)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Diacritization failed: %s — returning plain script.", exc)
            return text

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    def _get_client(self):
        if self._client is None:
            import anthropic  # noqa: PLC0415
            self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    def _call(self, prompt: str, model: str, max_tokens: int) -> str:
        client = self._get_client()
        msg = client.messages.create(
            model      = model,
            max_tokens = max_tokens,
            messages   = [{"role": "user", "content": prompt}],
        )
        return msg.content[0].text.strip()

    @staticmethod
    def _group_chunks(chunks: list, size: int) -> list[str]:
        """Merge consecutive chunks into groups for batched Reader calls."""
        groups = []
        for i in range(0, len(chunks), size):
            batch = chunks[i:i + size]
            groups.append("\n\n".join(c.text for c in batch))
        return groups
