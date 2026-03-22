"""Synonym resolution: input string → canonical binomial → all attested synonyms."""

import sqlite3
from typing import Optional
from rapidfuzz import fuzz, process
from core.database import get_connection


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
