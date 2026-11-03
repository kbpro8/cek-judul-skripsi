"""Similarity engine.

Each existing thesis is compared with the proposal on two levels:
  * title   - proposal title vs thesis title
  * content - proposal title + summary vs thesis title + abstract (only when a summary is given)

and with two kinds of signal:
  * lexical  - TF-IDF over stemmed words (unigrams + bigrams) and character n-grams, so
               reworded or lightly edited titles still match
  * semantic - cosine similarity of multilingual sentence embeddings, so the same topic in
               different words still matches (e.g. "perempuan" vs "wanita", "Pilkada" vs
               "pemilihan kepala daerah")
"""
import hashlib
import threading
import time

import numpy as np
from scipy.sparse import hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

from . import config
from .db import session
from .records import fill_stems
from .text import load_stem_cache, normalise, stem_text, word_stems

# Embedding cosines between unrelated Indonesian academic titles rarely drop below ~0.3,
# so the raw cosine is rescaled from [SEM_FLOOR, 1] to [0, 1].
SEM_FLOOR = 0.35
W_SEMANTIC = 0.6
W_WORD, W_CHAR = 0.65, 0.35

_model = None
_model_lock = threading.Lock()


def get_model():
    global _model
    if not config.SEMANTIC:
        return None
    with _model_lock:
        if _model is None:
            from .embedder import Embedder
            _model = Embedder()
    return _model


def doc_text(title: str, abstract: str | None) -> str:
    return f"{title}. {(abstract or '')[:800]}".strip()


def encode(texts: list[str]) -> np.ndarray:
    return get_model().encode(texts)


def _hash(title, abstract) -> str:
    from .embedder import MODEL_TAG
    return hashlib.md5(f"{MODEL_TAG}\x00{title}\x00{abstract or ''}".encode()).hexdigest()


def sync_embeddings(status: dict | None = None):
    """Compute embeddings for theses that are new, changed, or made with another model."""
    if not get_model():
        return
    with session() as conn:
        rows = conn.execute(
            """SELECT t.id, t.title, t.abstract, e.text_hash FROM theses t
               LEFT JOIN embeddings e ON e.thesis_id = t.id"""
        ).fetchall()
    todo = [r for r in rows if r["text_hash"] != _hash(r["title"], r["abstract"])]
    batch = 512
    for i in range(0, len(todo), batch):
        chunk = todo[i:i + batch]
        t_vecs = encode([r["title"] for r in chunk]).astype(np.float16)
        d_vecs = encode([doc_text(r["title"], r["abstract"]) for r in chunk]).astype(np.float16)
        with session() as conn:  # stored as float16: half the size, no measurable effect on ranking
            conn.executemany(
                "INSERT OR REPLACE INTO embeddings (thesis_id, text_hash, title_vec, doc_vec) VALUES (?, ?, ?, ?)",
                [(r["id"], _hash(r["title"], r["abstract"]), tv.tobytes(), dv.tobytes())
                 for r, tv, dv in zip(chunk, t_vecs, d_vecs)],
            )
        if status is not None:
            status["message"] = f"Menghitung embedding {min(i + batch, len(todo))}/{len(todo)}"


def _rescale(cos: np.ndarray) -> np.ndarray:
    return np.clip((cos - SEM_FLOOR) / (1 - SEM_FLOOR), 0, 1)


def _vectors(blob: bytes) -> np.ndarray:
    # float16 since the ONNX switch; older databases may still hold float32 rows
    return np.frombuffer(blob, dtype=np.float16 if len(blob) == 384 * 2 else np.float32)


class WordVectors:
    """TF-IDF over stemmed words: every single word, plus word pairs seen in 2+ theses.

    Pairs that occur only once (~70% of all pairs) cannot link two theses, so dropping
    them cuts the vocabulary from ~1.1M to ~0.35M terms without changing any match.
    """

    def __init__(self, docs: list[str]):
        opts = dict(sublinear_tf=True, token_pattern=r"\S+", dtype=np.float32)
        self.uni = TfidfVectorizer(ngram_range=(1, 1), min_df=1, **opts)
        self.bi = TfidfVectorizer(ngram_range=(2, 2), min_df=2, **opts)
        self.X_doc = normalize(hstack([self.uni.fit_transform(docs), self.bi.fit_transform(docs)]).tocsr())
        # Older scikit-learn keeps every pruned term in stop_words_ (~0.8M strings), for inspection only.
        self.uni.stop_words_ = self.bi.stop_words_ = None

    def transform(self, texts: list[str]):
        return normalize(hstack([self.uni.transform(texts), self.bi.transform(texts)]).tocsr())


