"""
app/search/catalogs/dspace.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
DSpace 7/8 repository, through its REST API (`/server/api`).

Search is the discovery endpoint, /api/discover/search/objects?dsoType=ITEM: DSpace's Solr
searches the metadata and, where text extraction runs, the full text of the files, and returns
highlights from both. An item's files are listed only when a result card asks for them
(list_files), as anonymous: a file anonymous users may read is "open", one DSpace refuses is
"restricted". Links always point at DSpace, which enforces its own permissions; SmartFinder never
downloads or proxies a file.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.search.catalogs.base import (
    SNIPPET_CHARS, USER_AGENT, CatalogError, CatalogFile, CatalogRecord, clean_text,
)

FILES_MAX = 20
ACCESS_CHECKS = 10        # files whose access is probed per item
_UUID_RE = re.compile(r"^[0-9a-fA-F-]{36}$")
_SOLR_SPECIAL = re.compile(r'[+\-!(){}\[\]^"~*?:\\/&|]')
_YEAR_RE = re.compile(r"(1[5-9]\d\d|20\d\d)")


def valid_uuid(value: str) -> bool:
    return bool(_UUID_RE.match(value or ""))


def _md(obj: Dict[str, Any], *keys: str) -> List[str]:
    meta = obj.get("metadata") or {}
    out: List[str] = []
    for k in keys:
        out += [str(v.get("value") or "").strip() for v in meta.get(k) or [] if isinstance(v, dict)]
    return [v for v in out if v]


def _highlight(hits: Dict[str, List[str]]) -> Optional[str]:
    """The best highlight: the full text's first, then the abstract's, then any field's."""
    if not hits:
        return None
    order = sorted(hits, key=lambda k: (0 if "fulltext" in k.lower() else 1 if "abstract" in k.lower() else 2))
    for k in order:
        parts = [clean_text(p) for p in hits.get(k) or [] if p]
        if parts:
            return clean_text(" … ".join(parts[:2]), SNIPPET_CHARS)
    return None


def parse_discover(payload: Dict[str, Any], api_url: str, ui_url: Optional[str]) -> Tuple[List[CatalogRecord], Optional[int]]:
    result = ((payload.get("_embedded") or {}).get("searchResult") or {})
    total = (result.get("page") or {}).get("totalElements")
    objects = ((result.get("_embedded") or {}).get("objects")) or []
    records: List[CatalogRecord] = []
    for obj in objects:
        item = ((obj.get("_embedded") or {}).get("indexableObject")) or {}
        uuid = item.get("uuid") or item.get("id")
        if not uuid:
            continue
        handle = item.get("handle")
        title = (_md(item, "dc.title") or [item.get("name") or "Untitled item"])[0]
        abstract = " ".join(_md(item, "dc.description.abstract"))
        date = (_md(item, "dc.date.issued") or [""])[0]
        year = _YEAR_RE.search(date)
        doi = next((v for v in _md(item, "dc.identifier.doi", "dc.identifier.uri", "dc.identifier")
                    if v.startswith("10.") or "doi.org/" in v), None)
        if doi and "doi.org/" in doi:
            doi = doi.split("doi.org/", 1)[1]
        isbn = [re.sub(r"[^0-9Xx]", "", v).upper() for v in _md(item, "dc.identifier.isbn")]
        thumb = ((((item.get("_embedded") or {}).get("thumbnail") or {}).get("_links") or {}).get("content") or {}).get("href")
        snippet = _highlight(obj.get("hitHighlights") or {}) or (clean_text(abstract, SNIPPET_CHARS) if abstract else None)
        records.append(CatalogRecord(
            id=f"dspace:{uuid}", source="dspace", nativeId=uuid,
            title=clean_text(title), recordUrl=item_url(uuid, handle, ui_url),
            authors=_md(item, "dc.contributor.author", "dc.creator")[:12],
            year=year.group(1) if year else None,
            publisher=(_md(item, "dc.publisher") or [None])[0],
            subjects=_md(item, "dc.subject")[:15],
            abstract=clean_text(abstract, 2000) or None, snippet=snippet,
            isbn=[i for i in isbn if len(i) in (10, 13)], doi=doi, handle=handle,
            itemType=(_md(item, "dc.type") or [None])[0], thumbnail=thumb,
            filesDeferred=True, nativeRank=len(records),
        ))
    return records, total


def item_url(uuid: str, handle: Optional[str], ui_url: Optional[str]) -> str:
    if ui_url:
        return f"{ui_url}/items/{uuid}"
    return f"https://hdl.handle.net/{handle}" if handle else ""


def default_ui_url(api_url: str) -> str:
    """https://repo.example.org/server → https://repo.example.org (the usual DSpace 7 layout)."""
    return re.sub(r"/server/?$", "", api_url.rstrip("/"))


