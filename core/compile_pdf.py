"""PDF compilation pipeline — extracts monograph text and compiles précis PDF.

Uses WeasyPrint (HTML→PDF) to produce a scholarly-quality reference document
with clickable TOC, PDF bookmarks, typographic hierarchy, and full source
attribution on every extracted unit.
"""

import re
from collections import OrderedDict
from datetime import datetime, timezone
from html import escape
from pathlib import Path


class CompilationError(Exception):
    """Raised when compilation cannot produce a valid PDF (e.g. zero content)."""
    pass


# Canonical ordering for TOC grouping and sorting
TRADITION_ORDER = [
    "western_folk",
    "eclectic_physiomedicalist",
    "galenic_humoral",
    "ayurvedic",
    "tcm",
    "unani",
    "indigenous_north_american",
    "ethnobotanical",
    "modern_western_herbal",
    "academic_biomedical",
]

TEMPORAL_ORDER = [
    "ancient",
    "early_modern",
    "historical",
    "mid_modern",
    "contemporary",
]

TRADITION_LABELS = {
    "western_folk": "Western Folk",
    "eclectic_physiomedicalist": "Eclectic / Physiomedicalist",
    "galenic_humoral": "Galenic / Humoral",
    "ayurvedic": "Ayurvedic",
    "tcm": "Traditional Chinese Medicine",
    "unani": "Unani Tibb",
    "indigenous_north_american": "Indigenous North American",
    "ethnobotanical": "Ethnobotanical",
    "modern_western_herbal": "Modern Western Herbal",
    "academic_biomedical": "Academic Biomedical",
}

TEMPORAL_LABELS = {
    "ancient": "Ancient (pre-1500)",
    "early_modern": "Early Modern (1500–1850)",
    "historical": "Historical (1850–1950)",
    "mid_modern": "Mid-Modern (1950–1994)",
    "contemporary": "Contemporary (1994–present)",
}


def compile_precis(
    query_results: dict,
    data_dir: str = ".",
    output_dir: str = "precis",
) -> str:
    """Compile a précis PDF from query results.

    Args:
        query_results: Manifest dict from QueryEngine.search()
        data_dir: Root data directory (for locating _indexes/)
        output_dir: Directory for output PDF

    Returns:
        File path to the generated PDF.

    Raises:
        CompilationError: If no content could be extracted (zero pages).
    """
    results = query_results.get("results", [])
    if not results:
        raise CompilationError("No results to compile — query returned zero hits.")

    # Step 1: Group and sort
    grouped = _group_results(results)

    # Step 2: Extract text from indexes
    extracted = {}
    has_content = False
    for result in results:
        source_id = result["source"]["id"]
        text, extra_flags = _extract_source_text(result, data_dir)
        extracted[source_id] = text
        if extra_flags:
            result["flags"] = list(set(result.get("flags", []) + extra_flags))
        if text.strip():
            has_content = True

    if not has_content:
        raise CompilationError(
            "No content could be extracted from any source. "
            "Index files may be missing or empty."
        )

    # Step 3: Build HTML
    html = _build_html(query_results["query"], query_results["compilation_metadata"],
                       grouped, extracted)

    # Step 4: Render PDF
    Path(output_dir).mkdir(exist_ok=True)
    plant_name = (
        query_results["query"].get("resolved_binomial")
        or query_results["query"]["input_string"]
    )
    safe_name = "".join(c if c.isalnum() or c in " _-" else "_" for c in plant_name).strip()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_path = Path(output_dir) / f"{safe_name}_{timestamp}.pdf"

    _render_pdf(html, str(output_path))
    return str(output_path)


# ---------------------------------------------------------------------------
# Step 1: Group and sort results
# ---------------------------------------------------------------------------

