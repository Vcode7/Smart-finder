import uuid
import re
import urllib.parse
import httpx
from typing import Dict, Any, List
from app.core.config import settings

async def search_internet_images(query: str, limit: int = 8) -> List[Dict[str, Any]]:
    serp_api_key = settings.SERP_API_KEY
    if serp_api_key:
        try:
            params = {
                "engine": "google_images",
                "q": query,
                "api_key": serp_api_key,
                "num": limit,
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get("https://serpapi.com/search", params=params)
                if res.status_code == 200:
                    data = res.json()
                    images_results = data.get("images_results", [])
                    if images_results:
                        results = []
                        for img in images_results[:limit]:
                            link = img.get("link", "")
                            domain = "web"
                            if link:
                                try:
                                    domain = urllib.parse.urlparse(link).hostname or "web"
                                    domain = re.sub(r"^www\.", "", domain)
                                except Exception:
                                    pass

                            results.append({
                                "id": str(uuid.uuid4()),
                                "title": img.get("title") or query,
                                "url": img.get("original") or img.get("thumbnail") or "",
                                "thumbnail": img.get("thumbnail") or img.get("original") or "",
                                "sourceUrl": img.get("link") or img.get("original") or "",
                                "domain": domain,
                                "sourceType": "image",
                                "relevanceScore": 0.85,
                            })
                        if results:
                            return results
        except Exception as e:
            print(f"[ImageProvider] SerpAPI error: {e}")

    # Fallback: Wikimedia Commons Open Media API (zero config, reliable)
    try:
        url = "https://commons.wikimedia.org/w/api.php"
        params = {
            "action": "query",
            "generator": "search",
            "gsrsearch": query,
            "gsrnamespace": "6",
            "gsrlimit": limit,
            "prop": "imageinfo",
            "iiprop": "url|size|extmetadata",
            "format": "json"
        }
        headers = {"User-Agent": "SmartFind-Search/1.0"}
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(url, params=params, headers=headers)
            if res.status_code == 200:
                pages = res.json().get("query", {}).get("pages", {})
                results = []
                for _, page in pages.items():
                    infos = page.get("imageinfo", [])
                    if not infos:
                        continue
                    ii = infos[0]
                    img_url = ii.get("url")
                    if not img_url:
                        continue
                    clean_title = re.sub(r"^File:", "", page.get("title", "")).rsplit(".", 1)[0].replace("_", " ").strip()
                    results.append({
                        "id": str(uuid.uuid4()),
                        "title": clean_title or query,
                        "url": img_url,
                        "thumbnail": ii.get("thumburl") or img_url,
                        "sourceUrl": ii.get("descriptionurl") or img_url,
                        "domain": "commons.wikimedia.org",
                        "sourceType": "image",
                        "relevanceScore": 0.82,
                    })
                    if len(results) >= limit:
                        break
                if results:
                    return results
    except Exception as e:
        print(f"[ImageProvider] Wikimedia fallback error: {e}")

    return []
