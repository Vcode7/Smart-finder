"""
app/search/catalogs/registry.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The external library sources SmartFinder can search next to the local libraries, their
admin settings, and the fan-out that searches the enabled ones together.

Settings live in app_settings as JSON (`catalog.koha`, `catalog.dspace`). A source is
*available* once an admin has enabled it and given its URL; the search page shows a toggle for
each available source.

Every catalog is searched with its own timeout. One that fails or is slow reports a status
(shown above the results) and never fails the search. Answers are cached for a few minutes,
so re-running a search or moving the relevance slider does not query the catalogs again.
"""
from __future__ import annotations

import asyncio
import copy
import json
import re
import time
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import urlparse

import httpx

from app.database.session import get_app_setting, set_app_setting
from app.search.catalogs.base import CatalogError, CatalogRecord, CatalogStatus
from app.search.constants import STOPWORDS

SOURCES = ("koha", "dspace")
ALL_SOURCES = ("local",) + SOURCES
LABELS = {"local": "Local Files", "koha": "Koha Catalog", "dspace": "DSpace Repository"}
_NAMES = {"koha": "Koha", "dspace": "DSpace"}

DEFAULTS: Dict[str, Dict[str, Any]] = {
    "koha": {"enabled": False, "baseUrl": "", "apiUrl": "", "authType": "none", "username": "", "secret": "",
             "timeout": 10, "maxResults": 25},
    "dspace": {"enabled": False, "baseUrl": "", "uiUrl": "", "timeout": 10, "maxResults": 25},
}
AUTH_TYPES = ("none", "basic", "oauth2")
CACHE_TTL = 300
CACHE_MAX = 200
DERIVED_TERMS = 10          # words of an image's or document's text sent to the catalogs

_cache: Dict[Tuple[str, str, str], Tuple[float, List[CatalogRecord], Optional[int]]] = {}
_WORD_RE = re.compile(r"[^\W\d_][\w'-]+", re.UNICODE)


# ── settings ─────────────────────────────────────────────────────────────────
def get_config(source: str) -> Dict[str, Any]:
    cfg = dict(DEFAULTS[source])
    try:
        stored = json.loads(get_app_setting(f"catalog.{source}") or "{}")
        if isinstance(stored, dict):
            cfg.update({k: v for k, v in stored.items() if k in cfg})
    except ValueError:
        pass
    return cfg


def _url(value: Any, label: str) -> str:
    url = str(value or "").strip().rstrip("/")
    if url and (urlparse(url).scheme not in ("http", "https") or not urlparse(url).netloc):
        raise ValueError(f"{label} must start with http:// or https://")
    return url


