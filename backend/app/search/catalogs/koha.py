"""
app/search/catalogs/koha.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Koha library catalog.

1. Search goes through the OPAC's own search engine (Zebra or Elasticsearch) as an RSS feed,
   opac-search.pl?format=rss: public on almost every Koha, and ranked by Koha's relevance.
2. The hits are filled in from the REST API's MARCXML (ISBN, subjects, abstract, 856 links):
   /api/v1/public/biblios/{id}, or the staff endpoint /api/v1/biblios/{id} when the admin gave
   credentials. A hit that cannot be filled in keeps what the feed said about it.

Records link to the OPAC detail page; 856 files link to wherever the catalog points (never
fetched by SmartFinder).
"""
from __future__ import annotations

import asyncio
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

import httpx
from defusedxml import ElementTree as SafeET

from app.search.catalogs.base import (
    SNIPPET_CHARS, USER_AGENT, CatalogError, CatalogFile, CatalogRecord, clean_text,
)

ENRICH_MAX = 25           # hits filled in from MARC per search
ENRICH_CONCURRENCY = 6
ENRICH_SHARE = 0.8          # of the timeout, from the search's start: a slow API keeps the feed's records

_BIBLIO_RE = re.compile(r"biblionumber=(\d+)")
_YEAR_RE = re.compile(r"(1[5-9]\d\d|20\d\d)")
_ISBN_RE = re.compile(r"[0-9Xx][0-9Xx\-]{8,16}")
_TRAIL = " /:;,.="


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(el, name: str) -> str:
    for c in el:
        if _local(c.tag) == name:
            return (c.text or "").strip()
    return ""


def parse_rss(payload: bytes, opac_url: str) -> Tuple[List[CatalogRecord], Optional[int]]:
    """Records (title, link, description) and the total Koha reported, from an OPAC RSS feed."""
    try:
        root = SafeET.fromstring(payload)
    except Exception as e:
        raise CatalogError("Koha did not return an RSS feed (is OPAC search public?)") from e
    total: Optional[int] = None
    records: List[CatalogRecord] = []
    for el in root.iter():
        name = _local(el.tag)
        if name == "totalResults" and (el.text or "").strip().isdigit():
            total = int(el.text.strip())
        if name not in ("item", "entry"):
            continue
        link = _child_text(el, "link") or _child_text(el, "guid") or _child_text(el, "id")
        if not link:
            for c in el:
                if _local(c.tag) == "link" and c.get("href"):
                    link = c.get("href")
                    break
        m = _BIBLIO_RE.search(link or "")
        if not m:
            continue
        bib = m.group(1)
        description = clean_text(_child_text(el, "description") or _child_text(el, "summary"))
        isbn = [s.replace("-", "") for s in _ISBN_RE.findall(_child_text(el, "identifier"))]
        records.append(CatalogRecord(
            id=f"koha:{bib}", source="koha", nativeId=bib,
            title=clean_text(_child_text(el, "title")).rstrip(_TRAIL) or f"Record {bib}",
            recordUrl=detail_url(opac_url, bib),
            authors=[a for a in [clean_text(_child_text(el, "creator"))] if a],
            snippet=clean_text(description, SNIPPET_CHARS) or None,
            isbn=isbn, nativeRank=len(records),
        ))
    return records, total


def detail_url(opac_url: str, biblionumber: str) -> str:
    return f"{opac_url}/cgi-bin/koha/opac-detail.pl?biblionumber={biblionumber}"


def _marc_fields(root) -> List[Tuple[str, str, Dict[str, List[str]]]]:
    """[(tag, ind1, {code: [values]})] for every datafield, plus controlfields as {"": [value]}."""
    out: List[Tuple[str, str, Dict[str, List[str]]]] = []
    for el in root.iter():
        name = _local(el.tag)
        if name == "controlfield":
            out.append((el.get("tag") or "", "", {"": [(el.text or "")]}))
        elif name == "datafield":
            subs: Dict[str, List[str]] = {}
            for sf in el:
                if _local(sf.tag) == "subfield":
                    subs.setdefault(sf.get("code") or "", []).append((sf.text or "").strip())
            out.append((el.get("tag") or "", (el.get("ind1") or "").strip(), subs))
    return out


def apply_marc(record: CatalogRecord, payload: bytes) -> None:
    """Fill a record in from a MARCXML biblio (MARC 21). Fields the record lacks stay as they were."""
    root = SafeET.fromstring(payload)
    fields = _marc_fields(root)

    def first(tag: str, code: str) -> str:
        for t, _i, subs in fields:
            if t == tag and subs.get(code):
                return subs[code][0]
        return ""

    title = " ".join(p.strip(_TRAIL) for p in (first("245", "a"), first("245", "b")) if p.strip(_TRAIL))
    if title:
        record.title = title
    authors = [subs["a"][0].strip(_TRAIL) for t, _i, subs in fields if t in ("100", "110", "700", "710") and subs.get("a")]
    if authors:
        record.authors = list(dict.fromkeys(a for a in authors if a))
    publisher = first("264", "b") or first("260", "b")
    if publisher:
        record.publisher = publisher.strip(_TRAIL)
    date = first("264", "c") or first("260", "c")
    m = _YEAR_RE.search(date or "") or _YEAR_RE.search((first("008", "") or "")[7:11])
    if m:
        record.year = m.group(1)
    subjects = []
    for t, _i, subs in fields:
        if t in ("650", "651", "653") and subs.get("a"):
            parts = subs["a"][:1] + subs.get("x", []) + subs.get("y", []) + subs.get("z", [])
            subjects.append(" -- ".join(p.strip(_TRAIL) for p in parts if p.strip(_TRAIL)))
    if subjects:
        record.subjects = list(dict.fromkeys(s for s in subjects if s))
    abstract = " ".join(subs["a"][0] for t, _i, subs in fields if t == "520" and subs.get("a"))
    if abstract.strip():
        # The summary says what the work is about; the feed's description is mostly the byline again
        record.abstract = clean_text(abstract, 2000)
        record.snippet = clean_text(abstract, SNIPPET_CHARS)
    isbns = []
    for t, _i, subs in fields:
        if t == "020":
            for v in subs.get("a", []):
                m = _ISBN_RE.search(v)
                if m:
                    isbns.append(m.group(0).replace("-", "").upper())
    if isbns:
        record.isbn = list(dict.fromkeys(isbns))
    for t, ind1, subs in fields:
        if t == "024":
            value = (subs.get("a") or [""])[0].strip()
            if value and ((subs.get("2") or [""])[0].lower() == "doi" or value.startswith("10.")):
                record.doi = value
                break
    record.itemType = first("942", "c") or record.itemType
    files = []
    for t, _i, subs in fields:
        if t != "856":
            continue
        for url in subs.get("u", []):
            if not url.startswith(("http://", "https://")):
                continue
            name = (subs.get("y") or subs.get("3") or subs.get("z") or [url.rstrip("/").rsplit("/", 1)[-1]])[0]
            files.append(CatalogFile(name=clean_text(name) or url, url=url,
                                     mimeType=(subs.get("q") or [None])[0]))
    if files:
        record.files = files


