"""Synonym resolution: input string → canonical binomial → all attested synonyms."""

import logging
import sqlite3
from typing import Optional
from urllib.parse import quote

import requests
from rapidfuzz import fuzz, process
from core.database import get_connection

log = logging.getLogger(__name__)

POWO_API_BASE = "https://powo.science.kew.org/api/2"


class SynonymResolver:
    def __init__(self, data_dir: str = "."):
        self.data_dir = data_dir

    def resolve(self, input_string: str) -> Optional[dict]:
        """Resolve an input string to a canonical binomial and all synonyms.

        Returns dict with keys: canonical_binomial, synonyms, match_type
        or None if no match found.
        """
        normalized = input_string.strip().lower()
        conn = get_connection(self.data_dir)
        try:
            # Exact match
            row = conn.execute(
                "SELECT canonical_binomial FROM synonyms WHERE LOWER(name_string) = ?",
                (normalized,),
            ).fetchone()
            if row:
                return self._build_result(conn, row["canonical_binomial"], "exact")

            # Fuzzy match
            all_names = conn.execute("SELECT DISTINCT name_string FROM synonyms").fetchall()
            if not all_names:
                return None

            candidates = [r["name_string"] for r in all_names]
            matches = process.extract(normalized, candidates, scorer=fuzz.WRatio, limit=5)
            if matches and matches[0][1] >= 80:
                best = matches[0][0]
                row = conn.execute(
                    "SELECT canonical_binomial FROM synonyms WHERE name_string = ?",
                    (best,),
                ).fetchone()
                if row:
                    return self._build_result(
                        conn,
                        row["canonical_binomial"],
                        "fuzzy",
                        score=matches[0][1],
                        candidates=[(m[0], m[1]) for m in matches[:3]],
                    )
            return None
        finally:
            conn.close()

    def _build_result(
        self,
        conn: sqlite3.Connection,
        canonical: str,
        match_type: str,
        score: float = 100.0,
        candidates: list = None,
    ) -> dict:
        rows = conn.execute(
            "SELECT name_string, name_type FROM synonyms WHERE canonical_binomial = ?",
            (canonical,),
        ).fetchall()
        return {
            "canonical_binomial": canonical,
            "synonyms": [{"name": r["name_string"], "type": r["name_type"]} for r in rows],
            "match_type": match_type,
            "score": score,
            "candidates": candidates,
        }

    def add_synonym(
        self,
        canonical_binomial: str,
        name_string: str,
        name_type: str,
        language: str = "en",
        source: str = "user_added",
    ) -> None:
        conn = get_connection(self.data_dir)
        try:
            conn.execute(
                "INSERT OR IGNORE INTO synonyms (canonical_binomial, name_string, name_type, language, source) VALUES (?, ?, ?, ?, ?)",
                (canonical_binomial, name_string, name_type, language, source),
            )
            conn.commit()
        finally:
            conn.close()

    def get_all_names(self, canonical_binomial: str) -> list[str]:
        conn = get_connection(self.data_dir)
        try:
            rows = conn.execute(
                "SELECT name_string FROM synonyms WHERE canonical_binomial = ?",
                (canonical_binomial,),
            ).fetchall()
            return [r["name_string"] for r in rows]
        finally:
            conn.close()

    def has_synonyms(self, canonical_binomial: str) -> bool:
        conn = get_connection(self.data_dir)
        try:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM synonyms WHERE canonical_binomial = ?",
                (canonical_binomial,),
            ).fetchone()
            return row["cnt"] > 0
        finally:
            conn.close()


def seed_synonyms_from_powo(canonical_binomial: str, data_dir: str = ".") -> int:
    """Query POWO API for a canonical binomial and populate the synonyms table.

    Returns the number of synonyms added.
    """
    resolver = SynonymResolver(data_dir)
    added = 0

    # Always add the canonical binomial itself
    resolver.add_synonym(canonical_binomial, canonical_binomial, "binomial", source="POWO")
    added += 1

    # Search POWO for the taxon
    try:
        search_url = f"{POWO_API_BASE}/search?q={quote(canonical_binomial)}"
        resp = requests.get(search_url, timeout=15, headers={"Accept": "application/json"})
        resp.raise_for_status()
        search_data = resp.json()

        results = search_data.get("results", [])
        if not results:
            log.warning("POWO: no results for %s", canonical_binomial)
            return added

        # Find the accepted name entry
        taxon = None
        for r in results:
            if r.get("accepted") and r.get("name", "").startswith(canonical_binomial.split(" ")[0]):
                taxon = r
                break
        if not taxon:
            taxon = results[0]

        fqid = taxon.get("fqId")
        if not fqid:
            return added

        # Fetch full taxon record for synonyms
        taxon_url = f"{POWO_API_BASE}/taxon/{quote(fqid)}?fields=synonyms"
        resp = requests.get(taxon_url, timeout=15, headers={"Accept": "application/json"})
        resp.raise_for_status()
        taxon_data = resp.json()

        # Add synonyms from POWO
        for syn in taxon_data.get("synonyms", []):
            name = syn.get("name", "").strip()
            if not name:
                continue
            name_type = "deprecated_binomial" if syn.get("accepted") is False else "binomial"
            resolver.add_synonym(canonical_binomial, name, name_type, source="POWO")
            added += 1

        log.info("POWO: seeded %d synonyms for %s", added, canonical_binomial)

    except requests.RequestException as e:
        log.warning("POWO API request failed for %s: %s", canonical_binomial, e)
    except (KeyError, ValueError) as e:
        log.warning("POWO API response parsing failed for %s: %s", canonical_binomial, e)

    return added
