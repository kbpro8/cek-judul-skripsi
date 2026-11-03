"""Manual upload of internal faculty thesis lists (CSV or Excel)."""
import csv
import hashlib
import io

from openpyxl import Workbook, load_workbook

from .db import session
from .records import upsert
from .text import normalise

# Accepted column names (case-insensitive) for each field.
COLUMNS = {
    "title": ["judul", "judul skripsi", "title", "judul penelitian"],
    "abstract": ["abstrak", "abstract", "ringkasan", "abstrak/ringkasan"],
    "author": ["penulis", "nama", "nama mahasiswa", "author"],
    "nim": ["nim", "npm"],
    "year": ["tahun", "year", "tahun lulus"],
    "program_name": ["prodi", "program studi", "jurusan", "program"],
    "faculty": ["fakultas", "faculty"],
    "level": ["jenjang", "level", "strata"],
    "url": ["url", "link", "tautan"],
}
TEMPLATE_HEADERS = ["judul", "abstrak", "penulis", "nim", "tahun", "prodi", "fakultas", "jenjang", "url"]


class ImportError_(Exception):
    pass


def _read_rows(filename: str, data: bytes) -> list[dict]:
    name = filename.lower()
    if name.endswith((".xlsx", ".xlsm")):
        ws = load_workbook(io.BytesIO(data), read_only=True, data_only=True).active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []
        headers = [str(h or "").strip() for h in rows[0]]
        return [dict(zip(headers, r)) for r in rows[1:]]
    if name.endswith((".csv", ".txt")):
        text = data.decode("utf-8-sig", errors="replace")
        # Excel with Indonesian locale saves CSV with ";", so pick the delimiter from the header.
        header = text.split("\n", 1)[0]
        delimiter = max(",;\t", key=header.count)
        return list(csv.DictReader(io.StringIO(text), delimiter=delimiter))
    raise ImportError_("Format file tidak didukung. Gunakan .xlsx atau .csv.")


def _map_headers(headers) -> dict:
    found = {}
    lower = {str(h).strip().lower(): h for h in headers if h}
    for field, aliases in COLUMNS.items():
        for alias in aliases:
            if alias in lower:
                found[field] = lower[alias]
                break
    if "title" not in found:
        raise ImportError_("Kolom 'judul' tidak ditemukan. Unduh templat untuk melihat format yang benar.")
    return found


def import_file(filename: str, data: bytes, batch_name: str, default_faculty: str = "",
                default_program: str = "") -> dict:
    rows = _read_rows(filename, data)
    if not rows:
        raise ImportError_("File kosong.")
    mapping = _map_headers(rows[0].keys())
    saved = skipped = 0
    with session() as conn:
        batch_id = conn.execute(
            "INSERT INTO batches (name, filename, faculty) VALUES (?, ?, ?)",
            (batch_name or filename, filename, default_faculty or None),
        ).lastrowid
        for row in rows:
            rec = {f: (str(row.get(col)).strip() if row.get(col) is not None else "") for f, col in mapping.items()}
            rec["faculty"] = rec.get("faculty") or default_faculty
            rec["program_name"] = rec.get("program_name") or default_program
            for f in ("year", "nim"):  # Excel stores numbers as floats
                if rec.get(f, "").endswith(".0"):
                    rec[f] = rec[f][:-2]
            if not rec.get("title"):
                skipped += 1
                continue
            # The same NIM, or the same normalised title, in a later upload updates the record.
            key = rec.get("nim") or hashlib.md5(normalise(rec["title"]).encode()).hexdigest()
            if upsert(conn, "internal", key, rec, batch_id):
                saved += 1
            else:
                skipped += 1
        conn.execute("UPDATE batches SET row_count=? WHERE id=?", (saved, batch_id))
    return {"batch_id": batch_id, "saved": saved, "skipped": skipped, "columns": mapping}


def delete_batch(batch_id: int):
    with session() as conn:
        conn.execute("DELETE FROM theses WHERE batch_id=? AND source='internal'", (batch_id,))
        conn.execute("DELETE FROM batches WHERE id=?", (batch_id,))


def template_xlsx() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Daftar Skripsi"
    ws.append(TEMPLATE_HEADERS)
    ws.append(["Partisipasi Politik Perempuan dalam Pilkada Aceh Barat Daya 2024",
               "Penelitian ini membahas ...", "Nama Mahasiswa", "190801001", 2024,
               "S1 Ilmu Politik", "Fakultas Ilmu Sosial dan Ilmu Pemerintahan", "S1", ""])
    for col, width in zip("ABCDEFGHI", (60, 60, 25, 14, 8, 28, 40, 8, 30)):
        ws.column_dimensions[col].width = width
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