def _group_results(results: list) -> OrderedDict:
    """Group results by tradition axis (primary), sort by temporal (secondary).

    Returns OrderedDict mapping tradition key → list of results, in canonical order.
    """
    groups = OrderedDict()

    for result in results:
        tags = result["source"].get("lens_tags", {})
        traditions = tags.get("tradition", [])
        if isinstance(traditions, str):
            traditions = [traditions]

        # Place under first matching tradition in canonical order
        placed = False
        for t in TRADITION_ORDER:
            if t in traditions:
                groups.setdefault(t, []).append(result)
                placed = True
                break
        if not placed:
            groups.setdefault("academic_biomedical", []).append(result)

    # Sort each group by temporal axis
    for tradition in groups:
        groups[tradition].sort(key=lambda r: _temporal_sort_key(r))

    # Reorder to canonical tradition order
    ordered = OrderedDict()
    for t in TRADITION_ORDER:
        if t in groups:
            ordered[t] = groups[t]
    return ordered


def _temporal_sort_key(result: dict) -> int:
    tags = result["source"].get("lens_tags", {})
    temporals = tags.get("temporal", [])
    if isinstance(temporals, str):
        temporals = [temporals]
    for t in temporals:
        if t in TEMPORAL_ORDER:
            return TEMPORAL_ORDER.index(t)
    return len(TEMPORAL_ORDER)


# ---------------------------------------------------------------------------
# Step 2: Extract text from index files
# ---------------------------------------------------------------------------

def _extract_source_text(result: dict, data_dir: str) -> tuple[str, list[str]]:
    """Read monograph text from the source's index file for the hit pages.

    Returns (extracted_text, extra_flags).
    """
    source_id = result["source"]["id"]
    hit_pages = set(result["extraction"].get("hit_page_numbers", []))
    extra_flags = []

    if not hit_pages:
        return "", ["no_hit_pages"]

    # Locate index file
    index_path = Path(data_dir) / "_indexes" / f"{source_id}.txt"
    if not index_path.exists():
        return "", ["source_unavailable"]

    try:
        raw = index_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return "", ["source_unavailable"]

    # Parse --- PAGE N --- blocks, collect text for hit pages
    pages_found = {}
    current_page = 0
    current_lines = []

    for line in raw.split("\n"):
        page_match = re.match(r"--- PAGE (\d+) ---", line)
        if page_match:
            if current_page in hit_pages and current_lines:
                pages_found[current_page] = "\n".join(current_lines)
            current_page = int(page_match.group(1))
            current_lines = []
        else:
            current_lines.append(line)

    # Flush last page
    if current_page in hit_pages and current_lines:
        pages_found[current_page] = "\n".join(current_lines)

    # Check for clamped pages (requested but not found in index)
    missing = hit_pages - set(pages_found.keys())
    if missing:
        extra_flags.append("page_range_clamped")

    # Assemble text in page order
    text = "\n\n".join(pages_found[p] for p in sorted(pages_found.keys()))
    return text.strip(), extra_flags


# ---------------------------------------------------------------------------
# Step 3: Build HTML document
# ---------------------------------------------------------------------------

def _build_html(
    query_info: dict,
    compilation_meta: dict,
    grouped: OrderedDict,
    extracted: dict[str, str],
) -> str:
    plant_name = escape(query_info.get("resolved_binomial") or query_info["input_string"])
    synonyms = query_info.get("synonyms_matched", [])
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    parts = [
        "<!DOCTYPE html>",
        "<html lang='en'>",
        "<head><meta charset='utf-8'>",
        f"<title>Précis — {plant_name}</title>",
        "<style>",
        _css(plant_name),
        "</style>",
        "</head>",
        "<body>",
        _cover_html(plant_name, synonyms, timestamp, compilation_meta),
        _toc_html(grouped),
        _sections_html(grouped, extracted),
        "</body></html>",
    ]
    return "\n".join(parts)


def _cover_html(
    plant_name: str,
    synonyms: list,
    timestamp: str,
    meta: dict,
) -> str:
    syn_text = ", ".join(escape(s) for s in synonyms[:8]) if synonyms else ""
    summary_parts = [f"{meta.get('sources_hit', 0)} sources across {meta.get('sources_queried', 0)} queried"]
    if meta.get("sources_degraded"):
        summary_parts.append(f"{meta['sources_degraded']} degraded")

    return f"""
    <div class="cover">
        <div class="cover-inner">
            <p class="cover-label">Plant Précis</p>
            <h1 class="cover-title">{plant_name}</h1>
            {"<p class='cover-synonyms'>" + syn_text + "</p>" if syn_text else ""}
            <p class="cover-meta">{' · '.join(summary_parts)}</p>
            <p class="cover-date">{escape(timestamp)}</p>
        </div>
    </div>
    """


