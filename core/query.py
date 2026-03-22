"""Query pipeline: synonym resolution, corpus search, manifest assembly."""

import json
import re
from pathlib import Path
from typing import Optional

from core.database import get_connection
from core.synonym_resolver import SynonymResolver


class QueryEngine:
    def __init__(self, data_dir: str = "."):
        self.data_dir = data_dir
        self.resolver = SynonymResolver(data_dir)

    def search(self, input_string: str, lens_filters: dict = None) -> dict:
        """Execute a corpus search. Returns structured results."""
        # Resolve synonyms
        resolution = self.resolver.resolve(input_string)
        if resolution:
            canonical = resolution["canonical_binomial"]
            search_terms = [s["name"] for s in resolution["synonyms"]]
        else:
            canonical = None
            search_terms = [input_string.strip()]

        # Get filtered sources
        sources = self._get_filtered_sources(lens_filters)

        results = []
        sources_hit = 0
        sources_no_hit = 0
        sources_degraded = 0

        for source in sources:
            if source["degraded"]:
                sources_degraded += 1
            hit = self._search_index(source, search_terms)
            if hit:
                sources_hit += 1
                results.append(hit)
            else:
                sources_no_hit += 1

        return {
            "query": {
                "input_string": input_string,
                "resolved_binomial": canonical,
                "synonyms_matched": search_terms,
                "lens_filters": lens_filters or {},
            },
            "compilation_metadata": {
                "sources_queried": len(sources),
                "sources_hit": sources_hit,
                "sources_degraded": sources_degraded,
                "sources_no_hit": sources_no_hit,
            },
            "results": results,
        }

    def _get_filtered_sources(self, lens_filters: dict = None) -> list:
        """Get sources filtered by lens tags. Only includes ready, queryable sources."""
        conn = get_connection(self.data_dir)
        try:
            rows = conn.execute(
                "SELECT * FROM sources WHERE index_status = 'ready'"
            ).fetchall()

            sources = [dict(r) for r in rows]

            if not lens_filters:
                return sources

            filtered = []
            for s in sources:
                match = True
                for axis in ["temporal", "epistemic", "tradition", "evidential_weight"]:
                    filter_vals = lens_filters.get(axis)
                    if filter_vals is None:
                        continue
                    source_vals = json.loads(s.get(f"lens_{axis}", "[]"))
                    if not any(v in filter_vals for v in source_vals):
                        match = False
                        break
                if match:
                    filtered.append(s)
            return filtered
        finally:
            conn.close()

    def _search_index(self, source: dict, search_terms: list[str]) -> Optional[dict]:
        """Search a source's index for any of the given terms."""
        index_file = source.get("index_file")
        if not index_file or not Path(index_file).exists():
            return None

        try:
            text = Path(index_file).read_text(encoding="utf-8", errors="replace")
        except Exception:
            return None

        # Find matching pages
        pages_with_hits = []
        current_page = 0
        for line in text.split("\n"):
            page_match = re.match(r"--- PAGE (\d+) ---", line)
            if page_match:
                current_page = int(page_match.group(1))
                continue
            line_lower = line.lower()
            for term in search_terms:
                if term.lower() in line_lower:
                    if current_page not in pages_with_hits:
                        pages_with_hits.append(current_page)
                    break

        if not pages_with_hits:
            return None

        pages_with_hits.sort()
        page_offset = source.get("page_offset", 0)

        # Build page ranges
        adjusted = [p + page_offset for p in pages_with_hits]
        page_range = f"{adjusted[0]}-{adjusted[-1]}" if len(adjusted) > 1 else str(adjusted[0])

        # Build citation
        citation = source.get("citation_template", "{author}. ({year}). {title}. pp. {pages}.")
        citation = citation.replace("{author}", source.get("author", ""))
        citation = citation.replace("{year}", str(source.get("year", "")))
        citation = citation.replace("{title}", source.get("title", ""))
        citation = citation.replace("{pages}", page_range)

        flags = []
        if source.get("degraded"):
            flags.append("degraded_ocr")

        return {
            "source": {
                "id": source["id"],
                "title": source["title"],
                "author": source["author"],
                "year": source.get("year"),
                "lens_tags": {
                    "temporal": json.loads(source.get("lens_temporal", "[]")),
                    "epistemic": json.loads(source.get("lens_epistemic", "[]")),
                    "tradition": json.loads(source.get("lens_tradition", "[]")),
                    "evidential_weight": json.loads(source.get("lens_evidential_weight", "[]")),
                },
                "extraction_template": source.get("extraction_template"),
                "ocr_confidence": source.get("ocr_confidence", 0.0),
            },
            "extraction": {
                "pages": page_range,
                "page_offset_applied": page_offset,
                "hit_page_numbers": pages_with_hits,
                "boundary_method": "index_search",
                "confidence": source.get("ocr_confidence", 0.0),
            },
            "citation": citation,
            "flags": flags,
        }
