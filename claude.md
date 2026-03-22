# Plant Précis Producer — Build Specification v2.0

## What You Are Building

A local-first botanical research tool for herbalists, students, pharmacognosists, and scientists. Given a plant query, it searches a user-maintained corpus of botanical texts (pharmacopoeias, dispensatories, monographs, journal papers) simultaneously and compiles results into a structured précis PDF and optionally a JSON export.

This is a complete greenfield build. Do not reference or port any prior implementation. Start from this specification.

---

## Design Philosophy

**Aesthetic mandate**: This tool is used by people who care deeply about plants, scholarship, and craft. The UI must reflect that. Target aesthetic: refined editorial — the feeling of a well-designed academic journal or a serious reference app (think Readwise, Linear, or a premium field guide). Clean typographic hierarchy, generous whitespace, purposeful color, zero visual noise. No Bootstrap defaults. No generic gradients. No rounded-everything. Pick fonts that have character appropriate to botanical scholarship — a serif with weight and history for display text, a legible humanist monospace or grotesque for data. Implement dark mode as default with a light toggle.

**Principle**: Complexity lives in the data model and pipeline, not the UI. The interface should feel calm and inevitable.

**Installation accessibility**: A first-year herbal medicine student with no technical background must be able to install and run this. Every sharp edge in the install path is a failure of the tool, not a failure of the user.

---

## Architecture: Three Isolated Interfaces

The system has three distinct interfaces that share a data layer but are architecturally separated. They may share chrome (a sidebar nav, for example) but their logic, failure modes, and user roles are different enough that coupling them will introduce the same generalizability problems this build is designed to avoid.

```
┌─────────────────────────────────────────────────────────┐
│                    Shared Data Layer                     │
│         SQLite (metadata) + Text indexes (_indexes/)     │
│              Synonym registry + Source registry          │
└────────────┬────────────────┬───────────────────────────┘
             │                │                │
    ┌────────▼──────┐ ┌───────▼──────┐ ┌──────▼──────────┐
    │   INGESTION   │ │    QUERY /   │ │   LIBRARY /     │
    │   INTERFACE   │ │   PRÉCIS     │ │   JSON EXPORT   │
    │               │ │   INTERFACE  │ │   INTERFACE     │
    └───────────────┘ └──────────────┘ └─────────────────┘
```

---

## Formal Data Model

### 1. Source Metadata Schema

Every source in the corpus carries these fields. This schema is the canonical definition — all other components derive from it.

```json
{
  "id": "felter_eclectic_materia_medica",
  "title": "The Eclectic Materia Medica, Pharmacology and Therapeutics",
  "author": "Felter, Harvey Wickes",
  "year": 1922,
  "edition": "1st",
  "publisher": "John K. Scudder",
  "file": "relative/path/to/file.pdf",
  "file_type": "pdf",

  "lens_tags": {
    "temporal": "historical",
    "epistemic": "clinical_observation",
    "tradition": "eclectic_physiomedicalist",
    "evidential_weight": "case_series"
  },

  "extraction_template": "felter_style",
  "offset_mode": "fixed",
  "page_offset": 0,
  "typical_monograph_pages": "3-6",
  "ocr_confidence": 0.91,
  "language": "en",
  "index_file": "_indexes/felter_eclectic_materia_medica.txt",
  "index_type": "back_of_book",
  "notes": "Back-of-book index. Entries by common and Latin name.",
  "citation_template": "{author}. ({year}). {title}. pp. {pages}.",
  "degraded": false,
  "degraded_reason": null
}
```

### 2. Lens Axes (Four Orthogonal Axes)

Lenses are query filters. Each source carries tags on all four axes. A query can filter on any combination.

#### Axis 1 — Temporal
| Value | Description |
|---|---|
| `ancient` | Pre-1500; classical antiquity and medieval |
| `early_modern` | 1500–1850; Renaissance to early industrial |
| `historical` | 1850–1950; eclectic, physiomedicalist, early pharmacopoeia era |
| `mid_modern` | 1950–1994; post-RCT paradigm, pre-internet |
| `contemporary` | 1994–present |