def _toc_html(grouped: OrderedDict) -> str:
    lines = ['<div class="toc">', '<h2 class="toc-title">Contents</h2>']

    for tradition, results in grouped.items():
        label = escape(TRADITION_LABELS.get(tradition, tradition.replace("_", " ").title()))
        lines.append(f'<h3 class="toc-group">{label}</h3>')
        lines.append('<ul class="toc-list">')
        for r in results:
            s = r["source"]
            sid = escape(s["id"])
            title = escape(s["title"])
            author = escape(s.get("author", ""))
            year = s.get("year", "")
            is_degraded = "degraded_ocr" in r.get("flags", [])
            is_unavailable = "source_unavailable" in r.get("flags", [])

            prefix = ""
            cls = ""
            if is_unavailable:
                prefix = '<span class="toc-warn">⚠ unavailable</span> '
                cls = ' class="toc-degraded"'
            elif is_degraded:
                prefix = '<span class="toc-warn">⚠ degraded</span> '
                cls = ' class="toc-degraded"'

            lines.append(
                f'<li{cls}>{prefix}'
                f'<a href="#source-{sid}">{title}</a>'
                f' <span class="toc-author">({author}, {year})</span></li>'
            )
        lines.append("</ul>")

    lines.append("</div>")
    return "\n".join(lines)


def _sections_html(grouped: OrderedDict, extracted: dict[str, str]) -> str:
    parts = []

    for tradition, results in grouped.items():
        label = escape(TRADITION_LABELS.get(tradition, tradition.replace("_", " ").title()))
        parts.append(f'<h2 class="tradition-heading">{label}</h2>')

        for r in results:
            parts.append(_source_section_html(r, extracted))

    return "\n".join(parts)


def _source_section_html(result: dict, extracted: dict[str, str]) -> str:
    s = result["source"]
    ext = result["extraction"]
    flags = result.get("flags", [])
    sid = escape(s["id"])
    title = escape(s["title"])
    author = escape(s.get("author", ""))
    year = s.get("year", "")
    citation = escape(result.get("citation", ""))
    ocr_pct = int((s.get("ocr_confidence", 0) or 0) * 100)
    template = escape(s.get("extraction_template", ""))
    pages = escape(ext.get("pages", ""))
    is_degraded = "degraded_ocr" in flags
    is_unavailable = "source_unavailable" in flags

    # Lens tag badges
    tags_html = _lens_tags_html(s.get("lens_tags", {}))

    # Flags display
    flags_html = ""
    flag_labels = {
        "degraded_ocr": "degraded OCR",
        "source_unavailable": "source unavailable",
        "page_range_clamped": "page range clamped",
        "boundary_fallback": "boundary fallback",
        "no_hit_pages": "no hit pages",
    }
    visible_flags = [flag_labels.get(f, f) for f in flags if f in flag_labels]
    if visible_flags:
        flags_html = " · ".join(f'<span class="flag">{escape(f)}</span>' for f in visible_flags)

    # Warning callout
    warning_html = ""
    if is_degraded:
        warning_html = (
            '<div class="warning-callout">'
            '⚠ Degraded OCR quality. Results shown but may be incomplete.'
            '</div>'
        )
    elif is_unavailable:
        warning_html = (
            '<div class="warning-callout">'
            '⚠ Source file unavailable. Index could not be read.'
            '</div>'
        )

    # Body text
    source_text = extracted.get(s["id"], "")
    if source_text.strip():
        body_paragraphs = _text_to_paragraphs(source_text)
    else:
        body_paragraphs = '<p class="no-content">No content could be extracted from this source.</p>'

    return f"""
    <section class="source-section" id="source-{sid}">
        <div class="source-header">
            <h3 class="source-title">{title}</h3>
            <p class="source-author">{author}, {year}</p>
            <div class="source-tags">{tags_html}</div>
            <p class="source-meta">
                Extraction template: {template} · OCR confidence: {ocr_pct}% · Pages: {pages}
                {' · ' + flags_html if flags_html else ''}
            </p>
            {warning_html}
            <p class="source-citation">{citation}</p>
        </div>
        <div class="source-body">
            {body_paragraphs}
        </div>
    </section>
    """


