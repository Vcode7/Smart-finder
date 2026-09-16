import uuid
import re
import httpx
from bs4 import BeautifulSoup
from typing import Dict, Any, List, Optional
from app.core.config import settings

def parse_arxiv_xml(xml_content: str, limit: int = 8) -> List[Dict[str, Any]]:
    sources = []
    soup = BeautifulSoup(xml_content, "xml")
    entries = soup.find_all("entry")

    for entry in entries[:limit]:
        id_tag = entry.find("id")
        title_tag = entry.find("title")
        summary_tag = entry.find("summary")
        published_tag = entry.find("published")
        doi_tag = entry.find("arxiv:doi")

        authors = [a.find("name").text.strip() for a in entry.find_all("author") if a.find("name")]

        if title_tag and id_tag:
            title = re.sub(r"\s+", " ", title_tag.text).strip()
            summary = re.sub(r"\s+", " ", summary_tag.text).strip() if summary_tag else ""
            paper_url = id_tag.text.strip()
            pdf_url = paper_url.replace("/abs/", "/pdf/") + ".pdf"

            sources.append({
                "id": str(uuid.uuid4()),
                "type": "paper",
                "title": title,
                "url": pdf_url or paper_url,
                "provider": "arXiv Preprints",
                "author": ", ".join(authors) if authors else "arXiv Contributors",
                "date": published_tag.text.split("T")[0] if published_tag else None,
                "description": summary or "arXiv preprint abstract.",
                "abstract": summary,
                "relevanceScore": 88,
                "quality": {
                    "level": "high",
                    "reason": "arXiv peer-reviewed / academic preprint",
                    "details": "Cornell University arXiv repository"
                },
                "chatHistory": [],
                "isSaved": False,
                "isBookmarked": False,
                "collectionIds": [],
                "journal": "arXiv Repository",
                "doi": doi_tag.text.strip() if doi_tag else None,
                "citationCount": 0,
            })
    return sources

async def search_papers(
    query: str,
    options: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    opts = options or {}
    api_key = settings.SEMANTIC_SCHOLAR_API_KEY
    offset = int(opts.get("offset") or 0)
    limit = int(opts.get("limit") or 8)

    # 1. Semantic Scholar
    try:
        url = "https://api.semanticscholar.org/graph/v1/paper/search"
        params = {
            "query": query,
            "offset": offset,
            "limit": limit,
            "fields": "title,abstract,authors,year,venue,externalIds,openAccessPdf,citationCount,url"
        }
        headers = {"User-Agent": "AI-Research-Workspace/1.0"}
        if api_key:
            headers["x-api-key"] = api_key

        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(url, params=params, headers=headers)
            if res.status_code == 200:
                data = res.json()
                items = data.get("data", [])
                if items:
                    sources = []
                    for it in items:
                        author_names = [a.get("name") for a in it.get("authors", []) if a.get("name")]
                        open_access = it.get("openAccessPdf") or {}
                        paper_url = open_access.get("url") or it.get("url") or f"https://www.semanticscholar.org/paper/{it.get('paperId')}"
                        sources.append({
                            "id": str(uuid.uuid4()),
                            "type": "paper",
                            "title": it.get("title", ""),
                            "url": paper_url,
                            "provider": "Semantic Scholar",
                            "author": ", ".join(author_names) if author_names else "Academic Authors",
                            "date": f"{it.get('year')}-01-01" if it.get("year") else None,
                            "description": it.get("abstract") or "No abstract text provided.",
                            "abstract": it.get("abstract"),
                            "relevanceScore": 90,
                            "quality": {
                                "level": "high",
                                "reason": "Peer-reviewed academic paper",
                                "details": it.get("venue") or "Academic repository"
                            },
                            "chatHistory": [],
                            "isSaved": False,
                            "isBookmarked": False,
                            "collectionIds": [],
                            "journal": it.get("venue"),
                            "doi": (it.get("externalIds") or {}).get("DOI"),
                            "citationCount": it.get("citationCount", 0),
                        })
                    return {
                        "provider": "Semantic Scholar API",
                        "category": "paper",
                        "status": "success",
                        "count": len(sources),
                        "sources": sources,
                        "offset": offset + len(sources),
                    }
    except Exception as e:
        print(f"[PaperProvider] Semantic Scholar notice: {e}")

    # 2. arXiv fallback
    try:
        clean_q = re.sub(r"[^a-zA-Z0-9 ]", " ", query).strip()
        arxiv_url = "https://export.arxiv.org/api/query"
        params = {
            "search_query": f"all:{clean_q}",
            "start": offset,
            "max_results": limit
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(arxiv_url, params=params, headers={"User-Agent": "AI-Research-Workspace/1.0"})
            if res.status_code == 200:
                sources = parse_arxiv_xml(res.text, limit)
                if sources:
                    return {
                        "provider": "arXiv Open Repository",
                        "category": "paper",
                        "status": "success",
                        "count": len(sources),
                        "sources": sources,
                        "offset": offset + len(sources),
                    }
    except Exception as e:
        print(f"[PaperProvider] arXiv notice: {e}")

    # 3. Crossref fallback
    try:
        crossref_url = "https://api.crossref.org/works"
        params = {"query": query, "rows": limit, "offset": offset}
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(crossref_url, params=params, headers={"User-Agent": "AI-Research-Workspace/1.0"})
            if res.status_code == 200:
                data = res.json()
                items = (data.get("message") or {}).get("items", [])
                if items:
                    sources = []
                    for it in items:
                        title = (it.get("title") or ["Scholarly Research Paper"])[0]
                        authors = [
                            f"{a.get('given', '')} {a.get('family', '')}".strip()
                            for a in it.get("author", [])
                            if a.get("family") or a.get("given")
                        ]
                        doi = it.get("DOI")
                        paper_url = it.get("URL") or (f"https://doi.org/{doi}" if doi else "")
                        venue = (it.get("container-title") or ["Peer-Reviewed Journal"])[0]
                        created = it.get("created", {}).get("date-parts", [[None]])[0][0]

                        sources.append({
                            "id": str(uuid.uuid4()),
                            "type": "paper",
                            "title": title,
                            "url": paper_url,
                            "provider": "Crossref Scholarly Registry",
                            "author": ", ".join(authors) if authors else "Academic Researchers",
                            "date": f"{created}-01-01" if created else None,
                            "description": it.get("abstract") or f"Published research study in {venue}.",
                            "abstract": it.get("abstract"),
                            "relevanceScore": 85,
                            "quality": {
                                "level": "high",
                                "reason": "Crossref registered scholarly work",
                                "details": venue
                            },
                            "chatHistory": [],
                            "isSaved": False,
                            "isBookmarked": False,
                            "collectionIds": [],
                            "journal": venue,
                            "doi": doi,
                            "citationCount": it.get("is-referenced-by-count", 0),
                        })
                    return {
                        "provider": "Crossref Scholarly Registry",
                        "category": "paper",
                        "status": "success",
                        "count": len(sources),
                        "sources": sources,
                        "offset": offset + len(sources),
                    }
    except Exception as e:
        print(f"[PaperProvider] Crossref notice: {e}")

    return {
        "provider": "Academic Repositories",
        "category": "paper",
        "status": "empty",
        "error": f'No peer-reviewed papers found matching "{query}".',
        "count": 0,
        "sources": [],
        "offset": offset,
    }
