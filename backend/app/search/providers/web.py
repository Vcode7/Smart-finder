import uuid
import re
import urllib.parse
import httpx
from bs4 import BeautifulSoup
from typing import Dict, Any, List, Optional
from app.core.config import settings

async def search_web(
    query: str,
    options: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    opts = options or {}
    serp_api_key = settings.SERP_API_KEY
    page = int(opts.get("page") or 1)
    offset = int(opts.get("offset") or 0)
    limit = int(opts.get("limit") or 8)

    # 1. SerpAPI if configured
    if serp_api_key:
        try:
            params = {
                "q": query,
                "api_key": serp_api_key,
                "start": offset,
                "num": limit,
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get("https://serpapi.com/search", params=params)
                if res.status_code == 200:
                    data = res.json()
                    organic = data.get("organic_results", [])
                    if organic:
                        sources = []
                        for it in organic:
                            sources.append({
                                "id": str(uuid.uuid4()),
                                "type": "web",
                                "title": it.get("title", ""),
                                "url": it.get("link", ""),
                                "provider": it.get("source") or "Web",
                                "date": it.get("date"),
                                "thumbnail": it.get("thumbnail"),
                                "description": it.get("snippet") or "Web reference result.",
                                "relevanceScore": 75,
                                "quality": {"level": "medium", "reason": "SerpAPI organic result"},
                                "chatHistory": [],
                                "isSaved": False,
                                "isBookmarked": False,
                                "collectionIds": [],
                            })
                        return {
                            "provider": "SerpAPI Web Search",
                            "category": "web",
                            "status": "success",
                            "count": len(sources),
                            "sources": sources,
                            "offset": offset + len(sources),
                            "page": page + 1,
                        }
        except Exception as e:
            print(f"[WebProvider] SerpAPI error: {e}")

    # 2. DuckDuckGo HTML fallback
    try:
        web_variants = [
            query,
            f"{query} guide overview",
            f"{query} technical reference",
            f"{query} analysis documentation",
            f"{query} insights data",
        ]
        target_query = web_variants[(page - 1) % len(web_variants)] if page > 0 else query
        url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(target_query)}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(url, headers=headers)
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, "html.parser")
                links = soup.find_all("a", class_="result__a")
                snippets = [s.text.strip() for s in soup.find_all("a", class_="result__snippet")]

                sources = []
                for i, link_tag in enumerate(links[:limit]):
                    href = link_tag.get("href", "")
                    title = link_tag.text.strip()
                    # Clean redirect urls if present
                    final_url = href
                    if "uddg=" in href:
                        match = re.search(r"uddg=([^&]+)", href)
                        if match:
                            final_url = urllib.parse.unquote(match.group(1))

                    if final_url.startswith("http"):
                        sources.append({
                            "id": str(uuid.uuid4()),
                            "type": "web",
                            "title": title,
                            "url": final_url,
                            "provider": "DuckDuckGo Web",
                            "description": snippets[i] if i < len(snippets) else "Web reference result.",
                            "relevanceScore": max(50, 75 - i * 3),
                            "quality": {"level": "medium", "reason": "DuckDuckGo Web result"},
                            "chatHistory": [],
                            "isSaved": False,
                            "isBookmarked": False,
                            "collectionIds": [],
                        })

                if sources:
                    return {
                        "provider": "DuckDuckGo Live Search",
                        "category": "web",
                        "status": "success",
                        "count": len(sources),
                        "sources": sources,
                        "offset": offset + len(sources),
                        "page": page + 1,
                    }
    except Exception as e:
        print(f"[WebProvider] DuckDuckGo error: {e}")

    # 3. Wikipedia Open API fallback (reliable encyclopedia & web articles)
    try:
        wiki_url = "https://en.wikipedia.org/w/api.php"
        wiki_params = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": limit,
            "format": "json"
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(wiki_url, params=wiki_params, headers={"User-Agent": "SmartFind-Search/1.0"})
            if res.status_code == 200:
                wiki_items = res.json().get("query", {}).get("search", [])
                if wiki_items:
                    sources = []
                    for i, it in enumerate(wiki_items):
                        clean_snippet = re.sub(r"<[^>]+>", "", it.get("snippet", "")).strip()
                        sources.append({
                            "id": str(uuid.uuid4()),
                            "type": "web",
                            "title": it.get("title", ""),
                            "url": f"https://en.wikipedia.org/wiki/{urllib.parse.quote(it.get('title', ''))}",
                            "provider": "Wikipedia Knowledge",
                            "description": clean_snippet or f"Reference article on {it.get('title')}",
                            "relevanceScore": max(60, 85 - i * 3),
                            "quality": {"level": "high", "reason": "Wikipedia reference article"},
                            "chatHistory": [],
                            "isSaved": False,
                            "isBookmarked": False,
                            "collectionIds": [],
                        })
                    return {
                        "provider": "Wikipedia Knowledge Base",
                        "category": "web",
                        "status": "success",
                        "count": len(sources),
                        "sources": sources,
                        "offset": offset + len(sources),
                        "page": page + 1,
                    }
    except Exception as e:
        print(f"[WebProvider] Wikipedia fallback error: {e}")

    return {
        "provider": "Web Search",
        "category": "web",
        "status": "empty",
        "error": f'No web references found matching "{query}".',
        "count": 0,
        "sources": [],
    }
