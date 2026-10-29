"""
External library sources: the Koha and DSpace connectors (against fake servers), ranking and
duplicate folding, the catalog settings API, and /search/smart with sources switched on and off.
"""
import io
import json

import httpx
import pytest

from tests.test_search_engine import api_library, fake_models  # noqa: F401  (fixtures)

OPAC = "https://opac.example.org"
DSPACE_API = "https://repo.example.org/server"

KOHA_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/" xmlns:dc="http://purl.org/dc/elements/1.1/">
<channel>
  <title>Koha search</title>
  <opensearch:totalResults>2</opensearch:totalResults>
  <item>
    <title>Urban drainage design /</title>
    <dc:identifier>ISBN 0306406152</dc:identifier>
    <link>https://opac.example.org/cgi-bin/koha/opac-detail.pl?biblionumber=42</link>
    <description><![CDATA[<p>By Smith, John.<br/>Water Press, 2019</p>]]></description>
  </item>
  <item>
    <title>Mango cultivation</title>
    <link>https://opac.example.org/cgi-bin/koha/opac-detail.pl?biblionumber=7</link>
    <description>Orchards and harvests.</description>
  </item>
</channel>
</rss>"""

MARC_42 = b"""<?xml version="1.0" encoding="UTF-8"?>
<record xmlns="http://www.loc.gov/MARC21/slim">
  <controlfield tag="008">190101s2019    ii a          000 0 eng d</controlfield>
  <datafield tag="020" ind1=" " ind2=" "><subfield code="a">0-306-40615-2 (pbk.)</subfield></datafield>
  <datafield tag="100" ind1="1" ind2=" "><subfield code="a">Smith, John,</subfield></datafield>
  <datafield tag="245" ind1="1" ind2="0"><subfield code="a">Urban drainage design :</subfield><subfield code="b">a handbook /</subfield></datafield>
  <datafield tag="264" ind1=" " ind2="1"><subfield code="b">Water Press,</subfield><subfield code="c">2019.</subfield></datafield>
  <datafield tag="520" ind1=" " ind2=" "><subfield code="a">Design of storm drainage networks and contracts for city works.</subfield></datafield>
  <datafield tag="650" ind1=" " ind2="0"><subfield code="a">Urban runoff</subfield><subfield code="x">Management.</subfield></datafield>
  <datafield tag="856" ind1="4" ind2="0"><subfield code="u">https://files.example.org/drainage.pdf</subfield><subfield code="y">Full text (PDF)</subfield></datafield>
</record>"""


def _dspace_item(uuid, title, *, abstract="", doi=None, isbn=None, author="Smith, John", date="2019-05-01"):
    md = {"dc.title": [{"value": title}], "dc.contributor.author": [{"value": author}],
          "dc.date.issued": [{"value": date}], "dc.subject": [{"value": "Drainage"}]}
    if abstract:
        md["dc.description.abstract"] = [{"value": abstract}]
    if doi:
        md["dc.identifier.doi"] = [{"value": doi}]
    if isbn:
        md["dc.identifier.isbn"] = [{"value": isbn}]
    return {"uuid": uuid, "name": title, "handle": "123456789/9", "metadata": md}


def _discover(*items, highlights=None):
    return {"_embedded": {"searchResult": {
        "page": {"totalElements": len(items)},
        "_embedded": {"objects": [
            {"hitHighlights": (highlights or {}).get(it["uuid"], {}), "_embedded": {"indexableObject": it}}
            for it in items]},
    }}}


UUID_A = "11111111-1111-1111-1111-111111111111"
UUID_B = "22222222-2222-2222-2222-222222222222"


@pytest.fixture(autouse=True)
def _fresh_cache():
    from app.search.catalogs import registry
    registry._cache.clear()
    yield
    registry._cache.clear()


def _mock(monkeypatch, connector_cls, handler):
    """Route a connector's HTTP calls to `handler` instead of the network."""
    original = connector_cls._client

    def client(self):
        real = original(self)
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), headers=real.headers,
                                 auth=real.auth, follow_redirects=True)

    monkeypatch.setattr(connector_cls, "_client", client)