class DSpaceConnector:
    source = "dspace"

    def __init__(self, cfg: Dict[str, Any]):
        self.api = cfg["baseUrl"].rstrip("/")
        self.ui = (cfg.get("uiUrl") or default_ui_url(self.api)).rstrip("/") or None
        self.timeout = float(cfg.get("timeout") or 10)

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self.timeout, follow_redirects=True,
                                 headers={"User-Agent": USER_AGENT, "Accept": "application/json"})

    async def search(self, query: str, limit: int, any_terms: bool = False) -> Tuple[List[CatalogRecord], Optional[int]]:
        terms = query.split()
        q = " OR ".join(terms) if any_terms and len(terms) > 1 else query
        async with self._client() as client:
            res = await self._discover(client, q, limit)
            if res.status_code in (400, 422):
                # Solr syntax in the query ("C++", "a:b"): search the words instead
                res = await self._discover(client, re.sub(r"\s+", " ", _SOLR_SPECIAL.sub(" ", q)).strip(), limit)
            if res.status_code != 200:
                raise CatalogError(f"DSpace search answered HTTP {res.status_code}")
            try:
                payload = res.json()
            except ValueError as e:
                raise CatalogError("DSpace did not return JSON (is the REST URL right? it usually ends in /server)") from e
        records, total = parse_discover(payload, self.api, self.ui)
        return records[:limit], total

    async def _discover(self, client: httpx.AsyncClient, query: str, limit: int) -> httpx.Response:
        return await client.get(f"{self.api}/api/discover/search/objects", params={
            "query": query, "dsoType": "ITEM", "size": limit, "page": 0, "embed": "thumbnail"})

    def _download_url(self, bitstream: Dict[str, Any]) -> str:
        if self.ui and bitstream.get("uuid"):
            # The UI's download route asks for a login when the file needs one
            return f"{self.ui}/bitstreams/{bitstream['uuid']}/download"
        return ((bitstream.get("_links") or {}).get("content") or {}).get("href") or ""

    async def list_files(self, uuid: str) -> Tuple[List[CatalogFile], Optional[str]]:
        """(files of the item's ORIGINAL bundle, a message when they cannot be listed)."""
        async with self._client() as client:
            res = await client.get(f"{self.api}/api/core/items/{uuid}/bundles",
                                   params={"embed": "bitstreams/format", "size": FILES_MAX})
            if res.status_code in (401, 403):
                return [], "The files of this item are restricted. Sign in to DSpace to open them."
            if res.status_code == 404:
                return [], "DSpace no longer has this item."
            if res.status_code != 200:
                return [], f"DSpace answered HTTP {res.status_code} for the files."
            bundles = ((res.json().get("_embedded") or {}).get("bundles")) or []
            raw: List[Dict[str, Any]] = []
            for b in bundles:
                if (b.get("name") or "").upper() == "ORIGINAL":
                    raw += ((((b.get("_embedded") or {}).get("bitstreams") or {}).get("_embedded") or {})
                            .get("bitstreams")) or []
            files: List[CatalogFile] = []
            for bs in raw[:FILES_MAX]:
                fmt = ((bs.get("_embedded") or {}).get("format")) or {}
                files.append(CatalogFile(name=bs.get("name") or "file", url=self._download_url(bs),
                                         mimeType=fmt.get("mimetype"), size=bs.get("sizeBytes")))
            content = [(f, ((bs.get("_links") or {}).get("content") or {}).get("href")) for f, bs in zip(files, raw)]
            await asyncio.gather(*(self._probe(client, f, href) for f, href in content[:ACCESS_CHECKS] if href))
        if not files:
            return [], "This item has no files."
        return files, None

    @staticmethod
    async def _probe(client: httpx.AsyncClient, f: CatalogFile, href: str) -> None:
        try:
            res = await client.head(href)
            if res.status_code == 405:          # older releases answer GET only; read a byte
                res = await client.get(href, headers={"Range": "bytes=0-0"})
            f.access = "open" if res.status_code in (200, 206) else \
                "restricted" if res.status_code in (401, 403) else "unknown"
        except Exception:
            f.access = "unknown"

    async def test(self) -> Dict[str, Any]:
        async with self._client() as client:
            res = await client.get(f"{self.api}/api")
            if res.status_code != 200:
                raise CatalogError(f"DSpace REST root answered HTTP {res.status_code}")
            try:
                root = res.json()
            except ValueError as e:
                raise CatalogError("No DSpace REST API at this URL (it usually ends in /server)") from e
        records, total = await self.search("research", 3)
        return {"version": root.get("dspaceVersion"), "name": root.get("dspaceName"),
                "records": len(records), "total": total, "sample": records[0].title if records else None}
