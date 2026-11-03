"""Indonesian text normalisation: cleaning, stopword removal and Sastrawi stemming."""
import html
import re

from Sastrawi.Stemmer.StemmerFactory import StemmerFactory
from Sastrawi.StopWordRemover.StopWordRemoverFactory import StopWordRemoverFactory

_stemmer = StemmerFactory().create_stemmer()

# Words that appear in a large share of thesis titles and say nothing about the topic.
ACADEMIC_STOPWORDS = {
    "analisis", "studi", "kasus", "tinjauan", "terhadap", "tentang", "dalam", "pada",
    "di", "dan", "atau", "dengan", "untuk", "oleh", "sebagai", "melalui", "secara",
    "skripsi", "tesis", "disertasi", "penelitian", "kajian", "deskriptif", "kualitatif",
    "kuantitatif", "tahun", "kota", "kabupaten", "kecamatan", "desa", "gampong",
    "the", "of", "in", "and", "a", "an", "on", "to", "at", "for", "by", "with",
}
STOPWORDS = set(StopWordRemoverFactory().get_stop_words()) | ACADEMIC_STOPWORDS

_TAG = re.compile(r"<[^>]+>")
_NON_WORD = re.compile(r"[^a-z0-9\s-]")
_SPACE = re.compile(r"\s+")


def clean(text: str | None) -> str:
    """Strip HTML and collapse whitespace, keeping the original casing."""
    if not text:
        return ""
    text = html.unescape(_TAG.sub(" ", str(text)))
    return _SPACE.sub(" ", text).strip()


def normalise(text: str | None) -> str:
    """Lowercase, drop punctuation. Used for character n-grams."""
    text = clean(text).lower().replace("-", " ")
    return _SPACE.sub(" ", _NON_WORD.sub(" ", text)).strip()


# Sastrawi needs ~25 ms per unseen word, so stems are cached in memory and in the
# stem_cache table, and new vocabulary is stemmed in parallel (see stem_vocabulary).
_cache: dict[str, str] = {}


def _raw_stem(word: str) -> str:
    if word.isdigit() or len(word) <= 3:
        return word
    return _stemmer.stem(word) or word


def stem_word(word: str) -> str:
    s = _cache.get(word)
    if s is None:
        s = _cache[word] = _raw_stem(word)
    return s


def load_stem_cache(conn):
    _cache.update(conn.execute("SELECT word, stem FROM stem_cache").fetchall())


def stem_vocabulary(conn, words: set[str], workers: int | None = None, status: dict | None = None):
    """Stem words not yet cached, using all CPU cores, and persist them."""
    import os
    from concurrent.futures import ProcessPoolExecutor

    # One process per core would be 64 on the hosting server; shared hosting limits processes.
    workers = workers or int(os.environ.get("STEM_WORKERS", min(4, os.cpu_count() or 1)))
    load_stem_cache(conn)
    todo = sorted(w for w in words if w not in _cache)
    if not todo:
        return
    if status is not None:
        status["message"] = f"Stemming {len(todo):,} kata baru".replace(",", ".")
    if len(todo) < 500 or workers <= 1:
        stems = [_raw_stem(w) for w in todo]
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            stems = list(pool.map(_raw_stem, todo, chunksize=200))
    conn.executemany("INSERT OR REPLACE INTO stem_cache (word, stem) VALUES (?, ?)", zip(todo, stems))
    conn.commit()
    _cache.update(zip(todo, stems))


def vocabulary(text: str | None) -> set[str]:
    return {w for w in normalise(text).split() if w not in STOPWORDS and len(w) >= 2}


def tokens(text: str | None) -> list[str]:
    """Normalised, stopword-free, stemmed tokens."""
    out = []
    for w in normalise(text).split():
        if w in STOPWORDS or len(w) < 2:
            continue
        s = stem_word(w)
        if s and s not in STOPWORDS:
            out.append(s)
    return out


def stem_text(text: str | None) -> str:
    return " ".join(tokens(text))


def word_stems(text: str | None) -> list[tuple[str, str]]:
    """(original word, stem) pairs, used to highlight shared words in results."""
    pairs = []
    for raw in clean(text).split():
        w = normalise(raw)
        if not w or w in STOPWORDS:
            continue
        for part in w.split():
            if part not in STOPWORDS and len(part) >= 2:
                pairs.append((raw, stem_word(part)))
    return pairs