# ── Koha ─────────────────────────────────────────────────────────────────────
def test_koha_reads_the_opac_feed_and_fills_records_in_from_marc(monkeypatch):
    from app.search.catalogs.koha import KohaConnector
    seen = []

    def handler(request: httpx.Request):
        seen.append(request)
        if request.url.path.endswith("opac-search.pl"):
            return httpx.Response(200, content=KOHA_RSS, headers={"content-type": "application/rss+xml"})
        if request.url.path.endswith("/biblios/42"):
            return httpx.Response(200, content=MARC_42)
        return httpx.Response(404)

    _mock(monkeypatch, KohaConnector, handler)
    import asyncio
    records, total = asyncio.run(KohaConnector({"baseUrl": OPAC}).search("drainage", 10))
    assert total == 2 and [r.nativeId for r in records] == ["42", "7"]
    first, second = records
    assert first.title == "Urban drainage design a handbook"
    assert first.recordUrl == f"{OPAC}/cgi-bin/koha/opac-detail.pl?biblionumber=42"
    assert first.authors == ["Smith, John"] and first.year == "2019" and first.publisher == "Water Press"
    assert first.isbn == ["0306406152"] and first.subjects == ["Urban runoff -- Management"]
    assert first.files[0].url == "https://files.example.org/drainage.pdf" and first.files[0].name == "Full text (PDF)"
    assert "storm drainage" in first.abstract
    # A record whose MARC cannot be read keeps what the feed said about it
    assert second.title == "Mango cultivation" and second.snippet == "Orchards and harvests."
    search = seen[0]
    assert search.url.params["q"] == "drainage" and search.url.params["format"] == "rss"
    assert any("/api/v1/public/biblios/42" in str(r.url) for r in seen)


def test_koha_any_terms_uses_the_advanced_search_form(monkeypatch):
    from app.search.catalogs.koha import KohaConnector
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, content=b"<rss><channel></channel></rss>")

    _mock(monkeypatch, KohaConnector, handler)
    import asyncio
    asyncio.run(KohaConnector({"baseUrl": OPAC}).search("storm drainage", 5, any_terms=True))
    params = seen[0].url.params
    assert params.get_list("q") == ["storm", "drainage"] and params.get_list("op") == ["or"]


def test_koha_html_instead_of_a_feed_is_reported(monkeypatch):
    from app.search.catalogs.base import CatalogError
    from app.search.catalogs.koha import KohaConnector
    _mock(monkeypatch, KohaConnector, lambda r: httpx.Response(200, content=b"<html><body>Log in<br></body></html>"))
    import asyncio
    with pytest.raises(CatalogError):
        asyncio.run(KohaConnector({"baseUrl": OPAC}).search("x", 5))


# ── DSpace ───────────────────────────────────────────────────────────────────
def test_dspace_reads_items_highlights_and_links(monkeypatch):
    from app.search.catalogs.dspace import DSpaceConnector
    payload = _discover(_dspace_item(UUID_A, "Storm water report", abstract="Runoff in wards.", doi="https://doi.org/10.1/abc"),
                        highlights={UUID_A: {"fulltext": ["the <em>drainage</em> contract was signed"]}})
    _mock(monkeypatch, DSpaceConnector, lambda r: httpx.Response(200, json=payload))
    import asyncio
    records, total = asyncio.run(DSpaceConnector({"baseUrl": DSPACE_API}).search("drainage", 10))
    rec = records[0]
    assert total == 1 and rec.id == f"dspace:{UUID_A}"
    assert rec.recordUrl == f"https://repo.example.org/items/{UUID_A}"      # UI url derived from /server
    assert rec.snippet == "the drainage contract was signed"             # full-text highlight first
    assert rec.doi == "10.1/abc" and rec.year == "2019" and rec.filesDeferred


