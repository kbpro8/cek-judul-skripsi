import sqlite3
from contextlib import contextmanager

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS theses (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,              -- 'repository' or 'internal'
    ext_id TEXT NOT NULL,              -- eprintid, or NIM / title hash for uploads
    batch_id INTEGER,                  -- upload batch, NULL for repository records
    title TEXT NOT NULL,
    abstract TEXT,
    author TEXT,
    nim TEXT,
    year TEXT,
    program_code TEXT,
    program_name TEXT,
    faculty TEXT,
    level TEXT,
    url TEXT,
    stem_title TEXT,
    stem_doc TEXT,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (source, ext_id)
);
CREATE INDEX IF NOT EXISTS idx_theses_faculty ON theses (faculty);
CREATE INDEX IF NOT EXISTS idx_theses_batch ON theses (batch_id);

CREATE TABLE IF NOT EXISTS embeddings (
    thesis_id INTEGER PRIMARY KEY REFERENCES theses (id) ON DELETE CASCADE,
    text_hash TEXT NOT NULL,
    title_vec BLOB NOT NULL,
    doc_vec BLOB NOT NULL
);

CREATE TABLE IF NOT EXISTS stem_cache (
    word TEXT PRIMARY KEY,
    stem TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS batches (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    filename TEXT,
    faculty TEXT,
    row_count INTEGER DEFAULT 0,
    uploaded_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS harvest_runs (
    id INTEGER PRIMARY KEY,
    started_at TEXT DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,
    status TEXT,                       -- running / done / failed
    message TEXT,
    records INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS checks (
    id INTEGER PRIMARY KEY,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    title TEXT,
    abstract TEXT,
    top_score REAL,
    status TEXT,
    top_match_id INTEGER
);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def session():
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with session() as conn:
        conn.executescript(SCHEMA)
