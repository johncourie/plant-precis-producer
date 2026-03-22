# core/ — Implementation Context

## Phase 4 scope: compile_pdf.py only
Do not modify any other file in this directory during phase 4 unless a bug is
discovered that directly breaks PDF compilation. Document any such change explicitly.

## Extraction templates
Six named templates defined in `/extraction_templates.json`. Each source in the
DB carries one assigned template in the `extraction_template` field. The compiler
reads this field — it does NOT infer template from source content at runtime.

Template → boundary detection strategy:
- felter_style: ALL-CAPS header line detection
- bhp_style: bold section header + drug name line  
- pharmacopoeia_style: numbered section with drug name
- dispensatory_style: centered header + em dash rules
- journal_article: full document; emit abstract + conclusions block
- low_structure_fallback: hit page ± 0 (N=1), always flags as degraded

## Degraded sources
N=1 is already enforced in query.py. The compiler receives pre-truncated page
lists for degraded sources. Do not re-expand them. Every degraded result must
carry a visible flag in the PDF output — both in the TOC and in a header on the
extracted content itself.

## Output contract — non-negotiable
Every extracted unit in the compiled PDF must carry:
- Source title, author, year
- Page range
- Lens tags (all four axes)
- OCR confidence score
- Extraction template used
- Any flags (degraded_ocr, boundary_fallback, etc.)

No anonymous content. No unattributed pages.

## PDF + JSON independence
compile_pdf.py and compile_json.py must succeed and fail independently.
A PDF compilation failure must not suppress JSON output and vice versa.
Both receive the same manifest dict as input.

## TOC with clickable bookmarks
The output PDF requires a clickable TOC grouped by tradition axis (primary)
then temporal axis (secondary). Each TOC entry must be a working internal
bookmark link to the relevant page. Use reportlab bookmarks or weasyprint
anchors depending on which library is already in requirements.txt.

## Index files are read-only from this module
compile_pdf.py reads from _indexes/ via the manifest page ranges.
It never writes to _indexes/, never triggers re-indexing, never modifies
source metadata in the DB.

## Failure modes to handle explicitly
1. Source file missing at compile time → note in TOC, skip, do not abort
2. Boundary detection fails for template → fall back to low_structure_fallback,
   add boundary_fallback flag, do not abort
3. Page range out of bounds for source → clamp to actual page count, add flag
4. Total output would be zero pages → return error to caller, do not emit empty PDF