def test_dspace_lists_files_and_marks_restricted_ones(monkeypatch):
    from app.search.catalogs.dspace import DSpaceConnector
    bundles = {"_embedded": {"bundles": [
        {"name": "THUMBNAIL", "_embedded": {"bitstreams": {"_embedded": {"bitstreams": [{"uuid": "t", "name": "t.jpg"}]}}}},
        {"name": "ORIGINAL", "_embedded": {"bitstreams": {"_embedded": {"bitstreams": [
            {"uuid": "open-1", "name": "report.pdf", "sizeBytes": 1200,
             "_embedded": {"format": {"mimetype": "application/pdf"}},
             "_links": {"content": {"href": f"{DSPACE_API}/api/core/bitstreams/open-1/content"}}},
            {"uuid": "closed-2", "name": "thesis.pdf",
             "_links": {"content": {"href": f"{DSPACE_API}/api/core/bitstreams/closed-2/content"}}},
        ]}}}},
    ]}}

    def handler(request):
        if request.url.path.endswith("/bundles"):
            return httpx.Response(200, json=bundles)
        return httpx.Response(403 if "closed-2" in request.url.path else 200)

    _mock(monkeypatch, DSpaceConnector, handler)
    import asyncio
    files, message = asyncio.run(DSpaceConnector({"baseUrl": DSPACE_API}).list_files(UUID_A))
    assert message is None and [f.name for f in files] == ["report.pdf", "thesis.pdf"]
    assert [f.access for f in files] == ["open", "restricted"]
    assert files[0].url == "https://repo.example.org/bitstreams/open-1/download" and files[0].mimeType == "application/pdf"


# ── ranking and duplicates ───────────────────────────────────────────────────
def _rec(source, nid, title, **kw):
    from app.search.catalogs.base import CatalogRecord
    return CatalogRecord(id=f"{source}:{nid}", source=source, nativeId=nid, title=title,
                         recordUrl=f"https://{source}.example.org/{nid}", **kw)


def test_records_are_ranked_by_meaning_and_duplicates_fold(mock_models_available):
    from app.search.catalogs.rank import dedupe, rank_records
    records = [
        _rec("koha", "1", "Mango cultivation", authors=["Rao, A."], nativeRank=0),
        _rec("koha", "42", "Urban drainage design", authors=["Smith, John"], isbn=["0306406152"], nativeRank=1),
        _rec("dspace", "a", "Urban drainage design", authors=["John Smith"], isbn=["9780306406157"],
             abstract="Drainage contracts for wards.", nativeRank=0),
        _rec("dspace", "b", "Quarterly minutes", authors=["Clerk"], snippet="the drainage contract was signed", nativeRank=1),
    ]
    ranked, trace = rank_records("drainage contract", records)
    assert trace["reranked"] == 4 and trace["candidates"] == 4
    assert all(0 <= r.relevanceScore <= 0.99 for r in ranked)
    assert "Mango cultivation" not in [r.title for r in ranked]      # off-topic: below the relevance floor
    assert "reranked" in ranked[0].matchedBy and "keywords" in ranked[0].matchedBy

    local = [{"id": "src-x", "title": "Quarterly minutes.txt"}]
    kept, folded = dedupe(ranked, local)
    titles = [r.title for r in kept]
    assert titles.count("Urban drainage design") == 1           # ISBN-10 and ISBN-13 are the same book
    book = next(r for r in kept if r.title == "Urban drainage design")
    assert {a["source"] for a in book.alsoIn} == {"koha", "dspace"} - {book.source}
    assert "Quarterly minutes" not in titles                    # the local file stands for it...
    assert local[0]["alsoIn"][0]["id"] == "dspace:b"            # ...and links to the record
    assert folded == 2


def test_keywords_keep_the_meaningful_words_in_order():
    from app.search.catalogs.registry import keywords
    assert keywords("The Annual Report of the Drainage Board, 2019: drainage and the city") == \
        "Annual Report Drainage Board city"


# ── API ──────────────────────────────────────────────────────────────────────
def _enable(c, source, **cfg):
    res = c.post(f"/api/catalogs/settings/{source}", json={"enabled": True, **cfg})
    assert res.status_code == 200, res.text
    return res.json()


def test_settings_are_admin_only_and_never_return_secrets(admin_client):
    c = admin_client
    sources = {s["id"]: s for s in c.get("/api/catalogs/sources").json()["sources"]}
    assert sources["local"]["available"] and not sources["koha"]["available"]

    assert c.post("/api/catalogs/settings/koha", json={"enabled": True}).status_code == 400   # no URL yet
    assert c.post("/api/catalogs/settings/koha", json={"baseUrl": "ftp://x"}).status_code == 400
    saved = _enable(c, "koha", baseUrl=OPAC + "/", authType="basic", username="api", secret="s3cret")
    assert saved["baseUrl"] == OPAC and saved["hasSecret"] and "secret" not in saved
    # A blank secret keeps the stored one
    again = c.post("/api/catalogs/settings/koha", json={"secret": "", "timeout": 999}).json()
    assert again["hasSecret"] and again["timeout"] == 60
    listed = {s["source"]: s for s in c.get("/api/catalogs/settings").json()["sources"]}
    assert "secret" not in json.dumps(listed["koha"]).replace("hasSecret", "")
    assert {s["id"]: s for s in c.get("/api/catalogs/sources").json()["sources"]}["koha"]["available"]
    assert c.post("/api/catalogs/settings/nope", json={}).status_code == 404


