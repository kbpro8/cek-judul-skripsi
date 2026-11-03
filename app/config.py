import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "cekjudul.sqlite3"

REPO_BASE = "https://repository.ar-raniry.ac.id"

ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "ganti-saya")

# Set SEMANTIC=0 to run on lexical similarity only (no model download needed).
# The embedding model itself is configured in embedder.py (EMBED_ONNX_FILE).
SEMANTIC = os.environ.get("SEMANTIC", "1") != "0"

# Status thresholds on the 0-100 combined score.
THRESHOLD_REVIEW = int(os.environ.get("THRESHOLD_REVIEW", 40))
THRESHOLD_HIGH = int(os.environ.get("THRESHOLD_HIGH", 70))

TOP_K = 10
