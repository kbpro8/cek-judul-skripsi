# Cek Kemiripan Judul Skripsi — Lab FISIP UIN Ar-Raniry

Students enter a proposal title (and optionally a summary and keywords). The app compares it with
every skripsi, tesis and disertasi in the [UIN Ar-Raniry repository](https://repository.ar-raniry.ac.id)
from all faculties, plus thesis lists the faculty uploads itself, and shows the 10 most similar works
with a similarity score.

## How it works

| Part | File | What it does |
|---|---|---|
| Harvester | `app/harvest.py` | Reads the study-program list from `/view/divisions/`, downloads each program's EPrints JSON export, keeps records of type `thesis`. |
| Manual upload | `app/importer.py` | Imports `.xlsx` / `.csv` thesis lists from the faculty (column `judul` is required). Re-uploading the same NIM or title updates instead of duplicating. |
| Text processing | `app/text.py` | Indonesian cleaning, stopwords (Sastrawi + academic filler words such as "analisis", "studi kasus"), Sastrawi stemming with a persistent cache. |
| Embeddings | `app/embedder.py` | Multilingual MiniLM sentence embeddings via ONNX Runtime (8-bit model, mean pooling). |
| Similarity | `app/engine.py` | Lexical (TF-IDF on stemmed words + character n-grams) and semantic (multilingual sentence embeddings) similarity, on title and on title + abstract. |
| Web app | `app/main.py` | Student check page, JSON API, admin page. |

**Score** = 40% lexical + 60% semantic on the title; when the student gives a summary, the content
match is blended in, but a near-identical title always counts on its own.

| Score | Status |
|---|---|
| < 40% | Aman (topic looks new) |
| 40–70% | Perlu ditinjau (similar theme; student must explain the difference) |
| ≥ 70% | Sangat mirip (likely duplicate; revise) |

## Running it

```bash
uv venv -p 3.12 .venv && uv pip install -p .venv/bin/python -r requirements.txt
.venv/bin/python -m app.harvest          # first harvest + index build (first time ~30–40 min)
ADMIN_PASSWORD='choose-a-password' ./run.sh
```

Open http://localhost:8000 (student page) and http://localhost:8000/admin (user `admin`).

The first index build downloads the embedding model (8-bit ONNX, ~118 MB) and stems the whole
vocabulary; both are cached, so later rebuilds only process new records. The semantic model runs on
ONNX Runtime, so PyTorch is not needed (the whole Python environment is ~250 MB).

### Settings (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `ADMIN_USER` / `ADMIN_PASSWORD` | `admin` / `ganti-saya` | Admin login. **Change the password.** |
| `SEMANTIC` | `1` | `0` = lexical only (no model, much lighter server) |
| `EMBED_ONNX_FILE` | per CPU | ONNX file from the model repo; default `onnx/model_qint8_arm64.onnx` on ARM, `onnx/model_quint8_avx2.onnx` on x86. Changing it re-embeds everything automatically. |
| `THRESHOLD_REVIEW` / `THRESHOLD_HIGH` | `40` / `70` | Status cut-offs |
| `DATA_DIR` | `./data` | Where the SQLite database lives |

### Keeping the data fresh

Run the harvest weekly, for example with cron:

```
0 2 * * 0  cd /path/to/cek-judul-skripsi && .venv/bin/python -m app.harvest >> data/harvest.log 2>&1
```

Or press **Harvest ulang repository** on the admin page. After a harvest from the command line,
restart the web app (or press **Bangun ulang indeks**) so it picks up the new records.

### API

```bash
curl -X POST http://localhost:8000/api/cek -H 'Content-Type: application/json' \
  -d '{"title": "Partisipasi politik perempuan dalam Pilkada Aceh Barat Daya 2024", "abstract": ""}'
```

Optional fields: `abstract`, `faculty`, `source` (`repository` / `internal`), `level` (`S1`, `S2`, ...).

## Notes

- The repository is a public university service; the harvester downloads one program at a time
  with a pause between requests. Let UPT Perpustakaan know the lab runs a weekly harvest.
- Records that the repository files under no study program are not harvested.
- The score supports the supervisor's decision; it does not replace it.

## Resource use (29,190 records, measured on an Apple-silicon Mac)

| | Size / time |
|---|---|
| Python environment | ~250 MB |
| Embedding model (cached in `~/.cache/huggingface`) | ~118 MB |
| Database | ~175 MB (embeddings stored as float16) |
| Server memory | ~530 MB |
| Startup (index build) | ~20 s |
| One check | ~30 ms |

## Deployment: https://lab.trida.id (hosting.com shared server)

The app lives in `~/lab.trida.id/app` on the server (SSH host alias `trida`).

| Piece | Where |
|---|---|
| Python environment | `~/lab.trida.id/app/.venv` (Python 3.11) |
| Settings (admin login, thread limits) | `~/lab.trida.id/app/.env.production` (chmod 600) |
| Web process | `deploy/start.sh` → uvicorn on `127.0.0.1:5061` |
| Domain → app | `~/lab.trida.id/.htaccess` (copy of `deploy/htaccess-docroot`): HTTPS redirect + proxy |
| Restart if down | `deploy/keepalive.sh` (meant for cron every 5 minutes) |
| Weekly harvest | `deploy/harvest.sh` (harvest + index, then restarts the web process) |
| Logs | `data/app.log`, `data/keepalive.log`, `data/harvest.log` |

Why not cPanel "Setup Python App": LiteSpeed's `lswsgi` launcher is missing for Python 3.11 on
this server, and short-lived worker processes would rebuild the 29k-record index on every cold start.

Shared hosting limits threads per account while the server has 64 cores, so `.env.production` sets
`OPENBLAS_NUM_THREADS=1`, `RAYON_NUM_THREADS=1`, `TOKENIZERS_PARALLELISM=false`, `HF_HUB_DISABLE_XET=1`,
`ORT_THREADS=2` and `STEM_WORKERS=2`; without them `import numpy` and the model download fail.

Update the code: `rsync -az --exclude-from=.rsyncignore --exclude data/ ./ trida:lab.trida.id/app/`,
then restart: `ssh trida 'pkill -f "[u]vicorn app.main:app"; sleep 2; ~/lab.trida.id/app/deploy/keepalive.sh'`.