class KohaConnector:
    source = "koha"

    def __init__(self, cfg: Dict[str, Any]):
        self.opac = cfg["baseUrl"].rstrip("/")
        self.api = (cfg.get("apiUrl") or cfg["baseUrl"]).rstrip("/")
        self.auth_type = (cfg.get("authType") or "none").lower()
        self.username = cfg.get("username") or ""
        self.secret = cfg.get("secret") or ""
        self.timeout = float(cfg.get("timeout") or 10)

    def _client(self) -> httpx.AsyncClient:
        auth = (self.username, self.secret) if self.auth_type == "basic" and self.username else None
        return httpx.AsyncClient(timeout=self.timeout, follow_redirects=True, auth=auth,
                                 headers={"User-Agent": USER_AGENT})

    async def search(self, query: str, limit: int, any_terms: bool = False) -> Tuple[List[CatalogRecord], Optional[int]]:
        terms = query.split()
        if any_terms and len(terms) > 1:
            # Koha's advanced-search form: idx=kw&q=a&op=or&idx=kw&q=b...
            params: List[Tuple[str, str]] = []
            for i, t in enumerate(terms):
                if i:
                    params.append(("op", "or"))
                params += [("idx", "kw"), ("q", t)]
        else:
            params = [("q", query)]
        params += [("format", "rss"), ("count", str(limit)), ("sort_by", "relevance")]
        url = f"{self.opac}/cgi-bin/koha/opac-search.pl?{urlencode(params)}"
        deadline = time.monotonic() + self.timeout * ENRICH_SHARE
        async with self._client() as client:
            res = await client.get(url)
            if res.status_code != 200:
                raise CatalogError(f"Koha search answered HTTP {res.status_code}")
            records, total = parse_rss(res.content, self.opac)
            records = records[:limit]
            await self._enrich(client, records[:ENRICH_MAX], deadline)
        return records, total

    async def _token(self, client: httpx.AsyncClient) -> Optional[str]:
        cached = _TOKENS.get(self.api)
        if cached and cached[1] > time.monotonic():
            return cached[0]
        res = await client.post(f"{self.api}/api/v1/oauth/token", data={
            "grant_type": "client_credentials", "client_id": self.username, "client_secret": self.secret})
        if res.status_code != 200:
            raise CatalogError(f"Koha refused the API client credentials (HTTP {res.status_code})")
        data = res.json()
        token = data.get("access_token")
        _TOKENS[self.api] = (token, time.monotonic() + max(60, int(data.get("expires_in") or 3600)) - 30)
        return token

    async def _enrich(self, client: httpx.AsyncClient, records: List[CatalogRecord], deadline: float) -> None:
        """Fill the records in from MARC until `deadline`; the rest keep what the feed said."""
        if not records or time.monotonic() >= deadline:
            return
        headers = {"Accept": "application/marcxml+xml"}
        staff = self.auth_type in ("basic", "oauth2") and self.username
        if self.auth_type == "oauth2" and self.username:
            try:
                headers["Authorization"] = f"Bearer {await self._token(client)}"
            except Exception as e:      # the feed's records are still worth showing
                print(f"[Koha] API token notice: {e}")
                staff = False
        path = "/api/v1/biblios/" if staff else "/api/v1/public/biblios/"
        gate = asyncio.Semaphore(ENRICH_CONCURRENCY)

        async def one(rec: CatalogRecord) -> None:
            async with gate:
                try:
                    res = await client.get(f"{self.api}{path}{rec.nativeId}", headers=headers)
                    if res.status_code == 200:
                        apply_marc(rec, res.content)
                except Exception as e:
                    print(f"[Koha] biblio {rec.nativeId} not filled in: {e}")

        try:
            await asyncio.wait_for(asyncio.gather(*(one(r) for r in records)),
                                   timeout=max(0.0, deadline - time.monotonic()))
        except asyncio.TimeoutError:
            filled = sum(1 for r in records if r.isbn or r.subjects or r.files)
            print(f"[Koha] API slow: {filled} of {len(records)} records filled in from MARC")

    async def test(self) -> Dict[str, Any]:
        records, total = await self.search("library", 3)
        return {"records": len(records), "total": total,
                "sample": records[0].title if records else None}


_TOKENS: Dict[str, Tuple[Optional[str], float]] = {}
