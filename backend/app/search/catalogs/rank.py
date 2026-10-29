"""
app/search/catalogs/rank.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Puts catalog records on the same 0-1 relevance scale as local files, and folds duplicates.

Koha and DSpace each rank by their own engine, and their orders cannot be compared with each
other or with local scores. Every record is judged again on its metadata (title, authors,
subjects, abstract, highlighted full text):

- keywords: the query's words found in the title (full weight) or elsewhere (less),
- meaning:  Qwen3 query↔record cosine, calibrated like the local dense retriever,
- reranker: Qwen3-Reranker on the best 30, combined as the engine does for files
            (0.7 × reranker + 0.3 × the best other evidence).

Without the models (cold start, tests) keywords and the catalog's own order decide.

Duplicates are the same work found twice: in both catalogs, twice in one, or a catalog record
of a file that is also in a local library. The best-scored copy stays; the others become its
`alsoIn` links, so no route to the original is lost. A local file always wins over a record of
it: the record's link moves onto the local result.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from app.search.catalogs.base import CatalogRecord
from app.search.engine import MIN_RELEVANCE, cal_dense, fts_terms

RERANK_MAX = 30
TITLE_KEY_MIN = 10          # shorter normalised titles ("Annual report") are too common to match on

_WORD_RE = re.compile(r"[\wऀ-ॿ]+", re.UNICODE)
_LEADING_ARTICLE = re.compile(r"^(the|a|an)\s+", re.IGNORECASE)
_EXT_RE = re.compile(r"\.[A-Za-z0-9]{1,5}$")


def _words(text: str) -> List[str]:
    return [w.lower() for w in _WORD_RE.findall(text or "")]


def keyword_score(terms: List[str], rec: CatalogRecord) -> float:
    if not terms:
        return 0.0
    title = set(_words(rec.title))
    body = set(_words(rec.text()))

    def found(t: str, words: set) -> bool:
        return t in words or (len(t) >= 4 and any(w.startswith(t) for w in words))

    score = sum(1.0 if found(t, title) else 0.6 if found(t, body) else 0.0 for t in terms) / len(terms)
    if len(terms) > 1 and " ".join(terms) in " ".join(_words(rec.title)):
        score = min(1.0, score + 0.15)
    return score


def _semantic(query: str, texts: List[str]) -> Optional[List[float]]:
    from app.search import model_pipeline as mp
    q = mp.get_text_query_embedding(query)
    if q is None:
        return None
    vecs = mp.get_text_embeddings_batch(texts)
    out = []
    for v in vecs:
        out.append(cal_dense(sum(a * b for a, b in zip(q, v))) if v is not None else 0.0)
    return out


def rank_records(query: str, records: List[CatalogRecord]) -> Tuple[List[CatalogRecord], Dict[str, Any]]:
    """Score every record in place; returns the relevant ones, best first, and a trace. Blocking."""
    from app.search import model_pipeline as mp
    if not records:
        return [], {}
    terms = fts_terms(query)
    texts = [r.text()[:1500] for r in records]
    kw = [keyword_score(terms, r) for r in records]
    try:
        sem = _semantic(query, texts)
    except Exception as e:
        print(f"[Catalogs] semantic scoring skipped: {e}")
        sem = None
    per_source: Dict[str, int] = {}
    for r in records:
        per_source[r.source] = per_source.get(r.source, 0) + 1
    native = [1.0 - r.nativeRank / max(1, per_source[r.source]) for r in records]

    pre = [(0.6 * sem[i] + 0.4 * kw[i]) if sem else (0.7 * kw[i] + 0.3 * native[i]) for i in range(len(records))]
    order = sorted(range(len(records)), key=lambda i: pre[i], reverse=True)
    top = order[:RERANK_MAX]
    rr: Optional[List[float]] = None
    try:
        rr = mp.rerank(query, [texts[i] for i in top]) if query.strip() else None
    except Exception as e:
        print(f"[Catalogs] rerank skipped: {e}")
    reranked = dict(zip(top, rr)) if rr else {}

    for i, rec in enumerate(records):
        evidence = max(sem[i] if sem else 0.0, kw[i])
        if i in reranked:
            score = 0.7 * reranked[i] + 0.3 * evidence
        elif sem:
            score = 0.75 * sem[i] + 0.25 * kw[i]
        else:
            score = 0.25 + 0.4 * kw[i] + 0.1 * native[i] if kw[i] > 0 else 0.1 * native[i]
        rec.relevanceScore = round(max(0.0, min(0.99, score)), 4)
        rec.matchedBy = [m for m, ok in (("keywords", kw[i] > 0), ("meaning", bool(sem) and sem[i] >= 0.3),
                                         ("reranked", i in reranked)) if ok]
    if reranked:
        # Records the reranker did not judge never outrank those it did
        floor = min(records[i].relevanceScore for i in reranked)
        for i, rec in enumerate(records):
            if i not in reranked:
                rec.relevanceScore = min(rec.relevanceScore, floor)
    kept = sorted((r for r in records if r.relevanceScore >= MIN_RELEVANCE),
                  key=lambda r: r.relevanceScore, reverse=True)
    return kept, {"candidates": len(records), "reranked": len(reranked), "semantic": sem is not None,
                  "kept": len(kept)}


# ── duplicates ───────────────────────────────────────────────────────────────
def norm_title(title: Optional[str]) -> str:
    t = _LEADING_ARTICLE.sub("", (title or "").strip())
    return re.sub(r"[^\w]", "", t.lower(), flags=re.UNICODE).replace("_", "")


def _surname(author: str) -> str:
    author = author.strip()
    if "," in author:
        return norm_title(author.split(",", 1)[0])
    parts = author.split()
    return norm_title(parts[-1]) if parts else ""


def _isbn13(isbn: str) -> str:
    digits = re.sub(r"[^0-9Xx]", "", isbn).upper()
    if len(digits) == 10:
        core = "978" + digits[:9]
        check = (10 - sum((1 if k % 2 == 0 else 3) * int(c) for k, c in enumerate(core)) % 10) % 10
        return core + str(check)
    return digits


def record_keys(rec: CatalogRecord) -> List[str]:
    keys: List[str] = []
    if rec.doi:
        keys.append("doi:" + rec.doi.strip().lower())
    keys += ["isbn:" + _isbn13(i) for i in rec.isbn if len(_isbn13(i)) == 13]
    if rec.handle:
        keys.append("hdl:" + rec.handle.strip().lower())
    title = norm_title(rec.title)
    if len(title) >= TITLE_KEY_MIN:
        who = _surname(rec.authors[0]) if rec.authors else ""
        if who:
            keys.append(f"t:{title}|{who}")
        elif rec.year:
            keys.append(f"t:{title}|{rec.year}")
    return keys


def _merge(kept: CatalogRecord, dup: CatalogRecord) -> None:
    kept.alsoIn.append({"source": dup.source, "id": dup.id, "title": dup.title, "recordUrl": dup.recordUrl})
    kept.alsoIn.extend(a for a in dup.alsoIn if a not in kept.alsoIn)
    urls = {f.url for f in kept.files}
    kept.files += [f for f in dup.files if f.url not in urls]
    kept.abstract = kept.abstract or dup.abstract
    kept.snippet = kept.snippet or dup.snippet
    kept.doi = kept.doi or dup.doi
    kept.isbn = list(dict.fromkeys(kept.isbn + dup.isbn))
    kept.subjects = list(dict.fromkeys(kept.subjects + dup.subjects))[:15]
    kept.year = kept.year or dup.year
    kept.thumbnail = kept.thumbnail or dup.thumbnail


def _local_title_keys(item: Dict[str, Any]) -> List[str]:
    keys = []
    for value in (item.get("title"), item.get("originalName")):
        t = norm_title(_EXT_RE.sub("", str(value or "")).replace("_", " ").replace("-", " "))
        if len(t) >= TITLE_KEY_MIN:
            keys.append(t)
    return list(dict.fromkeys(keys))


def dedupe(records: List[CatalogRecord], local_items: List[Dict[str, Any]]) -> Tuple[List[CatalogRecord], int]:
    """
    Records without duplicates, best first, and how many were folded away. A record of a local
    file is dropped and its link added to that file's `alsoIn` (the local dicts are changed in place).
    """
    by_key: Dict[str, CatalogRecord] = {}
    kept: List[CatalogRecord] = []
    folded = 0
    for rec in sorted(records, key=lambda r: r.relevanceScore, reverse=True):
        keys = record_keys(rec)
        match = next((by_key[k] for k in keys if k in by_key), None)
        if match is not None:
            _merge(match, rec)
            folded += 1
        else:
            kept.append(rec)
            match = rec
        for k in keys:
            by_key.setdefault(k, match)

    local_by_title: Dict[str, Dict[str, Any]] = {}
    for item in local_items:
        for k in _local_title_keys(item):
            local_by_title.setdefault(k, item)
    out: List[CatalogRecord] = []
    for rec in kept:
        local = local_by_title.get(norm_title(rec.title))
        if local is None:
            out.append(rec)
            continue
        links = local.setdefault("alsoIn", [])
        for ref in [{"source": rec.source, "id": rec.id, "title": rec.title, "recordUrl": rec.recordUrl}, *rec.alsoIn]:
            if ref not in links and ref.get("source") != "local":
                links.append(ref)
        folded += 1
    return out, folded