class Index:
    DETAIL = ("id", "source", "title", "abstract", "author", "nim", "year", "program_name",
              "faculty", "level", "url")

    def __init__(self):
        with session() as conn:
            rows = conn.execute(
                """SELECT t.id, t.source, t.faculty, t.level, t.title, t.stem_title, t.stem_doc,
                          e.title_vec, e.doc_vec
                   FROM theses t LEFT JOIN embeddings e ON e.thesis_id = t.id ORDER BY t.id"""
            ).fetchall()
        # Only what scoring and filtering need stays in memory; result details are read
        # from SQLite for the top matches.
        self.size = len(rows)
        self.ids = np.array([r["id"] for r in rows], dtype=np.int64)
        self.faculty = np.array([r["faculty"] or "" for r in rows], dtype=object)
        self.source = np.array([r["source"] for r in rows], dtype=object)
        self.level = np.array([r["level"] or "" for r in rows], dtype=object)
        self.semantic = False
        if not rows:
            return

        self.words = WordVectors([r["stem_doc"] or "" for r in rows])
        self.X_title = self.words.transform([r["stem_title"] or "" for r in rows])
        self.char_vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True,
                                        dtype=np.float32)
        self.X_char = self.char_vec.fit_transform([normalise(r["title"]) for r in rows])
        self.char_vec.stop_words_ = None

        if get_model() and all(r["title_vec"] for r in rows):
            self.E_title = np.vstack([_vectors(r["title_vec"]) for r in rows]).astype(np.float32)
            self.E_doc = np.vstack([_vectors(r["doc_vec"]) for r in rows]).astype(np.float32)
            self.semantic = True

    def details(self, ids: list[int]) -> dict[int, dict]:
        marks = ",".join("?" * len(ids))
        with session() as conn:
            rows = conn.execute(f"SELECT {', '.join(self.DETAIL)} FROM theses WHERE id IN ({marks})", ids)
            return {r["id"]: dict(r) for r in rows}

    def search(self, title: str, abstract: str = "", faculty: str = "", source: str = "",
               level: str = "", k: int = config.TOP_K) -> dict:
        if not self.size:
            return {"results": [], "top_score": 0.0}
        abstract = (abstract or "").strip()

        q_title = self.words.transform([stem_text(title)])
        lex_title = W_WORD * (self.X_title @ q_title.T).toarray().ravel()
        lex_title += W_CHAR * (self.X_char @ self.char_vec.transform([normalise(title)]).T).toarray().ravel()
        lex_doc = None
        if abstract:
            q_doc = self.words.transform([stem_text(f"{title} {abstract}")])
            lex_doc = (self.words.X_doc @ q_doc.T).toarray().ravel()

        if self.semantic:
            qt, qd = encode([title, doc_text(title, abstract)])
            sem_title = _rescale(self.E_title @ qt)
            title_score = (1 - W_SEMANTIC) * lex_title + W_SEMANTIC * sem_title
            sem_doc = _rescale(self.E_doc @ qd)
            content_score = W_SEMANTIC * sem_doc + (1 - W_SEMANTIC) * (lex_doc if lex_doc is not None else lex_title)
        else:
            sem_title = sem_doc = None
            title_score = lex_title
            content_score = lex_doc if lex_doc is not None else lex_title

        # A near-identical title is a problem on its own; otherwise blend in the content match.
        score = np.maximum(title_score, 0.6 * title_score + 0.4 * content_score)

        mask = np.ones(self.size, dtype=bool)
        if faculty:
            mask &= self.faculty == faculty
        if source:
            mask &= self.source == source
        if level:
            mask &= self.level == level
        score = np.where(mask, score, -1.0)

        k = min(k, int(mask.sum()))
        if k == 0:
            return {"results": [], "top_score": 0.0}
        top = np.argpartition(-score, k - 1)[:k]
        top = top[np.argsort(-score[top])]

        q_stems = {s for _, s in word_stems(title)}
        info = self.details([int(self.ids[i]) for i in top])
        results = []
        for i in top:
            m = info[int(self.ids[i])]
            m["score"] = round(float(score[i]) * 100, 1)
            m["title_score"] = round(float(title_score[i]) * 100, 1)
            m["content_score"] = round(float(content_score[i]) * 100, 1)
            m["lexical"] = round(float(lex_title[i]) * 100, 1)
            m["semantic"] = round(float(sem_title[i]) * 100, 1) if sem_title is not None else None
            m["title_parts"] = [(w, s in q_stems) for w, s in _title_parts(m["title"])]
            m["status"] = status_of(m["score"])
            results.append(m)
        return {"results": results, "top_score": results[0]["score"]}


def _title_parts(title: str):
    stems = dict(word_stems(title))
    return [(w, stems.get(w, "")) for w in title.split()]


def status_of(score: float) -> str:
    if score >= config.THRESHOLD_HIGH:
        return "tinggi"
    if score >= config.THRESHOLD_REVIEW:
        return "tinjau"
    return "aman"


# --- global index, rebuilt in the background after harvests and uploads ---------------

state = {"index": None, "building": False, "message": "", "built_at": None}
_build_lock = threading.Lock()


def _release_memory():
    """Return memory freed after an index build to the OS.

    glibc keeps freed heap pages, so on Linux the process otherwise stays at its build peak
    (~1.5 GB instead of ~0.5 GB), which on shared hosting counts against the account's limit.
    """
    import ctypes
    import gc

    gc.collect()
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (OSError, AttributeError):  # not glibc (e.g. macOS)
        pass


def rebuild(blocking: bool = False):
    def run():
        if not _build_lock.acquire(blocking=False):
            return
        try:
            state.update(building=True, message="Menyiapkan indeks")
            with session() as conn:
                load_stem_cache(conn)
                fill_stems(conn, state)
            sync_embeddings(state)
            state["message"] = "Membangun indeks TF-IDF"
            state["index"] = Index()
            state.update(message="", built_at=time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()))
            _release_memory()
        except Exception as exc:
            state["message"] = f"Gagal membangun indeks: {exc}"
            raise
        finally:
            state["building"] = False
            _build_lock.release()

    if blocking:
        run()
    else:
        threading.Thread(target=run, daemon=True).start()