#### Axis 2 — Epistemic/Methodological
| Value | Description |
|---|---|
| `folk_record` | Oral tradition, ethnobotanical field record |
| `formal_system` | Codified within a healing system (Galenic, TCM, Ayurvedic) |
| `clinical_observation` | Physician/practitioner case observation (non-controlled) |
| `analytical` | Pharmacognostic, phytochemical, microscopy, authentication |
| `controlled_research` | Experimental, RCT, in vitro/in vivo study |
| `regulatory_synthesis` | Standards body synthesis (USP, ESCOP, WHO, HMPC) |
| `systematic_review` | Meta-analysis, Cochrane-style synthesis |

#### Axis 3 — Tradition/System
| Value | Description |
|---|---|
| `western_folk` | Western European/North American folk tradition |
| `eclectic_physiomedicalist` | 19th–20th C American Eclectic and Physiomedical schools |
| `galenic_humoral` | European Galenic/Humoral tradition |
| `ayurvedic` | Indian Ayurvedic tradition |
| `tcm` | Traditional Chinese Medicine |
| `unani` | Unani Tibb |
| `indigenous_north_american` | Indigenous North American traditions |
| `ethnobotanical` | Field-documented indigenous/folk use (researcher-mediated) |
| `modern_western_herbal` | Post-1950 Western clinical herbal medicine |
| `academic_biomedical` | No tradition affiliation; biomedical research context |

#### Axis 4 — Evidential Weight
| Value | Description |
|---|---|
| `anecdote` | Single case, traditional attribution |
| `case_series` | Multiple cases, no control |
| `observational` | Population-level without experimental control |
| `clinical_trial` | Controlled but not randomized, or small RCT |
| `rct` | Randomized controlled trial |
| `meta_analysis` | Systematic review or meta-analysis |
| `expert_consensus` | Standards body position, expert panel |

Sources may carry multiple values on any axis (e.g., a contemporary Ayurvedic pharmacopoeia: `temporal: contemporary`, `tradition: ayurvedic`, `epistemic: regulatory_synthesis`). Use JSON arrays for multi-value.

### 3. Query Schema

```json
{
  "input_string": "yarrow",
  "resolved_binomial": "Achillea millefolium L.",
  "synonyms_matched": ["Achillea millefolium", "Millefolii herba", "yarrow", "milfoil"],
  "lens_filters": {
    "temporal": ["historical", "contemporary"],
    "epistemic": null,
    "tradition": null,
    "evidential_weight": null
  },
  "include_zotero": true,
  "output_formats": ["pdf", "json"]
}
```

`null` on a lens axis = no filter (include all). Empty array = exclude all (invalid, warn user).

### 4. JSON Output Schema

```json
{
  "schema_version": "2.0",
  "query": {
    "input_string": "yarrow",
    "resolved_binomial": "Achillea millefolium L.",
    "synonyms_matched": ["Achillea millefolium", "Millefolii herba", "yarrow", "milfoil"],
    "lens_filters": {},
    "timestamp": "2026-03-22T14:30:00Z"
  },
  "compilation_metadata": {
    "sources_queried": 12,
    "sources_hit": 7,
    "sources_degraded": 1,
    "sources_no_hit": 4
  },
  "results": [
    {
      "source": {
        "id": "felter_eclectic_materia_medica",
        "title": "The Eclectic Materia Medica",
        "author": "Felter, Harvey Wickes",
        "year": 1922,
        "lens_tags": {
          "temporal": "historical",
          "epistemic": "clinical_observation",
          "tradition": "eclectic_physiomedicalist",
          "evidential_weight": "case_series"
        },
        "extraction_template": "felter_style",
        "ocr_confidence": 0.91
      },
      "extraction": {
        "pages": "309-314",
        "page_offset_applied": 0,
        "boundary_method": "header_detection",
        "confidence": 0.87,
        "raw_text": "..."
      },
      "citation": "Felter, Harvey Wickes. (1922). The Eclectic Materia Medica. pp. 309-314.",
      "flags": []
    }
  ]
}
```

### 5. Synonym Registry Schema

```sql
CREATE TABLE synonyms (
  id INTEGER PRIMARY KEY,
  canonical_binomial TEXT NOT NULL,      -- "Achillea millefolium L."
  name_string TEXT NOT NULL,             -- the variant as it appears
  name_type TEXT NOT NULL,               -- 'binomial', 'common', 'drug_name', 'deprecated_binomial', 'transliteration'
  language TEXT DEFAULT 'en',
  source TEXT,                           -- 'POWO', 'corpus_scan', 'user_added'
  UNIQUE(canonical_binomial, name_string)
);
```

