"""Entry point for Phusion Passenger (cPanel "Setup Python App" on CloudLinux).

Passenger speaks WSGI, the app is ASGI (FastAPI), so a2wsgi bridges the two.
Settings come from .env.production next to this file (KEY=value lines, chmod 600).
"""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

env_file = os.path.join(ROOT, ".env.production")
if os.path.exists(env_file):
    with open(env_file) as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip("'\""))

# Shared hosting caps threads per account, and OpenBLAS otherwise starts one thread per
# CPU core (64 on the hosting.com server), which makes `import numpy` fail.
# The Rust libraries (tokenizers, the Hugging Face downloader) do the same.
for var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "RAYON_NUM_THREADS"):
    os.environ.setdefault(var, "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

from a2wsgi import ASGIMiddleware  # noqa: E402

from app.main import app, startup  # noqa: E402

# a2wsgi does not run ASGI lifespan events, so start the index build here.
startup()
application = ASGIMiddleware(app)