def _lens_tags_html(lens_tags: dict) -> str:
    badges = []
    for axis in ["tradition", "temporal", "epistemic", "evidential_weight"]:
        vals = lens_tags.get(axis, [])
        if isinstance(vals, str):
            vals = [vals]
        for v in vals:
            if v:
                label = v.replace("_", " ")
                badges.append(f'<span class="tag">{escape(label)}</span>')
    return " ".join(badges)


def _text_to_paragraphs(text: str) -> str:
    """Convert extracted text to HTML paragraphs, preserving structure."""
    # Split on double newlines for paragraph breaks
    blocks = re.split(r"\n{2,}", text.strip())
    parts = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        # Preserve single newlines within a block as line breaks
        content = escape(block).replace("\n", "<br>")
        parts.append(f"<p>{content}</p>")
    return "\n".join(parts) if parts else '<p class="no-content">No content could be extracted.</p>'


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

def _css(plant_name: str) -> str:
    # Escape plant name for use in CSS content strings
    css_plant = plant_name.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')

    return f"""
    @import url('https://fonts.googleapis.com/css2?family=EB+Garamond:ital,wght@0,400;0,500;0,600;0,700;1,400;1,500&family=DM+Sans:wght@300;400;500;600&display=swap');

    @page {{
        size: A4;
        margin: 25mm 20mm 22mm 20mm;

        @top-left {{
            content: "{css_plant}";
            font-family: 'EB Garamond', Georgia, serif;
            font-size: 8pt;
            font-style: italic;
            color: #9a9080;
        }}
        @top-right {{
            content: "Plant Précis";
            font-family: 'DM Sans', sans-serif;
            font-size: 7.5pt;
            font-weight: 500;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: #9a9080;
        }}
        @bottom-center {{
            content: counter(page);
            font-family: 'DM Sans', sans-serif;
            font-size: 8pt;
            color: #9a9080;
        }}
    }}

    @page :first {{
        @top-left {{ content: none; }}
        @top-right {{ content: none; }}
        @bottom-center {{ content: none; }}
    }}

    /* --- Base --- */

    * {{ margin: 0; padding: 0; box-sizing: border-box; }}

    body {{
        font-family: 'EB Garamond', Georgia, serif;
        font-size: 11pt;
        line-height: 1.55;
        color: #1a1814;
        background: #ffffff;
    }}

    /* --- Cover --- */

    .cover {{
        page-break-after: always;
        display: flex;
        align-items: center;
        justify-content: center;
        min-height: 80%;
        text-align: center;
    }}

    .cover-inner {{
        max-width: 80%;
    }}

    .cover-label {{
        font-family: 'DM Sans', sans-serif;
        font-size: 9pt;
        font-weight: 600;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: #5a7a4a;
        margin-bottom: 12pt;
    }}

    .cover-title {{
        font-family: 'EB Garamond', Georgia, serif;
        font-size: 32pt;
        font-weight: 500;
        font-style: italic;
        color: #1a1814;
        margin-bottom: 8pt;
        line-height: 1.15;
    }}

    .cover-synonyms {{
        font-size: 11pt;
        font-style: italic;
        color: #6b6358;
        margin-bottom: 20pt;
    }}

    .cover-meta {{
        font-family: 'DM Sans', sans-serif;
        font-size: 9pt;
        color: #6b6358;
        margin-bottom: 4pt;
    }}

    .cover-date {{
        font-family: 'DM Sans', sans-serif;
        font-size: 8pt;
        color: #9a9080;
    }}

    /* --- Table of Contents --- */

    .toc {{
        page-break-after: always;
    }}

    .toc-title {{
        font-family: 'EB Garamond', Georgia, serif;
        font-size: 22pt;
        font-weight: 500;
        margin-bottom: 18pt;
        padding-bottom: 6pt;
        border-bottom: 1px solid #d4cdc2;
        bookmark-level: none;
    }}

    .toc-group {{
        font-family: 'DM Sans', sans-serif;
        font-size: 9pt;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: #5a7a4a;
        margin-top: 14pt;
        margin-bottom: 4pt;
        bookmark-level: none;
    }}

    .toc-list {{
        list-style: none;
        padding-left: 0;
    }}

    .toc-list li {{
        font-size: 10pt;
        line-height: 1.7;
        padding-left: 0;
    }}

    .toc-list a {{
        color: #1a1814;
        text-decoration: none;
    }}

    .toc-author {{
        font-size: 9pt;
        color: #6b6358;
    }}

    .toc-degraded {{
        color: #9a9080;
    }}

    .toc-degraded a {{
        color: #9a9080;
    }}

    .toc-warn {{
        font-family: 'DM Sans', sans-serif;
        font-size: 7.5pt;
        font-weight: 500;
        color: #b08a3e;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }}

    /* --- Tradition Group Headings --- */

    .tradition-heading {{
        font-family: 'EB Garamond', Georgia, serif;
        font-size: 18pt;
        font-weight: 500;
        color: #1a1814;
        margin-top: 24pt;
        margin-bottom: 6pt;
        padding-bottom: 4pt;
        border-bottom: 2px solid #5a7a4a;
        bookmark-level: 1;
    }}

    /* --- Source Sections --- */

    .source-section {{
        margin-top: 20pt;
        page-break-inside: avoid;
    }}

    .source-header {{
        background: #f5f0e8;
        border: 1px solid #d4cdc2;
        border-radius: 2pt;
        padding: 12pt 14pt;
        margin-bottom: 10pt;
    }}

    .source-title {{
        font-family: 'EB Garamond', Georgia, serif;
        font-size: 16pt;
        font-weight: 600;
        color: #1a1814;
        margin-bottom: 2pt;
        bookmark-level: 2;
    }}

    .source-author {{
        font-family: 'EB Garamond', Georgia, serif;
        font-size: 11pt;
        color: #6b6358;
        margin-bottom: 6pt;
    }}

    .source-tags {{
        margin-bottom: 6pt;
    }}

    .tag {{
        display: inline-block;
        font-family: 'DM Sans', sans-serif;
        font-size: 7.5pt;
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: #5a7a4a;
        border: 1px solid #5a7a4a;
        border-radius: 2pt;
        padding: 1pt 5pt;
        margin-right: 3pt;
        margin-bottom: 2pt;
    }}

    .source-meta {{
        font-family: 'DM Sans', sans-serif;
        font-size: 8pt;
        color: #6b6358;
        margin-bottom: 4pt;
    }}

    .flag {{
        color: #b08a3e;
        font-weight: 500;
    }}

    .warning-callout {{
        font-family: 'DM Sans', sans-serif;
        font-size: 8.5pt;
        background: rgba(176, 138, 62, 0.12);
        border-left: 3pt solid #b08a3e;
        color: #5a3800;
        padding: 6pt 10pt;
        margin: 6pt 0;
    }}

    .source-citation {{
        font-size: 9pt;
        font-style: italic;
        color: #6b6358;
        margin-top: 4pt;
    }}

    /* --- Source Body --- */

    .source-body {{
        margin-top: 8pt;
        margin-bottom: 16pt;
    }}

    .source-body p {{
        font-family: 'EB Garamond', Georgia, serif;
        font-size: 11pt;
        line-height: 1.55;
        color: #1a1814;
        margin-bottom: 6pt;
        text-align: justify;
        hyphens: auto;
    }}

    .no-content {{
        font-style: italic;
        color: #9a9080;
    }}

    /* --- Separator between sections --- */

    .source-section + .source-section {{
        border-top: 1px solid #d4cdc2;
        padding-top: 16pt;
    }}
    """


# ---------------------------------------------------------------------------
# Step 4: Render PDF
# ---------------------------------------------------------------------------

def _render_pdf(html: str, output_path: str) -> None:
    from weasyprint import HTML
    HTML(string=html).write_pdf(output_path)
