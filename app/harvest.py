"""Harvest thesis metadata from the UIN Ar-Raniry EPrints repository.

The repository offers a JSON export for every study program (division), e.g.
  /cgi/exportview/divisions/fisip=5Fpol/JSON/fisip=5Fpol.js
We read the division list from /view/divisions/, download each program's export and
keep the records of type "thesis" (skripsi, tesis, disertasi).

Run from the command line:
  python -m app.harvest                     # all study programs, then build the index
  python -m app.harvest fisip_pol tar_pai   # only these programs
  python -m app.harvest --no-index          # skip the index build
"""
import re
import sys
import time

import httpx

from .config import REPO_BASE
from .db import init_db, session
from .records import upsert

LEVEL_BY_TYPE = {"skripsi": "S1", "masters": "S2", "doctoral": "S3", "diploma": "D3"}
_DIV_LINK = re.compile(r'href="([a-z]+=5F[a-z0-9]+|fac=5F[a-z]+|pro=5F[a-z]+)/">([^<]+)<')

progress = {"running": False, "current": "", "done": 0, "total": 0, "records": 0, "errors": []}


def list_programs(client: httpx.Client) -> list[dict]:
    """Study programs in page order, each tagged with the faculty heading above it."""
    page = client.get(f"{REPO_BASE}/view/divisions/").text
    faculty, programs = None, []
    for code, name in _DIV_LINK.findall(page):
        code = code.replace("=5F", "_")
        name = name.strip()
        if code.startswith(("fac_", "pro_")):
            faculty = name
            continue
        programs.append({"code": code, "name": name, "faculty": faculty or ""})
    return programs


def level_of(rec: dict, program_name: str) -> str:
    level = LEVEL_BY_TYPE.get(rec.get("thesis_type") or "")
    if level:
        return level
    m = re.match(r"(D3|S1|S2|S3)\b", program_name)
    return m.group(1) if m else ""


def author_of(rec: dict) -> tuple[str, str]:
    """EPrints stores the student name in creators.name.family and often the NIM in .given."""
    creators = rec.get("creators") or []
    if not creators:
        return "", ""
    name = creators[0].get("name") or {}
    family, given = name.get("family") or "", name.get("given") or ""
    if str(given).isdigit():
        return str(family), str(given)
    return f"{given} {family}".strip(), ""


def fetch_program(client: httpx.Client, code: str) -> list[dict]:
    slug = code.replace("_", "=5F")
    url = f"{REPO_BASE}/cgi/exportview/divisions/{slug}/JSON/{slug}.js"
    for attempt in range(3):
        try:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPError, ValueError):
            if attempt == 2:
                raise
            time.sleep(5 * (attempt + 1))
    return []


def harvest(only: list[str] | None = None) -> int:
    init_db()
    progress.update(running=True, current="daftar prodi", done=0, total=0, records=0, errors=[])
    with session() as conn:
        run_id = conn.execute("INSERT INTO harvest_runs (status) VALUES ('running')").lastrowid
    total_saved, status, message = 0, "failed", None
    try:
        with httpx.Client(timeout=300, follow_redirects=True,
                          headers={"User-Agent": "FISIP-UIN-Lab-CekJudul/1.0"}) as client:
            programs = list_programs(client)
            if only:
                programs = [p for p in programs if p["code"] in only]
            progress["total"] = len(programs)
            for prog in programs:
                progress["current"] = prog["name"]
                try:
                    items = fetch_program(client, prog["code"])
                except Exception as exc:  # keep going; one bad program should not stop the run
                    progress["errors"].append(f"{prog['name']}: {exc}")
                    progress["done"] += 1
                    continue
                saved = 0
                with session() as conn:
                    for rec in items:
                        if rec.get("type") != "thesis" or rec.get("eprint_status") not in (None, "archive"):
                            continue
                        try:
                            ok = save_record(conn, rec, prog)
                        except Exception as exc:
                            progress["errors"].append(f"eprint {rec.get('eprintid')}: {exc}")
                            continue
                        saved += ok
                total_saved += saved
                progress["done"] += 1
                progress["records"] = total_saved
                print(f"[{progress['done']}/{progress['total']}] {prog['name']}: {saved} skripsi/tesis", flush=True)
                time.sleep(1)  # be gentle with the university server
        status, message = "done", "; ".join(progress["errors"][:20]) or None
    except Exception as exc:
        message = str(exc)
        raise
    finally:
        with session() as conn:
            conn.execute(
                "UPDATE harvest_runs SET finished_at=CURRENT_TIMESTAMP, status=?, message=?, records=? WHERE id=?",
                (status, message, total_saved, run_id),
            )
        progress.update(running=False, current="")
    return total_saved


def save_record(conn, rec: dict, prog: dict) -> bool:
    author, nim = author_of(rec)
    return upsert(conn, "repository", rec["eprintid"], {
        "title": rec.get("title"),
        "abstract": rec.get("abstract"),
        "author": author,
        "nim": nim,
        "year": str(rec.get("date") or "")[:4],
        "program_code": prog["code"],
        "program_name": prog["name"],
        "faculty": prog["faculty"],
        "level": level_of(rec, prog["name"]),
        "url": rec.get("uri") or f"{REPO_BASE}/id/eprint/{rec['eprintid']}",
    })


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    n = harvest(args or None)
    print(f"Selesai: {n} record disimpan.")
    if "--no-index" not in sys.argv:
        from .engine import rebuild, state
        print("Membangun indeks (stemming + embedding)...", flush=True)
        rebuild(blocking=True)
        print(f"Indeks siap: {state['index'].size} record, semantik={state['index'].semantic}")