def _fake_catalogs(monkeypatch, koha=None, dspace=None):
    """Replace the connectors' search with canned answers (a list, or an exception to raise)."""
    from app.search.catalogs.dspace import DSpaceConnector
    from app.search.catalogs.koha import KohaConnector
    asked = {"koha": [], "dspace": []}

    def fake(source, answer):
        async def search(self, query, limit, any_terms=False):
            asked[source].append((query, any_terms))
            if isinstance(answer, Exception):
                raise answer
            return list(answer or []), len(answer or [])
        return search

    monkeypatch.setattr(KohaConnector, "search", fake("koha", koha))
    monkeypatch.setattr(DSpaceConnector, "search", fake("dspace", dspace))
    return asked


def test_smart_search_combines_sources_and_reports_failures(api_library, admin_client, monkeypatch):
    c = admin_client
    _enable(c, "koha", baseUrl=OPAC)
    _enable(c, "dspace", baseUrl=DSPACE_API)
    asked = _fake_catalogs(
        monkeypatch,
        koha=[_rec("koha", "42", "Drainage contract law", authors=["Smith, John"])],
        dspace=httpx.ConnectError("refused"))

    body = c.post("/api/search/smart", json={"query": "drainage contract"}).json()      # default: every source
    assert body["sources"] == ["local", "koha", "dspace"]
    assert body["local"]["documents"][0]["title"] == "minutes.txt"
    records = body["catalog"]["records"]
    assert [r["source"] for r in records] == ["koha"] and records[0]["recordUrl"].startswith("https://koha.")
    assert body["catalog"]["bySource"] == {"koha": 1, "dspace": 0}
    status = {s["source"]: s for s in body["sourceStatuses"]}
    assert status["koha"]["status"] == "ok" and status["dspace"]["status"] == "error"
    assert "Could not reach DSpace" in status["dspace"]["message"]
    assert body["discoveryTrace"]["catalogQueryOrigin"] == "typed"
    assert asked["koha"][0] == ("drainage contract", False)

    dash = c.post("/api/search/dashboard", json={"searchId": body["searchId"], "relativeThreshold": 100}).json()
    assert {f["source"] for f in dash["files"]} == {"local", "koha"}

    history = c.get("/api/search-history").json()["searches"]
    assert history[0]["sources"] == ["dspace", "koha", "local"]

    # Local switched off: only the catalogs answer
    only = c.post("/api/search/smart", json={"query": "drainage contract", "sources": ["koha"]}).json()
    assert only["sources"] == ["koha"] and only["local"]["total"] == 0 and only["catalog"]["total"] == 1
    # Nothing to search with
    assert c.post("/api/search/smart", json={"query": "x", "sources": []}).status_code == 400


def test_image_upload_searches_catalogs_with_its_text(admin_client, monkeypatch):
    import app.search.model_pipeline as mp
    from PIL import Image
    c = admin_client
    _enable(c, "koha", baseUrl=OPAC)
    asked = _fake_catalogs(monkeypatch, koha=[_rec("koha", "42", "Urban drainage handbook", authors=["Smith, John"])])
    monkeypatch.setattr(mp, "run_ocr", lambda *a, **k: "URBAN DRAINAGE HANDBOOK\nfor the city engineers")

    buf = io.BytesIO()
    Image.new("RGB", (64, 64), "white").save(buf, format="PNG")
    res = c.post("/api/search/smart", data={"sources": "koha", "enableInternet": "false"},
                 files={"file": ("cover.png", buf.getvalue(), "image/png")})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["discoveryTrace"]["catalogQueryOrigin"] == "ocr"
    query, any_terms = asked["koha"][0]
    assert "DRAINAGE" in query and any_terms
    assert body["catalog"]["records"][0]["title"] == "Urban drainage handbook"
