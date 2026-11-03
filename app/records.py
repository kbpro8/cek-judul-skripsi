"""Shared helpers for writing thesis records."""
import sqlite3

from .text import clean, stem_text, stem_vocabulary, vocabulary

FIELDS = ("title", "abstract", "author", "nim", "year", "program_code",
          "program_name", "faculty", "level", "url")

# Long abstracts often carry English and Arabic versions after the Indonesian one; the
# first part is enough for topic matching and keeps the vocabulary manageable.
MAX_DOC_WORDS = 400


def doc_for_stemming(title: str, abstract: str | None) -> str:
    return " ".join(f"{title} {abstract or ''}".split()[:MAX_DOC_WORDS])


def upsert(conn: sqlite3.Connection, source: str, ext_id: str, rec: dict, batch_id: int | None = None):
    """Insert or update a record. Stems are filled in later by fill_stems()."""
    rec = {k: (clean(rec.get(k)) or None) for k in FIELDS}
    if not rec["title"]:
        return False
    cols = ", ".join(rec)
    marks = ", ".join(f":{k}" for k in rec)
    updates = ", ".join(f"{k}=excluded.{k}" for k in rec)
    conn.execute(
        f"""INSERT INTO theses (source, ext_id, batch_id, {cols}) VALUES (:source, :ext_id, :batch_id, {marks})
            ON CONFLICT (source, ext_id) DO UPDATE SET batch_id=excluded.batch_id, {updates},
            stem_title=NULL, stem_doc=NULL, updated_at=CURRENT_TIMESTAMP""",
        {**rec, "source": source, "ext_id": str(ext_id), "batch_id": batch_id},
    )
    return True


def fill_stems(conn: sqlite3.Connection, status: dict | None = None):
    """Stem every record that has no stems yet (new or changed since the last index build)."""
    rows = conn.execute("SELECT id, title, abstract FROM theses WHERE stem_doc IS NULL").fetchall()
    if not rows:
        return
    words = set()
    for r in rows:
        words |= vocabulary(doc_for_stemming(r["title"], r["abstract"]))
    stem_vocabulary(conn, words, status=status)
    conn.executemany(
        "UPDATE theses SET stem_title=?, stem_doc=? WHERE id=?",
        [(stem_text(r["title"]), stem_text(doc_for_stemming(r["title"], r["abstract"])), r["id"]) for r in rows],
    )
    conn.commit()
