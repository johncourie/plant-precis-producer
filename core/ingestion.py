"""Ingestion pipeline: probe, OCR scoring, index build, atomic swap.

Supports PDF, EPUB, plain text, and HTML sources. The index output format
is identical regardless of input format: --- PAGE N --- delimited text blocks.
"""

import json
import os
import re
import tempfile
import shutil
from pathlib import Path
from typing import Optional

import pdfplumber
from bs4 import BeautifulSoup

from core.database import get_connection
from core.synonym_resolver import SynonymResolver, seed_synonyms_from_powo

SUPPORTED_FORMATS = {"pdf", "epub", "txt", "html"}

EXTENSION_MAP = {
    ".pdf": "pdf",
    ".epub": "epub",
    ".txt": "txt",
    ".text": "txt",
    ".html": "html",
    ".htm": "html",
}

TEXT_CHUNK_SIZE = 3000


class UnsupportedFormatError(Exception):
    """Raised when a source file has an unrecognized or unsupported format."""
    pass


def _detect_file_type(file_path: str) -> str:
    """Auto-detect file_type from extension."""
    ext = Path(file_path).suffix.lower()
    file_type = EXTENSION_MAP.get(ext)
    if not file_type:
        raise UnsupportedFormatError(
            f"Unsupported file extension '{ext}' for '{file_path}'. "
            f"Supported formats: {', '.join(sorted(SUPPORTED_FORMATS))}"
        )
    return file_type


def _extract_text_by_format(file_path: str, file_type: str) -> list[tuple[int, str]]:
    """Extract text from a source file, returning (page_number, text) tuples.

    Page numbering starts at 1. The meaning of "page" varies by format:
      pdf  → physical PDF page
      epub → chapter/spine item
      txt  → ~3000-character chunk
      html → ~3000-character chunk after tag stripping
    """
    if file_type == "pdf":
        return _extract_pdf(file_path)
    elif file_type == "epub":
        return _extract_epub(file_path)
    elif file_type == "txt":
        return _extract_txt(file_path)
    elif file_type == "html":
        return _extract_html(file_path)
    else:
        raise UnsupportedFormatError(
            f"Unsupported file_type '{file_type}'. "
            f"Supported formats: {', '.join(sorted(SUPPORTED_FORMATS))}"
        )


