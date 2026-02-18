"""SQLite schema DDL with FTS5 full-text search."""

from __future__ import annotations

__all__ = ["get_sqlite_schema"]


def get_sqlite_schema() -> list[str]:
    """Return a list of SQL statements to initialize the SQLite schema.

    Uses FTS5 with porter tokenizer for full-text search.
    Embedding support is optional via sqlite-vec (detected at runtime).
    """
    return [
        # Main documentation chunks table
        """\
CREATE TABLE IF NOT EXISTS documentation_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL,
    chunk_index INTEGER NOT NULL DEFAULT 0,
    title TEXT,
    content TEXT NOT NULL,
    category TEXT,
    audience TEXT DEFAULT 'all',
    tags TEXT,
    embedding BLOB,
    content_hash TEXT,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (file_path, chunk_index)
)""",
        # Indexes
        "CREATE INDEX IF NOT EXISTS idx_chunks_file_path ON documentation_chunks (file_path)",
        "CREATE INDEX IF NOT EXISTS idx_chunks_category ON documentation_chunks (category)",
        # FTS5 virtual table (porter tokenizer for stemming)
        """\
CREATE VIRTUAL TABLE IF NOT EXISTS documentation_chunks_fts USING fts5(
    title,
    content,
    content='documentation_chunks',
    content_rowid='id',
    tokenize='porter'
)""",
        # Triggers to keep FTS in sync with main table
        """\
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON documentation_chunks BEGIN
    INSERT INTO documentation_chunks_fts(rowid, title, content)
    VALUES (new.id, new.title, new.content);
END""",
        """\
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON documentation_chunks BEGIN
    INSERT INTO documentation_chunks_fts(documentation_chunks_fts, rowid, title, content)
    VALUES ('delete', old.id, old.title, old.content);
END""",
        """\
CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON documentation_chunks BEGIN
    INSERT INTO documentation_chunks_fts(documentation_chunks_fts, rowid, title, content)
    VALUES ('delete', old.id, old.title, old.content);
    INSERT INTO documentation_chunks_fts(rowid, title, content)
    VALUES (new.id, new.title, new.content);
END""",
        # Documentation links table
        """\
CREATE TABLE IF NOT EXISTS documentation_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_path TEXT NOT NULL,
    target_path TEXT NOT NULL,
    relation_type TEXT NOT NULL DEFAULT 'related',
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (source_path, target_path, relation_type)
)""",
        "CREATE INDEX IF NOT EXISTS idx_links_source ON documentation_links (source_path)",
        "CREATE INDEX IF NOT EXISTS idx_links_target ON documentation_links (target_path)",
    ]