Seeded from POWO/IPNI API at init for any plant added to the library. Corpus-internal variants added during indexing. User-editable via library interface.

---

## Extraction Templates

Templates define how monograph boundaries are detected per source type. Each source has one assigned template. Templates are named, versioned, and defined in `extraction_templates.json`.

| Template Name | Used For | Boundary Detection Strategy |
|---|---|---|
| `felter_style` | Felter, Ellingwood, King's | ALL-CAPS header line detection |
| `bhp_style` | BHP, BHMA | Bold section header + drug name line |
| `pharmacopoeia_style` | EP, USP, BP | Numbered section with drug name |
| `dispensatory_style` | Potter's, older dispensatories | Centered header + em dash rules |
| `journal_article` | Zotero, external PDFs | Full document; emit abstract + conclusions block |
| `low_structure_fallback` | Degraded OCR, unknown structure | Emit hit page ± 1 with degradation flag |

When auto-detection at ingestion cannot assign a template with >0.7 confidence, assign `low_structure_fallback` and flag for user review.

---

## Component Specifications

### Component 1: Ingestion Interface

**Purpose**: Get sources into the corpus correctly. This is the highest-leverage quality gate — everything downstream depends on clean ingestion.

**Ingestion is async and must never block the query interface.**

#### Ingestion Workflow

1. **Intake** — File drop, URL fetch, or Zotero sync trigger. Accept: PDF only initially. Validate file is readable before proceeding.

2. **Probe** — Extract first 20 and last 25 pages as text. Assess:
   - OCR confidence score (character density heuristic + noise ratio)
   - Structure detection (TOC present? Back-of-book index? Header patterns?)
   - Language detection
   - Likely extraction template (pattern match against known formats)

3. **Assisted Metadata Tagging** — Present probe results to user with pre-filled suggestions:
   - Suggested lens tags on all four axes (with confidence scores shown)
   - Suggested extraction template
   - Flag if OCR confidence < 0.6 with explicit warning: "This source has degraded text quality. Queries against it will use fallback extraction and results may be incomplete."
   - Let user confirm or override all suggestions before proceeding

4. **Synonym Enrichment** — If title/author suggests a known plant text, pre-populate synonym registry entries. Allow user additions.

5. **Index Build** — Run asynchronously. Atomic swap into queryable state on completion. Never query against a partially-built index. Show progress.

6. **Verification Step** — After indexing, prompt: "Test this source — enter a plant you know is in this text." Run a test query and show the hit. Let user confirm the result looks correct before marking source as verified.

#### OCR Confidence Scoring Heuristic
```python
def ocr_confidence(text: str) -> float:
    if not text or len(text) < 100:
        return 0.0
    alpha_ratio = sum(c.isalpha() for c in text) / len(text)
    word_count = len(text.split())
    avg_word_len = len(text.replace(' ', '')) / max(word_count, 1)
    noise_chars = sum(1 for c in text if c in '|}{\\^~`')
    noise_ratio = noise_chars / len(text)
    score = (alpha_ratio * 0.5) + (min(avg_word_len, 8) / 8 * 0.3) - (noise_ratio * 0.2)
    return max(0.0, min(1.0, score))
