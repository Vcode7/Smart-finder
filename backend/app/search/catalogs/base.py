"""
app/search/catalogs/base.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~
What every catalog connector (Koha, DSpace) returns: records in one shape, and a status per
source so a failing catalog is reported next to the results instead of failing the search.
"""
from __future__ import annotations

import html
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

USER_AGENT = "SmartFinder/1.0 (+catalog search)"
SNIPPET_CHARS = 320

_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")


def clean_text(value: Any, limit: Optional[int] = None) -> str:
    """Plain text from a catalog field that may hold HTML (RSS descriptions, highlights)."""
    text = _SPACE_RE.sub(" ", html.unescape(_TAG_RE.sub(" ", str(value or "")))).strip()
    if limit and len(text) > limit:
        cut = text[:limit].rsplit(" ", 1)[0]
        text = (cut or text[:limit]) + "…"
    return text


@dataclass
class CatalogFile:
    name: str
    url: str
    mimeType: Optional[str] = None
    size: Optional[int] = None
    access: str = "unknown"          # open | restricted | unknown


@dataclass
class CatalogRecord:
    id: str                          # "koha:<biblionumber>" | "dspace:<uuid>"
    source: str                      # koha | dspace
    nativeId: str
    title: str
    recordUrl: str                   # the exact OPAC detail page or repository item page
    authors: List[str] = field(default_factory=list)
    year: Optional[str] = None
    publisher: Optional[str] = None
    subjects: List[str] = field(default_factory=list)
    abstract: Optional[str] = None
    snippet: Optional[str] = None
    isbn: List[str] = field(default_factory=list)
    doi: Optional[str] = None
    handle: Optional[str] = None
    itemType: Optional[str] = None
    thumbnail: Optional[str] = None
    files: List[CatalogFile] = field(default_factory=list)
    filesDeferred: bool = False      # DSpace: the file list is fetched when the card asks for it
    nativeRank: int = 0              # position in the catalog's own result list
    relevanceScore: float = 0.0
    matchedBy: List[str] = field(default_factory=list)
    alsoIn: List[Dict[str, Any]] = field(default_factory=list)

    def text(self) -> str:
        """What the ranker reads: the record's descriptive metadata as one passage."""
        parts = [f"Title: {self.title}"]
        if self.authors:
            parts.append("By: " + "; ".join(self.authors[:6]))
        if self.subjects:
            parts.append("Subjects: " + "; ".join(self.subjects[:12]))
        if self.abstract:
            parts.append(self.abstract)
        if self.snippet and self.snippet not in (self.abstract or ""):
            parts.append(self.snippet)
        return "\n".join(parts)

    def as_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["category"] = "record"
        return d


@dataclass
class CatalogStatus:
    source: str
    status: str = "ok"               # ok | error | timeout | skipped
    count: int = 0
    total: Optional[int] = None      # matches the catalog reported (it may hold more than were fetched)
    message: Optional[str] = None
    ms: int = 0
    query: Optional[str] = None
    started: float = field(default_factory=time.monotonic, repr=False)

    def finish(self, status: str, count: int = 0, message: Optional[str] = None) -> "CatalogStatus":
        self.status, self.count, self.message = status, count, message
        self.ms = int((time.monotonic() - self.started) * 1000)
        return self

    def as_dict(self) -> Dict[str, Any]:
        return {"source": self.source, "status": self.status, "count": self.count, "total": self.total,
                "message": self.message, "ms": self.ms, "query": self.query}


class CatalogError(Exception):
    """A catalog answered, but not usefully (bad status, unreadable payload). The message is shown to users."""
