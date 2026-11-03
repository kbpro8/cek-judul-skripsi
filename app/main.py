import os
import secrets
import threading
from datetime import datetime, timezone
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from . import config, engine, harvest, importer
from .config import BASE_DIR
from .db import init_db, session

app = FastAPI(title="Cek Kemiripan Judul Skripsi")
app.mount("/static", StaticFiles(directory=BASE_DIR / "app" / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "app" / "templates")
basic = HTTPBasic()


def localtime(value: str | None) -> str:
    """SQLite stores UTC timestamps; show them in the server's local time."""
    if not value:
        return ""
    try:
        utc = datetime.strptime(value[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return value
    return utc.astimezone().strftime("%Y-%m-%d %H:%M")


templates.env.filters["localtime"] = localtime
templates.env.filters["num"] = lambda n: f"{int(n or 0):,}".replace(",", ".")  # 29.190


def back(msg: str = "", err: str = "") -> RedirectResponse:
    params = {k: v for k, v in (("msg", msg), ("err", err)) if v}
    return RedirectResponse("/admin" + ("?" + urlencode(params) if params else ""), 303)


def require_admin(creds: HTTPBasicCredentials = Depends(basic)):
    ok = secrets.compare_digest(creds.username, config.ADMIN_USER) and \
        secrets.compare_digest(creds.password, config.ADMIN_PASSWORD)
    if not ok:
        raise HTTPException(401, "Login admin diperlukan", headers={"WWW-Authenticate": "Basic"})


@app.on_event("startup")
async def limit_worker_threads():
    # Sync routes run in a thread pool (40 threads by default); shared hosting caps threads.
    import anyio.to_thread
    anyio.to_thread.current_default_thread_limiter().total_tokens = int(os.environ.get("WORKER_THREADS", 8))


@app.on_event("startup")
def startup():
    init_db()
    with session() as conn:  # runs cut off by a restart would otherwise show "running" forever
        conn.execute("""UPDATE harvest_runs SET status='terputus' WHERE status='running'
                        AND started_at < datetime('now', '-3 hours')""")
    engine.rebuild()


def filter_options():
    with session() as conn:
        faculties = [r[0] for r in conn.execute(
            "SELECT DISTINCT faculty FROM theses WHERE faculty IS NOT NULL ORDER BY faculty")]
        levels = [r[0] for r in conn.execute(
            "SELECT DISTINCT level FROM theses WHERE level IS NOT NULL ORDER BY level")]
    return faculties, levels


def run_check(title: str, abstract: str, faculty: str, source: str, level: str) -> dict:
    index = engine.state["index"]
    if index is None:
        raise HTTPException(503, "Indeks sedang disiapkan. Coba lagi dalam beberapa menit.")
    out = index.search(title, abstract, faculty=faculty, source=source, level=level)
    out["status"] = engine.status_of(out["top_score"])
    with session() as conn:
        conn.execute(
            "INSERT INTO checks (title, abstract, top_score, status, top_match_id) VALUES (?, ?, ?, ?, ?)",
            (title, abstract, out["top_score"], out["status"],
             out["results"][0]["id"] if out["results"] else None),
        )
    return out


# --- student pages -----------------------------------------------------------------------

def faculty_stats() -> dict:
    """Counts per faculty (largest first); the order also fixes each faculty's colour."""
    with session() as conn:
        rows = conn.execute(
            """SELECT COALESCE(faculty, 'Lainnya') AS faculty, COUNT(*) AS n FROM theses
               GROUP BY 1 ORDER BY n DESC""").fetchall()
        programs = conn.execute(
            "SELECT COUNT(DISTINCT COALESCE(program_code, program_name)) FROM theses").fetchone()[0]
    return {
        "by_faculty": [dict(r) for r in rows],
        "fac_color": {r["faculty"]: i % 10 for i, r in enumerate(rows)},
        "programs": programs,
    }


def page_context(**extra) -> dict:
    faculties, levels = filter_options()
    index = engine.state["index"]
    return {"faculties": faculties, "levels": levels, "form": {}, "state": engine.state,
            "total": index.size if index else 0, "config": config, **faculty_stats(), **extra}


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(request, "index.html", page_context())


@app.post("/cek", response_class=HTMLResponse)
def check(request: Request, title: str = Form(...), abstract: str = Form(""), keywords: str = Form(""),
          faculty: str = Form(""), source: str = Form(""), level: str = Form("")):
    title = title.strip()
    form = {"title": title, "abstract": abstract, "keywords": keywords,
            "faculty": faculty, "source": source, "level": level}
    if len(title.split()) < 3:
        return templates.TemplateResponse(request, "index.html", page_context(
            form=form, error="Judul terlalu pendek. Tulis judul lengkap, minimal 3 kata."), status_code=400)
    summary = f"{abstract} {keywords}".strip()
    out = run_check(title, summary, faculty, source, level)
    return templates.TemplateResponse(request, "result.html", {
        **page_context(), **out,
        "form": {"title": title, "abstract": abstract, "keywords": keywords,
                 "faculty": faculty, "source": source, "level": level},
        "semantic": engine.state["index"].semantic, "total": engine.state["index"].size,
    })


class CheckIn(BaseModel):
    title: str
    abstract: str = ""
    faculty: str = ""
    source: str = ""
    level: str = ""


@app.post("/api/cek")
def api_check(body: CheckIn):
    out = run_check(body.title, body.abstract, body.faculty, body.source, body.level)
    for r in out["results"]:
        r.pop("title_parts", None)
        r.pop("stem_title", None)
    return out


# --- admin -------------------------------------------------------------------------------

@app.get("/admin", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
def admin(request: Request, msg: str = "", err: str = ""):
    with session() as conn:
        fac_rows = conn.execute(
            """SELECT COALESCE(faculty, 'Lainnya') AS faculty,
                      SUM(source='repository') AS repo, SUM(source='internal') AS internal, COUNT(*) AS n
               FROM theses GROUP BY 1 ORDER BY n DESC""").fetchall()
        check_stats = conn.execute(
            """SELECT COUNT(*) AS n, SUM(status='tinggi') AS tinggi, SUM(status='tinjau') AS tinjau,
                      SUM(date(created_at) = date('now')) AS today FROM checks""").fetchone()
        totals = conn.execute(
            "SELECT SUM(source='repository') AS repo, SUM(source='internal') AS internal FROM theses").fetchone()
        runs = conn.execute("SELECT * FROM harvest_runs ORDER BY id DESC LIMIT 5").fetchall()
        # Counted live: re-uploading the same NIM/title moves the row to the newer batch.
        batches = conn.execute(
            """SELECT b.*, (SELECT COUNT(*) FROM theses t WHERE t.batch_id = b.id) AS row_count
               FROM batches b ORDER BY b.id DESC""").fetchall()
        checks = conn.execute("SELECT * FROM checks ORDER BY id DESC LIMIT 20").fetchall()
    return templates.TemplateResponse(request, "admin.html", page_context(
        fac_rows=fac_rows, check_stats=check_stats, totals=totals, runs=runs, batches=batches,
        checks=checks, progress=harvest.progress, msg=msg, err=err,
        default_password=config.ADMIN_PASSWORD == "ganti-saya",
    ))


@app.get("/admin/status", dependencies=[Depends(require_admin)])
def admin_status():
    index = engine.state["index"]
    return {"harvest": harvest.progress, "index_building": engine.state["building"],
            "index_message": engine.state["message"], "index_size": index.size if index else 0}


@app.post("/admin/harvest", dependencies=[Depends(require_admin)])
def start_harvest():
    if harvest.progress["running"]:
        return back(err="Harvest sedang berjalan.")

    def run():
        try:
            harvest.harvest()
        finally:
            engine.rebuild()

    threading.Thread(target=run, daemon=True).start()
    return back(msg="Harvest dimulai. Proses ini memakan waktu sekitar 5–30 menit.")


@app.post("/admin/reindex", dependencies=[Depends(require_admin)])
def reindex():
    engine.rebuild()
    return back(msg="Indeks sedang dibangun ulang.")


@app.post("/admin/upload", dependencies=[Depends(require_admin)])
async def upload(file: UploadFile = File(...), batch_name: str = Form(""),
                 faculty: str = Form(""), program: str = Form("")):
    data = await file.read()
    try:
        res = importer.import_file(file.filename or "upload", data, batch_name.strip(),
                                   faculty.strip(), program.strip())
    except importer.ImportError_ as exc:
        return back(err=str(exc))
    except Exception as exc:
        return back(err=f"Gagal membaca file: {exc}")
    engine.rebuild()
    msg = f"{res['saved']} judul diimpor ({res['skipped']} baris dilewati). Indeks sedang diperbarui."
    return back(msg=msg)


@app.post("/admin/batches/{batch_id}/delete", dependencies=[Depends(require_admin)])
def delete_batch(batch_id: int):
    importer.delete_batch(batch_id)
    engine.rebuild()
    return back(msg="Batch dihapus. Indeks sedang diperbarui.")


@app.get("/admin/template.xlsx", dependencies=[Depends(require_admin)])
def template():
    return Response(importer.template_xlsx(),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="templat-daftar-skripsi.xlsx"'})