```

Sources with confidence < 0.6: `degraded = true`. Still indexed, still queryable, but every result from them carries a degradation flag in both PDF output and JSON. N=1 for page context window on fallback extraction (hit page only).

#### Index Lifecycle Rules
- Source added → async index build → atomic swap → source enters queryable pool
- Source removed → index file deleted → metadata removed → rebuild not required
- Source re-indexed (user-triggered or on file change detection) → build new index → atomic swap → old index deleted
- SQLite metadata DB is source of truth. Index files are derived artifacts and can always be rebuilt from the source PDF + metadata.
- Never assume index state from file presence alone. Always verify against DB.

---

### Component 2: Query / Précis Interface

**Purpose**: Given a plant query and lens filters, search the corpus and compile a précis.

#### Query Workflow

1. **Input** — Accept free text. Common name, binomial, drug name, misspellings, partial matches all valid.

2. **Synonym Resolution**
   - Normalize input (strip extra whitespace, fix common misspellings via fuzzy match)
   - Look up in synonym registry: input → canonical binomial → all attested synonyms
   - If no match: fuzzy search synonym registry, present top 3 candidates, ask user to confirm
   - If still no match: search the indexes directly with the input string as fallback

3. **Lens Filter Selection** — Present four axis filters as independent multi-select dropdowns. Show source counts per selection in real time so users understand what they're filtering. Sensible defaults: all axes unfiltered.

4. **Corpus Search** — Search all sources in queryable pool (sources where index build is complete and verified). Filter by lens tags before searching. Match against all synonym variants.

5. **Results Presentation** — Before compiling, show grouped results by tradition axis (most intuitive grouping for the target users). Let user deselect any result. Show confidence and degradation flags inline.

6. **Zotero Search** — If Zotero enabled and peer_reviewed sources requested: run `zotero_scan.py` with resolved binomial + synonym list. Present results for user selection.

7. **Manifest Build** — Assemble source list with page ranges, lens tags, extraction templates, citations.

8. **Compilation** — Run `compile_precis.py`. Output to `precis/` directory.

#### Failure Mode Handling in Query

| Failure Type | Detection | User Message |
|---|---|---|
| Source-level degraded | `ocr_confidence < 0.6` | "⚠ [Source Name]: degraded OCR quality. Results shown but may be incomplete." |
| Query miss (absent) | Zero hits across all synonym variants | "No entries found for [plant] in [source]. This plant may not be covered." |
| Query miss (extraction failure) | Hit found, boundary detection failed | "Found [plant] in [source] but could not determine monograph boundaries. Showing ±1 page around hit." |
| Source unavailable | PDF file missing or unreadable | "⚠ [Source Name]: file not found. Re-index required." |

All failures noted in output PDF TOC and JSON `flags` array.

---

### Component 3: Library / JSON Export Interface

**Purpose**: Corpus state management, metadata editing, JSON export, and library sharing.

**Features:**
- View all sources with their metadata and lens tags
- Edit any metadata field post-hoc (triggers re-index prompt if index-relevant fields changed)
- Export full library state as a portable `library_manifest.json` — allows curated source sets to be shared between users (e.g., instructor → students)
- Import a `library_manifest.json` (does not transfer PDFs — user must supply those separately; tool validates file presence)
- Export query results as JSON (the structured schema defined above)
- Configure Zotero connection and external directory scans
- View index health: per-source OCR confidence, last indexed timestamp, verification status

---

## Tech Stack

### Backend
- **Python 3.11+**
- **FastAPI** (not Flask — better async support for non-blocking ingestion, auto-generated OpenAPI docs useful for JSON integration)
- **SQLite** via `sqlite3` stdlib — metadata store, synonym registry, source registry
- **pdfplumber** — primary PDF text extraction (handles complex layouts better than pdftotext, pure Python, easier cross-platform install)
- **rapidfuzz** — fuzzy matching for synonym resolution and query normalization
- **reportlab** or **weasyprint** — PDF compilation output (weasyprint preferred if HTML→PDF pipeline is cleaner for the template system)
- **python-magic** — file type validation at ingestion

### Frontend
- **Single-page app served by FastAPI** — Jinja2 templates or a compiled JS bundle in `static/`
- **Vanilla JS with no framework** — reduces install complexity, no Node.js required for end users
- Target aesthetic: refined editorial. Fonts: a serif with scholarly weight for display (Lora, Playfair Display, or EB Garamond), humanist sans for UI chrome (Outfit, DM Sans). Color: deep warm-neutral dark mode default (#1a1814 background, #e8e0d4 text, botanical green accent #5a7a4a). Generous whitespace. Understated micro-interactions (CSS only, no JS animation libraries).
- Clickable TOC in output PDF via reportlab bookmarks or weasyprint anchors.

### Installation
- **Single script install**: `install.sh` (macOS/Linux) and `install.bat` (Windows)
- Installs Python if not present (via pyenv on macOS/Linux, official installer prompt on Windows)
- Creates virtualenv, installs dependencies
- Runs first-launch setup wizard in the browser
- Popover install instructions for Claude Desktop Cowork, Claude Code, and manual CLI paths

### No Node.js dependency for end users.
### No Docker requirement (add a Dockerfile as optional for advanced users).

---

## Demo Deployment

### Primary: Hugging Face Spaces (Gradio)

GitHub Pages is static — won't run a Python backend. Hugging Face Spaces with Gradio is the correct free hosting path.

Build a separate `demo/` directory in the repo:
- Gradio interface wrapping the core query pipeline
- Pre-loaded demo corpus: 4 public domain texts (Potter's, Ellingwood, Felter, King's) — all pre-indexed, committed to the repo
- No Zotero, no ingestion interface (read-only demo corpus)
- Clear "This is a demo with 4 sample texts — install locally to use your full library" messaging
- Auto-deploys from GitHub via HF Spaces GitHub integration

### Secondary: GitHub Pages (Static Demo)
A static landing page only — project description, screenshots, install instructions, link to HF demo and repo. Lives in `docs/` directory, served via GitHub Pages.

---

## Repository Structure

```
plant-precis-producer/
├── README.md
├── install.sh
├── install.bat
├── requirements.txt
├── main.py                        # FastAPI app entry point, port 7734
├── config.json                    # User config (gitignored template provided)
├── books.json                     # Source registry (user-maintained)
├── extraction_templates.json      # Named extraction templates
│
├── core/
│   ├── synonym_resolver.py        # Binomial → synonym graph
│   ├── ingestion.py               # Probe, OCR scoring, index build
│   ├── query.py                   # Search, manifest assembly
│   ├── compile_pdf.py             # PDF compilation pipeline
│   ├── compile_json.py            # JSON export
│   └── zotero_scan.py             # Zotero SQLite integration
│
├── _indexes/                      # Generated, gitignored (except demo set)
├── precis/                        # Output directory, gitignored
│
├── static/
│   ├── style.css
│   ├── app.js
│   └── fonts/
│
├── templates/
│   ├── base.html
│   ├── query.html
│   ├── ingestion.html
│   └── library.html
│
├── demo/                          # Hugging Face Spaces deployment
│   ├── app.py                     # Gradio interface
│   ├── requirements.txt
│   └── _indexes/                  # Pre-built demo indexes committed here
│
└── docs/                          # GitHub Pages static site
    └── index.html