def merge_config(source: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    """The stored settings with an admin's changes on top (not saved). A blank secret keeps the stored one."""
    cfg = get_config(source)
    for key in cfg:
        if key not in patch or patch[key] is None:
            continue
        value = patch[key]
        if key == "secret" and not str(value).strip():
            continue
        if key in ("baseUrl", "apiUrl", "uiUrl"):
            value = _url(value, {"baseUrl": "The URL", "apiUrl": "The API URL", "uiUrl": "The site URL"}[key])
        elif key == "enabled":
            value = bool(value)
        elif key == "timeout":
            value = max(2, min(60, int(value)))
        elif key == "maxResults":
            value = max(5, min(100, int(value)))
        elif key == "authType":
            value = str(value).lower()
            if value not in AUTH_TYPES:
                raise ValueError(f"authType must be one of {', '.join(AUTH_TYPES)}")
        else:
            value = str(value).strip()
        cfg[key] = value
    return cfg


def save_config(source: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    """Merge an admin's changes in and store them. Raises ValueError on bad input."""
    cfg = merge_config(source, patch)
    if cfg["enabled"] and not cfg["baseUrl"]:
        raise ValueError(f"Give the {_NAMES[source]} URL before enabling it")
    set_app_setting(f"catalog.{source}", json.dumps(cfg))
    _cache.clear()
    return cfg


def public_config(source: str) -> Dict[str, Any]:
    """The settings as the admin form shows them: secrets never leave the server."""
    cfg = get_config(source)
    out = {k: v for k, v in cfg.items() if k != "secret"}
    if "secret" in cfg:
        out["hasSecret"] = bool(cfg["secret"])
    return {"source": source, "label": LABELS[source], "available": is_available(cfg), **out}


def is_available(cfg: Dict[str, Any]) -> bool:
    return bool(cfg.get("enabled") and cfg.get("baseUrl"))


def available_sources() -> List[str]:
    return [s for s in SOURCES if is_available(get_config(s))]


def make_connector(source: str, cfg: Optional[Dict[str, Any]] = None):
    from app.search.catalogs.dspace import DSpaceConnector
    from app.search.catalogs.koha import KohaConnector
    cfg = cfg or get_config(source)
    return {"koha": KohaConnector, "dspace": DSpaceConnector}[source](cfg)


def parse_sources(raw: Any) -> Optional[Set[str]]:
    """The `sources` a search asked for (a list or "local,koha"); None when it did not say."""
    if raw is None:
        return None
    if isinstance(raw, str):
        raw = raw.strip()
        if raw.startswith("["):
            try:
                raw = json.loads(raw)
            except ValueError:
                raw = raw.strip("[]")
        if isinstance(raw, str):
            raw = raw.split(",")
    if not isinstance(raw, (list, tuple, set)):
        return None
    return {str(s).strip().lower() for s in raw if str(s).strip().lower() in ALL_SOURCES}


def resolve_sources(raw: Any) -> List[str]:
    """Sources to search, in display order: what was asked for and is available (all of them by default)."""
    asked = parse_sources(raw)
    usable = ["local"] + available_sources()
    return [s for s in usable if asked is None or s in asked]


# ── the query a catalog gets ─────────────────────────────────────────────────
def keywords(text: str, limit: int = DERIVED_TERMS) -> str:
    """The first distinct meaningful words of a longer text (OCR'd page, document passage)."""
    seen: Dict[str, str] = {}
    for w in _WORD_RE.findall(text or ""):
        low = w.lower().strip("'-")
        if len(low) < 3 or low in STOPWORDS or low in seen:
            continue
        seen[low] = w.strip("'-")
        if len(seen) >= limit:
            break
    return " ".join(seen.values())


def is_image_upload(file_name: Optional[str], mime_type: Optional[str]) -> bool:
    from app.search.constants import IMAGE_EXTENSIONS
    ext = (file_name or "").rsplit(".", 1)[-1].lower() if "." in (file_name or "") else ""
    return (mime_type or "").lower().startswith("image/") or ext in IMAGE_EXTENSIONS


def catalog_query(plan, image_bytes: Optional[bytes] = None) -> Tuple[str, Optional[str]]:
    """
    (query, where it came from: typed | ocr | document | speech) for the catalogs. Typed words
    win; an uploaded image (`image_bytes`) without words is read with OCR, also when the local
    search did not run it because its gate judged the picture unlikely to hold text. Blocking.
    ("", None) when there is nothing to search for.
    """
    if plan.text.strip():
        return plan.text.strip(), "typed"
    extra = {label: text for label, text, _ in plan.extra}
    if extra.get("image text"):
        return keywords(extra["image text"]), "ocr"
    if image_bytes:
        from app.search import model_pipeline as mp
        text = mp.run_ocr(image_bytes).strip()
        if text:
            plan.extra.append(("image text", text[:1500], 0.8))
            plan.trace["ocr"] = text[:300]
            return keywords(text), "ocr"
    doc = " ".join(t for label, t in extra.items() if label in ("document title", "document passage 1"))
    if doc.strip():
        return keywords(doc), "document"
    if extra.get("speech"):
        return keywords(extra["speech"]), "speech"
    return "", None


def plan_for_catalogs(query_text: str, file_buffer: Optional[bytes], file_name: Optional[str],
                      mime_type: Optional[str]):
    """
    The query plan when local search is switched off: the typed text and filters, and only what
    the catalogs need from an attachment (an image's text, not its vectors or faces). Blocking.
    """
    from app.search.plan import ImageSignal, QueryPlan, attach_file, parse_text
    clean, phrases, filters, boosts = parse_text(query_text)
    plan = QueryPlan(raw_text=query_text or "", text=clean, phrases=phrases, filters=filters, boosts=boosts)
    if file_buffer:
        if is_image_upload(file_name, mime_type):
            plan.images.append(ImageSignal(label=file_name or "image"))   # catalog_query reads its text
        else:
            attach_file(plan, file_buffer, file_name, mime_type)
    plan.trace["filters"] = plan.filters.describe()
    plan.trace["queryKind"] = plan.kind
    return plan


# ── searching ────────────────────────────────────────────────────────────────
def _cache_get(key: Tuple[str, str, str]) -> Optional[Tuple[List[CatalogRecord], Optional[int]]]:
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_TTL:
        return copy.deepcopy(hit[1]), hit[2]
    _cache.pop(key, None)
    return None


def _cache_put(key: Tuple[str, str, str], records: List[CatalogRecord], total: Optional[int]) -> None:
    if len(_cache) >= CACHE_MAX:
        for k in sorted(_cache, key=lambda k: _cache[k][0])[:CACHE_MAX // 4]:
            _cache.pop(k, None)
    _cache[key] = (time.monotonic(), copy.deepcopy(records), total)


def describe_error(source: str, e: Exception, cfg: Dict[str, Any]) -> Tuple[str, str]:
    name = _NAMES[source]
    if isinstance(e, asyncio.TimeoutError) or isinstance(e, httpx.TimeoutException):
        return "timeout", f"{name} did not answer within {cfg.get('timeout')} s"
    if isinstance(e, CatalogError):
        return "error", str(e)
    if isinstance(e, httpx.ConnectError):
        return "error", f"Could not reach {name} at {urlparse(cfg.get('baseUrl') or '').netloc or 'its URL'}"
    if isinstance(e, httpx.HTTPError):
        return "error", f"{name} connection failed ({type(e).__name__})"
    return "error", f"{name} search failed ({type(e).__name__})"


async def _search_one(source: str, query: str, derived: bool) -> Tuple[List[CatalogRecord], CatalogStatus]:
    cfg = get_config(source)
    status = CatalogStatus(source, query=query)
    key = (source, json.dumps(cfg, sort_keys=True), f"{int(derived)}:{query}")
    cached = _cache_get(key)
    if cached is not None:
        records, status.total = cached
        return records, status.finish("ok", len(records))
    connector = make_connector(source, cfg)
    limit = int(cfg.get("maxResults") or 25)

    async def run() -> Tuple[List[CatalogRecord], Optional[int]]:
        # Words read from an attachment rarely all appear in one record: any of them may match,
        # and the ranker sorts out which records are about the same thing
        records, total = await connector.search(query, limit, any_terms=derived)
        if not records and not derived and len(query.split()) > 1:
            records, total = await connector.search(query, limit, any_terms=True)
        return records, total

    try:
        records, total = await asyncio.wait_for(run(), timeout=float(cfg.get("timeout") or 10) + 2)
    except Exception as e:
        state, message = describe_error(source, e, cfg)
        print(f"[Catalogs] {source} search failed: {type(e).__name__}: {e}")
        return [], status.finish(state, 0, message)
    status.total = total
    _cache_put(key, records, total)
    return records, status.finish("ok", len(records))


async def search_catalogs(query: str, sources: Iterable[str], derived: bool = False) -> Tuple[List[CatalogRecord], List[CatalogStatus]]:
    """Every requested catalog at once: (all their records, a status per catalog)."""
    wanted = [s for s in sources if s in SOURCES]
    if not wanted:
        return [], []
    results = await asyncio.gather(*(_search_one(s, query, derived) for s in wanted))
    records = [r for recs, _ in results for r in recs]
    return records, [st for _, st in results]


def skipped(sources: Iterable[str], message: str) -> List[CatalogStatus]:
    return [CatalogStatus(s).finish("skipped", 0, message) for s in sources if s in SOURCES]
