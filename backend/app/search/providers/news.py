import uuid
import re
import urllib.parse
import httpx
from bs4 import BeautifulSoup
from typing import Dict, Any, List, Optional, Tuple
from app.core.config import settings

def parse_google_news_rss(xml_content: str, query: str, limit: int = 15) -> List[Dict[str, Any]]:
    sources = []
    soup = BeautifulSoup(xml_content, "xml")
    items = soup.find_all("item")

    for item in items[:limit]:
        title_tag = item.find("title")
        link_tag = item.find("link")
        pub_date_tag = item.find("pubDate")
        source_tag = item.find("source")
        desc_tag = item.find("description")

        if title_tag and link_tag:
            title = title_tag.text.strip()
            url = link_tag.text.strip()
            provider = source_tag.text.strip() if source_tag else "Google News"
            desc = ""
            if desc_tag:
                clean_desc = re.sub(r"<[^>]+>", " ", desc_tag.text)
                desc = re.sub(r"\s+", " ", clean_desc).strip()

            sources.append({
                "id": str(uuid.uuid4()),
                "type": "article",
                "title": title,
                "url": url,
                "provider": provider,
                "author": provider,
                "date": pub_date_tag.text.strip() if pub_date_tag else None,
                "thumbnail": None,
                "description": desc or f"Live news report on {query}.",
                "relevanceScore": 88,
                "quality": {"level": "medium", "reason": f"Published via {provider}"},
                "chatHistory": [],
                "isSaved": False,
                "isBookmarked": False,
                "collectionIds": [],
            })
    return sources

def split_articles_and_reports(sources: List[Dict[str, Any]], provider_name: str) -> Dict[str, Any]:
    articles = []
    reports = []

    for s in sources:
        lower_title = s.get("title", "").lower()
        lower_desc = s.get("description", "").lower()
        if any(k in lower_title or k in lower_desc for k in ["report", "policy", "study", "audit", "framework", "investigation"]):
            rep = s.copy()
            rep["type"] = "report"
            reports.append(rep)
        else:
            articles.append(s)

    if not reports and len(articles) > 2:
        reports = articles[-2:]
        for r in reports:
            r["type"] = "report"

    return {
        "articleResult": {
            "provider": provider_name,
            "category": "article",
            "status": "success" if articles else "empty",
            "count": len(articles),
        },
        "reportResult": {
            "provider": f"{provider_name} Policy",
            "category": "reports",
            "status": "success" if reports else "empty",
            "count": len(reports),
        },
        "articles": articles,
        "reports": reports,
    }

async def search_news(
    query: str,
    options: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    opts = options or {}
    api_key = settings.NEWS_API_KEY
    page = int(opts.get("page") or 1)
    limit = int(opts.get("limit") or 15)

    # 1. Try NewsAPI if configured
    if api_key:
        try:
            params = {
                "q": query,
                "sortBy": "relevancy",
                "pageSize": limit,
                "page": page,
                "language": "en",
            }
            headers = {"User-Agent": "AI-Research-Workspace/1.0", "X-Api-Key": api_key}
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get("https://newsapi.org/v2/everything", params=params, headers=headers)
                if res.status_code == 200:
                    data = res.json()
                    raw_articles = data.get("articles", [])
                    if raw_articles:
                        sources = []
                        for it in raw_articles:
                            src_name = (it.get("source") or {}).get("name") or "NewsAPI"
                            sources.append({
                                "id": str(uuid.uuid4()),
                                "type": "article",
                                "title": it.get("title", ""),
                                "url": it.get("url", ""),
                                "provider": src_name,
                                "author": it.get("author") or src_name,
                                "date": it.get("publishedAt"),
                                "thumbnail": it.get("urlToImage"),
                                "description": it.get("description") or f"Live news report on {query}.",
                                "relevanceScore": 88,
                                "quality": {"level": "medium", "reason": f"Published via {src_name}"},
                                "chatHistory": [],
                                "isSaved": False,
                                "isBookmarked": False,
                                "collectionIds": [],
                            })
                        return split_articles_and_reports(sources, "NewsAPI")
        except Exception as e:
            print(f"[NewsProvider] NewsAPI error: {e}")

    # 2. Google News RSS feed fallback
    try:
        page_suffix = f" {'analysis' if page == 2 else 'latest' if page == 3 else 'update'}" if page > 1 else ""
        clean_q = urllib.parse.quote(f"{query.strip()}{page_suffix}")
        gnews_url = f"https://news.google.com/rss/search?q={clean_q}&hl=en-US&gl=US&ceid=US:en"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(gnews_url, headers=headers)
            if res.status_code == 200:
                sources = parse_google_news_rss(res.text, query, limit)
                if sources:
                    return split_articles_and_reports(sources, "Google News Live Feed")
    except Exception as e:
        print(f"[NewsProvider] Google News RSS error: {e}")

    return {
        "articleResult": {
            "provider": "News Publications",
            "category": "article",
            "status": "empty",
            "error": f'No live news articles found matching "{query}".',
            "count": 0,
        },
        "reportResult": {
            "provider": "Policy Publications",
            "category": "reports",
            "status": "empty",
            "error": f'No policy reports found matching "{query}".',
            "count": 0,
        },
        "articles": [],
        "reports": [],
    }

async def search_articles_only(query: str, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    res = await search_news(query, options)
    page = int((options or {}).get("page") or 1)
    return {
        "sources": res.get("articles", []),
        "providerResult": res.get("articleResult"),
        "page": page + 1,
    }

async def search_reports_only(query: str, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    res = await search_news(query, options)
    page = int((options or {}).get("page") or 1)
    return {
        "sources": res.get("reports", []),
        "providerResult": res.get("reportResult"),
        "page": page + 1,
    }
