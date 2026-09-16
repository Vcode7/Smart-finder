import re
import uuid
import httpx
from typing import Dict, Any, List, Optional
from app.core.config import settings

def parse_duration(iso_str: str) -> str:
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso_str)
    if not match:
        return ""
    h = int(match.group(1) or 0)
    m = int(match.group(2) or 0)
    s = int(match.group(3) or 0)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"

import json
import urllib.parse

async def search_youtube_scrape_fallback(query: str, limit: int = 8) -> List[Dict[str, Any]]:
    try:
        url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(url, headers=headers)
            if res.status_code != 200:
                return []
            match = re.search(r"ytInitialData\s*=\s*({.+?});</script>", res.text)
            if not match:
                return []
            data = json.loads(match.group(1))
            sections = data.get("contents", {}).get("twoColumnSearchResultsRenderer", {}).get("primaryContents", {}).get("sectionListRenderer", {}).get("contents", [])
            sources = []
            for sec in sections:
                contents = sec.get("itemSectionRenderer", {}).get("contents", [])
                for it in contents:
                    vr = it.get("videoRenderer")
                    if not vr:
                        continue
                    vid = vr.get("videoId")
                    title = ""
                    runs = vr.get("title", {}).get("runs", [])
                    if runs:
                        title = runs[0].get("text", "")
                    elif vr.get("title", {}).get("simpleText"):
                        title = vr.get("title", {}).get("simpleText")
                    ch_runs = vr.get("ownerText", {}).get("runs", [])
                    channel = ch_runs[0].get("text", "") if ch_runs else ""
                    desc_snippets = vr.get("detailedMetadataSnippets", [])
                    desc = ""
                    if desc_snippets:
                        snippet_runs = desc_snippets[0].get("snippetText", {}).get("runs", [])
                        desc = "".join([s.get("text", "") for s in snippet_runs])
                    dur = vr.get("lengthText", {}).get("simpleText", "")
                    thumb = f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
                    if vid and title:
                        sources.append({
                            "id": f"yt-{vid}",
                            "type": "video",
                            "title": title,
                            "url": f"https://www.youtube.com/watch?v={vid}",
                            "provider": "YouTube",
                            "channel": channel,
                            "author": channel or "YouTube Creator",
                            "thumbnail": thumb,
                            "description": desc or f"YouTube video about {query}",
                            "duration": dur,
                            "viewCount": 0,
                            "relevanceScore": 85,
                            "quality": {"level": "medium", "reason": "YouTube live index"},
                            "chatHistory": [],
                            "isSaved": False,
                            "isBookmarked": False,
                            "collectionIds": [],
                        })
                    if len(sources) >= limit:
                        return sources
            return sources
    except Exception as e:
        print(f"[VideoProvider] Scrape fallback error: {e}")
        return []

async def search_videos(
    query: str,
    options: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    opts = options or {}
    api_key = settings.YOUTUBE_API_KEY
    limit = min(50, int(opts.get("maxResults") or 8))

    if api_key:
        try:
            params: Dict[str, Any] = {
                "part": "snippet",
                "q": query,
                "type": "video",
                "maxResults": limit,
                "relevanceLanguage": "en",
                "key": api_key,
            }
            if opts.get("pageToken"):
                params["pageToken"] = opts["pageToken"]

            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get("https://www.googleapis.com/youtube/v3/search", params=params)
                if res.status_code == 200:
                    data = res.json()
                    items = data.get("items", [])
                    next_page_token = data.get("nextPageToken")
                    if items:
                        video_ids = [it["id"]["videoId"] for it in items if it.get("id", {}).get("videoId")]
                        detail_map: Dict[str, Dict[str, str]] = {}

                        if video_ids:
                            try:
                                detail_res = await client.get(
                                    "https://www.googleapis.com/youtube/v3/videos",
                                    params={
                                        "part": "contentDetails,statistics",
                                        "id": ",".join(video_ids),
                                        "key": api_key,
                                    }
                                )
                                if detail_res.status_code == 200:
                                    detail_data = detail_res.json()
                                    for d_it in detail_data.get("items", []):
                                        detail_map[d_it["id"]] = {
                                            "duration": parse_duration(d_it.get("contentDetails", {}).get("duration", "")),
                                            "viewCount": str(d_it.get("statistics", {}).get("viewCount", "0")),
                                        }
                            except Exception:
                                pass

                        sources = []
                        for it in items:
                            vid = it["id"]["videoId"]
                            snippet = it.get("snippet", {})
                            details = detail_map.get(vid, {"duration": "", "viewCount": "0"})
                            thumbs = snippet.get("thumbnails", {})
                            thumb_url = thumbs.get("high", {}).get("url") or thumbs.get("medium", {}).get("url")

                            sources.append({
                                "id": f"yt-{vid}",
                                "type": "video",
                                "title": snippet.get("title", ""),
                                "url": f"https://www.youtube.com/watch?v={vid}",
                                "provider": "YouTube",
                                "channel": snippet.get("channelTitle", ""),
                                "author": snippet.get("channelTitle", ""),
                                "date": snippet.get("publishedAt"),
                                "thumbnail": thumb_url,
                                "description": snippet.get("description", ""),
                                "relevanceScore": 85,
                                "quality": {"level": "medium", "reason": "YouTube verified video"},
                                "chatHistory": [],
                                "isSaved": False,
                                "isBookmarked": False,
                                "collectionIds": [],
                                "duration": details["duration"],
                                "viewCount": int(details["viewCount"] or 0),
                            })

                        return {
                            "provider": "YouTube Data API v3",
                            "category": "video",
                            "status": "success",
                            "count": len(sources),
                            "sources": sources,
                            "nextPageToken": next_page_token,
                        }
        except Exception as e:
            print(f"[VideoProvider] API error: {e}, attempting scrape fallback")

    # Fallback to YouTube web scrape
    fallback_sources = await search_youtube_scrape_fallback(query, limit)
    if fallback_sources:
        return {
            "provider": "YouTube Web",
            "category": "video",
            "status": "success",
            "count": len(fallback_sources),
            "sources": fallback_sources,
            "nextPageToken": None,
        }

    return {
        "provider": "YouTube",
        "category": "video",
        "status": "empty",
        "error": f'No YouTube videos found matching "{query}".',
        "count": 0,
        "sources": [],
    }
