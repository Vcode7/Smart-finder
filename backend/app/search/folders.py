"""
app/search/folders.py
~~~~~~~~~~~~~~~~~~~~~
Folder names in a query ("dancing at Rahul wedding", "goa 2023/day 2").

Folder trees carry meaning a file name doesn't: `Events/Rahul Wedding/Haldi/IMG_2041.jpg`
is from the Haldi of Rahul's wedding. A library's folders are matched against the query
words; the folders that cover them best become scopes: every file below a scope is
boosted, and the remaining words rank the files inside it (see engine.py).

Matching is read from the current paths, so a renamed or moved folder matches by its
new name at once.
  * words           a query word matches a folder word when equal, or when one starts
                    with the other and they share 4+ letters (wedding / weddings);
                    numbers match exactly (day 2 ≠ day 21)
  * rarity          rare folder words count for more; a word naming the folders above
                    nearly every file ("photos" in Photos/...) and kind words ("videos")
                    never make a scope on their own
  * shallowest      the top-most folder covering the best set of words is the scope,
                    so "diwali" scopes Events/Diwali 2023 with all its subfolders and
                    "diwali day 2" scopes Events/Diwali 2023/Day 2
  * typed paths     "Diwali 2023/Day 2" (2+ segments) matching the end of a folder's
                    path scopes exactly that folder
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from app.library.manager import Library
from app.search.constants import tokenize

MAX_SCOPES = 8            # per library ("wedding" may name several weddings)
# A word naming the folders above nearly every file (Photos/... in a photo library), and
# scopes holding nearly every file, don't narrow anything
COMMON_SHARE = 0.9
MIN_PREFIX = 4

# Words that describe a kind of file or a default folder rather than what it is about
GENERIC_WORDS: Set[str] = {
    "photo", "photos", "picture", "pictures", "pics", "pic", "image", "images", "img", "screenshots",
    "screenshot", "video", "videos", "movies", "clips", "audio", "music", "recordings", "voice",
    "document", "documents", "docs", "doc", "pdf", "pdfs", "files", "file", "folder", "new", "misc",
    "other", "others", "stuff", "dcim", "camera", "download", "downloads", "desktop", "users", "home",
    "data", "backup", "backups", "copy", "untitled", "tmp", "temp",
}

_CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z])")
_LETTER_DIGIT = re.compile(r"(?<=[^\d\s_./-])(?=\d)|(?<=\d)(?=[^\d\s_./-])")


@dataclass
class FolderMatch:
    lib_id: str
    path: str                     # folder relative to the library root
    matched: List[str]            # query words the folder's path covers
    score: float                  # [0, 1]: share of the query's folder words covered
    files: int                    # files below it (all depths)
    exact: bool = False           # typed as a path

    def contains(self, folder: str) -> bool:
        return folder == self.path or folder.startswith(self.path + "/")

    def describe(self, library: str) -> Dict[str, object]:
        return {"libraryId": self.lib_id, "library": library, "path": self.path,
                "files": self.files, "matched": self.matched, "score": round(self.score, 3)}


def words(text: str) -> List[str]:
    """Words of a name or query: splits camelCase and letters from digits (Diwali2023)."""
    text = _LETTER_DIGIT.sub(" ", _CAMEL.sub(" ", text or ""))
    return [w for w in tokenize(text, min_len=1, drop_stopwords=True) if len(w) > 1 or w.isdigit()]


def query_words(text: str) -> List[str]:
    return list(dict.fromkeys(words(text)))


def word_matches(term: str, token: str) -> bool:
    if term == token:
        return True
    if term.isdigit() or token.isdigit():
        return False
    short, long_ = (term, token) if len(term) <= len(token) else (token, term)
    return len(short) >= MIN_PREFIX and long_.startswith(short)


def list_folders(lib: Library) -> Dict[str, int]:
    """Every folder holding files (at any depth below it) → number of those files."""
    assert lib.db is not None
    counts: Dict[str, int] = {}
    for r in lib.db.all(
        "SELECT folder, COUNT(*) AS n FROM sources WHERE status NOT IN ('missing', 'excluded') GROUP BY folder"
    ):
        folder = r["folder"] or ""
        if not folder:
            continue
        parts = folder.split("/")
        for i in range(1, len(parts) + 1):
            p = "/".join(parts[:i])
            counts[p] = counts.get(p, 0) + int(r["n"])
    return counts


def _total_files(lib: Library) -> int:
    assert lib.db is not None
    return int(lib.db.scalar("SELECT COUNT(*) FROM sources WHERE status NOT IN ('missing', 'excluded')", (), 0) or 0)


def _depth(path: str) -> int:
    return path.count("/")


def _typed_paths(text: str, folders: Dict[str, int]) -> Dict[str, str]:
    """Folders whose path ends with a path typed in the query (two or more segments) → that text."""
    norm = re.sub(r"\s*/\s*", "/", (text or "").replace("\\", "/").lower())
    if "/" not in norm:
        return {}
    found: Dict[str, str] = {}
    for path in folders:
        parts = path.lower().split("/")
        for k in range(len(parts), 1, -1):
            tail = "/".join(parts[-k:])
            if re.search(rf"(?<![^\s/\"']){re.escape(tail)}(?![^\s/\"'])", norm):
                found[path] = tail
                break
    # "trips/goa" typed: the folder Trips/Goa, not every Trips/Goa/... below it
    return {p: t for p, t in found.items() if not any(q != p and p.startswith(q + "/") for q in found)}


def match_folders(lib: Library, text: str) -> List[FolderMatch]:
    """The folders of `lib` the query names, best first (empty when none does)."""
    if lib.db is None or not text.strip():
        return []
    folders = list_folders(lib)
    if not folders:
        return []
    total = max(1, _total_files(lib))

    typed = _typed_paths(text, folders)
    if typed:
        return [FolderMatch(lib.id, p, query_words(tail), 1.0, folders[p], exact=True)
                for p, tail in sorted(typed.items(), key=lambda kv: -folders[kv[0]])[:MAX_SCOPES]]

    terms = query_words(text)
    if not terms:
        return []
    own: Dict[str, List[str]] = {p: words(p.rsplit("/", 1)[-1]) for p in folders}

    # Which folders each query word names (by the folder's own name), and how common it is
    named_by: Dict[str, Set[str]] = {}
    for t in terms:
        hit = {p for p, toks in own.items() if any(word_matches(t, tok) for tok in toks)}
        if hit:
            named_by[t] = hit
    if not named_by:
        return []

    def files_below(paths: Set[str]) -> int:
        tops = [p for p in paths if not any(q != p and p.startswith(q + "/") for q in paths)]
        return sum(folders[p] for p in tops)

    weight: Dict[str, float] = {}
    for t, paths in named_by.items():
        share = files_below(paths) / total
        weight[t] = 0.0 if share > COMMON_SHARE else math.log(1.0 + 1.0 / max(share, 1e-6))
    meaningful = {t for t, w in weight.items() if w > 0 and t not in GENERIC_WORDS}
    if not meaningful:
        return []
    available = sum(weight[t] for t in named_by)

    # A folder covers the words naming it or any folder above it
    candidates: List[Tuple[str, Set[str], float]] = []
    for path in folders:
        parts = path.split("/")
        covered: Set[str] = set()
        for t, paths in named_by.items():
            if any("/".join(parts[:i]) in paths for i in range(1, len(parts) + 1)):
                covered.add(t)
        if covered & meaningful:
            candidates.append((path, covered, sum(weight[t] for t in covered)))
    if not candidates:
        return []
    best = max(w for _, _, w in candidates)
    top = [(p, c, w) for p, c, w in candidates if w >= best - 1e-9]
    kept = {p for p, _, _ in top}
    # Shallowest only: a folder's subfolders are inside its scope already
    top = [(p, c, w) for p, c, w in top
           if not any(q != p and p.startswith(q + "/") for q in kept)]
    top.sort(key=lambda x: (-folders[x[0]], _depth(x[0]), x[0]))
    top = top[:MAX_SCOPES]
    if sum(folders[p] for p, _, _ in top) > COMMON_SHARE * total:
        return []
    score = min(1.0, best / available) if available > 0 else 0.0
    return [FolderMatch(lib.id, p, sorted(c, key=terms.index), score, folders[p]) for p, c, _ in top]


def scope_members(lib: Library, scopes: List[FolderMatch], allowed: Optional[Set[str]],
                  limit: int = 5000) -> Dict[str, float]:
    """source id → score of the best scope holding it."""
    assert lib.db is not None
    out: Dict[str, float] = {}
    for s in sorted(scopes, key=lambda s: -s.score):
        # Index range scan: the folder itself, then everything in [path/, path0) (0 sorts after /)
        rows = lib.db.all(
            "SELECT id FROM sources WHERE status NOT IN ('missing', 'excluded') "
            "AND (folder = ? OR (folder >= ? AND folder < ?)) LIMIT ?",
            (s.path, s.path + "/", s.path + "0", limit),
        )
        for r in rows:
            if (allowed is None or r["id"] in allowed) and r["id"] not in out:
                out[r["id"]] = s.score
        if len(out) >= limit:
            break
    return out


def without_words(text: str, matched: Set[str]) -> str:
    """The query with the words that named folders taken out."""
    kept = []
    for w in re.split(r"[\s/\\]+", text or ""):
        toks = words(w)
        if toks and all(t in matched for t in toks):
            continue
        kept.append(w)
    return " ".join(w for w in kept if w).strip()
