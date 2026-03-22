"""Ingestion pipeline: probe, OCR scoring, index build, atomic swap."""

import json
import os
import tempfile
import shutil
from pathlib import Path
from typing import Optional

import pdfplumber

from core.database import get_connection


def ocr_confidence(text: str) -> float:
    """Score OCR quality of extracted text. Returns 0.0–1.0."""
    if not text or len(text) < 100:
        return 0.0
    alpha_ratio = sum(c.isalpha() for c in text) / len(text)
    word_count = len(text.split())
    avg_word_len = len(text.replace(" ", "")) / max(word_count, 1)
    noise_chars = sum(1 for c in text if c in "|}{\\^~`")
    noise_ratio = noise_chars / len(text)
    score = (alpha_ratio * 0.5) + (min(avg_word_len, 8) / 8 * 0.3) - (noise_ratio * 0.2)
    return max(0.0, min(1.0, score))


def probe_pdf(file_path: str) -> dict:
    """Extract first 20 and last 25 pages, assess structure and quality."""
    result = {
        "file": file_path,
        "total_pages": 0,
        "ocr_confidence": 0.0,
        "has_toc": False,
        "has_back_index": False,
        "language": "en",
        "suggested_template": "low_structure_fallback",
        "template_confidence": 0.0,
        "front_text": "",
        "back_text": "",
    }

    try:
        with pdfplumber.open(file_path) as pdf:
            result["total_pages"] = len(pdf.pages)

            # Extract front pages
            front_pages = min(20, len(pdf.pages))
            front_text = ""
            for i in range(front_pages):
                page_text = pdf.pages[i].extract_text() or ""
                front_text += page_text + "\n"

            # Extract back pages
            back_start = max(0, len(pdf.pages) - 25)
            back_text = ""
            for i in range(back_start, len(pdf.pages)):
                page_text = pdf.pages[i].extract_text() or ""
                back_text += page_text + "\n"

            combined = front_text + back_text
            result["ocr_confidence"] = ocr_confidence(combined)
            result["front_text"] = front_text[:5000]
            result["back_text"] = back_text[:5000]

            # Structure detection
            front_lower = front_text.lower()
            if "table of contents" in front_lower or "contents" in front_lower[:2000]:
                result["has_toc"] = True
            back_lower = back_text.lower()
            if "index" in back_lower[:500]:
                result["has_back_index"] = True

            # Template suggestion
            result["suggested_template"], result["template_confidence"] = _suggest_template(
                front_text, back_text
            )

    except Exception as e:
        result["error"] = str(e)

    return result


def _suggest_template(front_text: str, back_text: str) -> tuple[str, float]:
    """Heuristic template matching based on text patterns."""
    import re

    # Check for ALL-CAPS headers (felter_style)
    caps_lines = len(re.findall(r"^[A-Z][A-Z\s]{5,}$", front_text, re.MULTILINE))
    if caps_lines > 3:
        return "felter_style", min(0.5 + caps_lines * 0.05, 0.95)

    # Check for numbered sections (pharmacopoeia_style)
    numbered = len(re.findall(r"^\d+\.\d+", front_text, re.MULTILINE))
    if numbered > 5:
        return "pharmacopoeia_style", min(0.5 + numbered * 0.03, 0.9)

    # Check for centered headers with em dashes (dispensatory_style)
    em_dashes = front_text.count("—") + front_text.count("--")
    if em_dashes > 10:
        return "dispensatory_style", 0.6

    return "low_structure_fallback", 0.3


def build_index(source_id: str, data_dir: str = ".") -> str:
    """Build a text index for a source. Returns path to index file.

    Uses atomic swap: builds to temp file, then moves into place.
    """
    conn = get_connection(data_dir)
    try:
        source = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
        if not source:
            raise ValueError(f"Source not found: {source_id}")

        conn.execute(
            "UPDATE sources SET index_status = 'building', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (source_id,),
        )
        conn.commit()

        index_dir = Path(data_dir) / "_indexes"
        index_dir.mkdir(exist_ok=True)
        index_path = index_dir / f"{source_id}.txt"

        # Build index to temp file
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".txt", dir=str(index_dir))
        try:
            with pdfplumber.open(source["file"]) as pdf, os.fdopen(tmp_fd, "w") as f:
                for i, page in enumerate(pdf.pages):
                    text = page.extract_text() or ""
                    if text.strip():
                        f.write(f"--- PAGE {i + 1} ---\n")
                        f.write(text)
                        f.write("\n\n")

            # Atomic swap
            shutil.move(tmp_path, str(index_path))

            conn.execute(
                "UPDATE sources SET index_status = 'ready', index_file = ?, last_indexed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (str(index_path), source_id),
            )
            conn.commit()
            return str(index_path)

        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            conn.execute(
                "UPDATE sources SET index_status = 'failed', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (source_id,),
            )
            conn.commit()
            raise
    finally:
        conn.close()


def register_source(metadata: dict, data_dir: str = ".") -> str:
    """Register a new source in the database. Returns source ID."""
    conn = get_connection(data_dir)
    try:
        lens = metadata.get("lens_tags", {})
        conn.execute(
            """INSERT INTO sources (
                id, title, author, year, edition, publisher, file, file_type,
                lens_temporal, lens_epistemic, lens_tradition, lens_evidential_weight,
                extraction_template, offset_mode, page_offset, typical_monograph_pages,
                ocr_confidence, language, index_type, notes, citation_template,
                degraded, degraded_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                metadata["id"],
                metadata["title"],
                metadata["author"],
                metadata.get("year"),
                metadata.get("edition"),
                metadata.get("publisher"),
                metadata["file"],
                metadata.get("file_type", "pdf"),
                json.dumps(lens.get("temporal", [])) if isinstance(lens.get("temporal"), list) else json.dumps([lens.get("temporal")] if lens.get("temporal") else []),
                json.dumps(lens.get("epistemic", [])) if isinstance(lens.get("epistemic"), list) else json.dumps([lens.get("epistemic")] if lens.get("epistemic") else []),
                json.dumps(lens.get("tradition", [])) if isinstance(lens.get("tradition"), list) else json.dumps([lens.get("tradition")] if lens.get("tradition") else []),
                json.dumps(lens.get("evidential_weight", [])) if isinstance(lens.get("evidential_weight"), list) else json.dumps([lens.get("evidential_weight")] if lens.get("evidential_weight") else []),
                metadata.get("extraction_template", "low_structure_fallback"),
                metadata.get("offset_mode", "fixed"),
                metadata.get("page_offset", 0),
                metadata.get("typical_monograph_pages"),
                metadata.get("ocr_confidence", 0.0),
                metadata.get("language", "en"),
                metadata.get("index_type"),
                metadata.get("notes"),
                metadata.get("citation_template", "{author}. ({year}). {title}. pp. {pages}."),
                metadata.get("degraded", False),
                metadata.get("degraded_reason"),
            ),
        )
        conn.commit()
        return metadata["id"]
    finally:
        conn.close()