```

---

## Seed Corpus (Public Domain — Ship Pre-Indexed)

These four texts are public domain and available on archive.org. Pre-build their indexes and commit them to `_indexes/`. These are the demo corpus and the default starting point for new installs.

| ID | Title | Author | Year | Temporal | Epistemic | Tradition |
|---|---|---|---|---|---|---|
| `potters` | Potter's Cyclopaedia of Botanical Drugs | Potter/Wren | 1907 | historical | clinical_observation | western_folk |
| `ellingwood` | American Materia Medica | Ellingwood | 1919 | historical | clinical_observation | eclectic_physiomedicalist |
| `felter` | Eclectic Materia Medica | Felter | 1922 | historical | clinical_observation | eclectic_physiomedicalist |
| `kings` | King's American Dispensatory | Felter/Lloyd | 1898 | historical | clinical_observation | eclectic_physiomedicalist |

---

## Build Sequence

Build in this order. Do not build components out of sequence — each layer depends on the previous.

1. **Data layer** — SQLite schema, synonym registry seed, source registry CRUD
2. **Ingestion pipeline** — probe, OCR scoring, index build, atomic swap
3. **Query pipeline** — synonym resolution, corpus search, manifest assembly
4. **PDF compiler** — extraction by template, page assembly, TOC with bookmarks
5. **JSON exporter** — structured output per schema above
6. **FastAPI app** — routes wiring all pipeline components
7. **Frontend** — three interfaces in shared chrome, following aesthetic spec
8. **Install scripts** — macOS/Linux and Windows, first-launch wizard
9. **Demo (Gradio)** — wraps query pipeline, read-only, pre-loaded corpus
10. **Static landing page** — GitHub Pages in `docs/`

---

## Constraints and Invariants

- Never modify a user's Zotero database. Read-only SQLite access only.
- Never query against a partially-built index. Atomic swap enforced.
- Every extracted unit in output carries: source title, author, year, page range, lens tags, OCR confidence, extraction template used, and any flags. No anonymous content in précis output.
- All source files stay in their original locations. The tool indexes and reads; it never moves, copies, or modifies source PDFs.
- The metadata SQLite DB is the source of truth. All other derived files (indexes, precis outputs) can be regenerated from it.
- Failure mode messages are honest and specific. "No results found" and "search failed" are different messages.
- JSON output must be valid and schema-conformant regardless of PDF output success/failure.
