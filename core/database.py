"""Database initialization and connection management for Plant Précis Producer."""

import sqlite3
import json
import os
from pathlib import Path

DB_NAME = "plant_precis.db"


def get_db_path(data_dir: str = ".") -> Path:
    return Path(data_dir) / DB_NAME


def get_connection(data_dir: str = ".") -> sqlite3.Connection:
    db_path = get_db_path(data_dir)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(data_dir: str = ".") -> None:
    conn = get_connection(data_dir)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()

        # Seed synonym data if table is empty
        count = conn.execute("SELECT COUNT(*) as cnt FROM synonyms").fetchone()["cnt"]
        if count == 0:
            seed_path = Path(data_dir) / "seed_data.sql"
            if seed_path.exists():
                conn.executescript(seed_path.read_text(encoding="utf-8"))
                conn.commit()
    finally:
        conn.close()


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    author TEXT NOT NULL,
    year INTEGER,
    edition TEXT,
    publisher TEXT,
    file TEXT NOT NULL,
    file_type TEXT NOT NULL DEFAULT 'pdf',

    -- Lens tags stored as JSON arrays
    lens_temporal TEXT NOT NULL DEFAULT '[]',
    lens_epistemic TEXT NOT NULL DEFAULT '[]',
    lens_tradition TEXT NOT NULL DEFAULT '[]',
    lens_evidential_weight TEXT NOT NULL DEFAULT '[]',

    extraction_template TEXT NOT NULL DEFAULT 'low_structure_fallback',
    offset_mode TEXT DEFAULT 'fixed',
    page_offset INTEGER DEFAULT 0,
    typical_monograph_pages TEXT,
    ocr_confidence REAL DEFAULT 0.0,
    language TEXT DEFAULT 'en',
    index_file TEXT,
    index_type TEXT,
    notes TEXT,
    citation_template TEXT DEFAULT '{author}. ({year}). {title}. pp. {pages}.',
    degraded BOOLEAN DEFAULT 0,
    degraded_reason TEXT,

    -- Lifecycle
    index_status TEXT DEFAULT 'pending',  -- pending, building, ready, failed
    verified BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_indexed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS synonyms (
    id INTEGER PRIMARY KEY,
    canonical_binomial TEXT NOT NULL,
    name_string TEXT NOT NULL,
    name_type TEXT NOT NULL,  -- 'binomial', 'common', 'drug_name', 'deprecated_binomial', 'transliteration'
    language TEXT DEFAULT 'en',
    source TEXT,              -- 'POWO', 'corpus_scan', 'user_added'
    UNIQUE(canonical_binomial, name_string)
);

CREATE INDEX IF NOT EXISTS idx_synonyms_canonical ON synonyms(canonical_binomial);
CREATE INDEX IF NOT EXISTS idx_synonyms_name ON synonyms(name_string);
CREATE INDEX IF NOT EXISTS idx_synonyms_type ON synonyms(name_type);

CREATE TABLE IF NOT EXISTS query_history (
    id INTEGER PRIMARY KEY,
    input_string TEXT NOT NULL,
    resolved_binomial TEXT,
    synonyms_matched TEXT,   -- JSON array
    lens_filters TEXT,       -- JSON object
    sources_queried INTEGER,
    sources_hit INTEGER,
    output_formats TEXT,     -- JSON array
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""