def _extract_pdf(file_path: str) -> list[tuple[int, str]]:
    pages = []
    with pdfplumber.open(file_path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            if text.strip():
                pages.append((i + 1, text))
    return pages


def _extract_epub(file_path: str) -> list[tuple[int, str]]:
    import ebooklib
    from ebooklib import epub

    book = epub.read_epub(file_path)
    pages = []
    page_num = 1
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        raw_html = item.get_content()
        soup = BeautifulSoup(raw_html, "html.parser")
        text = soup.get_text(separator="\n\n")
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if text:
            pages.append((page_num, text))
            page_num += 1
    return pages


def _extract_txt(file_path: str) -> list[tuple[int, str]]:
    raw = Path(file_path).read_text(encoding="utf-8", errors="replace")
    return _chunk_text(raw)


def _extract_html(file_path: str) -> list[tuple[int, str]]:
    raw_html = Path(file_path).read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(raw_html, "html.parser")
    text = soup.get_text(separator="\n\n")
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return _chunk_text(text)


def _chunk_text(text: str) -> list[tuple[int, str]]:
    """Split text into ~3000-character chunks, breaking at paragraph boundaries."""
    if not text.strip():
        return []

    paragraphs = text.split("\n\n")
    pages = []
    current_chunk = ""
    page_num = 1

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if current_chunk and len(current_chunk) + len(para) + 2 > TEXT_CHUNK_SIZE:
            pages.append((page_num, current_chunk))
            page_num += 1
            current_chunk = para
        else:
            current_chunk = current_chunk + "\n\n" + para if current_chunk else para

    if current_chunk.strip():
        pages.append((page_num, current_chunk))

    return pages


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


def probe_source(file_path: str, file_type: str = None) -> dict:
    """Probe a source file: extract sample text, assess structure and quality.

    Works for all supported formats (PDF, EPUB, TXT, HTML).
    """
    if file_type is None:
        file_type = _detect_file_type(file_path)

    result = {
        "file": file_path,
        "file_type": file_type,
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
        pages = _extract_text_by_format(file_path, file_type)
        result["total_pages"] = len(pages)

        if not pages:
            return result

        # Extract front and back sample text
        front_count = min(20, len(pages))
        front_text = "\n".join(text for _, text in pages[:front_count])

        back_start = max(0, len(pages) - 25)
        back_text = "\n".join(text for _, text in pages[back_start:])

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

        # Template suggestion (most meaningful for PDFs, but run for all)
        result["suggested_template"], result["template_confidence"] = _suggest_template(
            front_text, back_text
        )

    except UnsupportedFormatError:
        raise
    except Exception as e:
        result["error"] = str(e)

    return result


# Keep backward-compatible alias
probe_pdf = probe_source


def _suggest_template(front_text: str, back_text: str) -> tuple[str, float]:
    """Heuristic template matching based on text patterns."""
    # Check for ALL-CAPS headers (felter_style)
    caps_lines = len(re.findall(r"^[A-Z][A-Z\s]{5,}$", front_text, re.MULTILINE))
    if caps_lines > 3:
        return "felter_style", min(0.5 + caps_lines * 0.05, 0.95)

    # Check for numbered sections (pharmacopoeia_style)
    numbered = len(re.findall(r"^\d+\.\d+", front_text, re.MULTILINE))
    if numbered > 5:
        return "pharmacopoeia_style", min(0.5 + numbered * 0.03, 0.9)

    # Check for centered headers with em dashes (dispensatory_style)
    em_dashes = front_text.count("\u2014") + front_text.count("--")
    if em_dashes > 10:
        return "dispensatory_style", 0.6

    return "low_structure_fallback", 0.3


_ZONE_TEMPLATES = {"felter_style", "dispensatory_style"}

_MM_ZONE_MARKERS = re.compile(
    r"(?:common\s+name|materia\s+medica|part\s+used|parts?\s+employed|botanical\s+name)",
    re.IGNORECASE,
)


def _detect_materia_medica_zone(pages: list[tuple[int, str]]) -> int | None:
    """Detect the start line of the materia medica section.

    Looks for an ALL-CAPS header (>=10 chars) preceded within 20 lines
    by a zone marker like "COMMON NAME", "MATERIA MEDICA", or "Part used:".

    Returns the 1-based line number of the first qualifying ALL-CAPS header,
    or None if no zone is detected.
    """
    all_lines = []
    for page_num, text in pages:
        for line in text.split("\n"):
            all_lines.append(line)

    caps_re = re.compile(r"^[A-Z][A-Z\s]{9,}$")

    for i, line in enumerate(all_lines):
        if caps_re.match(line.strip()):
            # Look backwards up to 20 lines for a zone marker
            start = max(0, i - 20)
            window = "\n".join(all_lines[start:i])
            if _MM_ZONE_MARKERS.search(window):
                return i + 1  # 1-based
    return None


def build_index(source_id: str, data_dir: str = ".") -> str:
    """Build a text index for a source. Returns path to index file.

    Uses atomic swap: builds to temp file, then moves into place.
    Works for all supported formats via _extract_text_by_format.
    For felter_style/dispensatory_style, detects materia medica zone boundary.
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
            pages = _extract_text_by_format(source["file"], source["file_type"])

            with os.fdopen(tmp_fd, "w") as f:
                for page_num, text in pages:
                    if text.strip():
                        f.write(f"--- PAGE {page_num} ---\n")
                        f.write(text)
                        f.write("\n\n")

            # Detect materia medica zone for structured templates
            mm_line = None
            if source["extraction_template"] in _ZONE_TEMPLATES:
                mm_line = _detect_materia_medica_zone(pages)

            # Atomic swap
            shutil.move(tmp_path, str(index_path))

            # Store zone detection result in notes
            notes_update = ""
            if mm_line is not None:
                existing_notes = source["notes"] or ""
                # Remove any previous materia_medica_line annotation
                cleaned = re.sub(r"materia_medica_line:\s*\d+\s*;?\s*", "", existing_notes).strip()
                new_notes = f"materia_medica_line: {mm_line}" + ("; " + cleaned if cleaned else "")
                conn.execute(
                    "UPDATE sources SET notes = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (new_notes, source_id),
                )

            conn.execute(
                "UPDATE sources SET index_status = 'ready', index_file = ?, last_indexed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (str(index_path), source_id),
            )

            # Enforce degraded flag based on OCR confidence (spec invariant)
            if source["ocr_confidence"] is not None and source["ocr_confidence"] < 0.6:
                conn.execute(
                    "UPDATE sources SET degraded = 1, degraded_reason = 'ocr_confidence_below_threshold', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (source_id,),
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
    """Register a new source in the database. Returns source ID.

    Auto-detects file_type from extension if not explicitly provided.
    """
    # Auto-detect file_type if not provided
    if not metadata.get("file_type"):
        metadata["file_type"] = _detect_file_type(metadata["file"])

    file_type = metadata["file_type"]
    if file_type not in SUPPORTED_FORMATS:
        raise UnsupportedFormatError(
            f"Unsupported file_type '{file_type}'. "
            f"Supported formats: {', '.join(sorted(SUPPORTED_FORMATS))}"
        )

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
                file_type,
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

        # Auto-seed synonyms from POWO if none exist for this plant
        canonical = metadata.get("canonical_binomial")
        if canonical:
            resolver = SynonymResolver(data_dir)
            if not resolver.has_synonyms(canonical):
                seed_synonyms_from_powo(canonical, data_dir)

        return metadata["id"]
    finally:
        conn.close()
