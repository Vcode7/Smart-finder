"""
Manual retrieval check against the live knowledge base (not a pytest test).

    venv\\Scripts\\python.exe scripts\\search_debug.py "modi" "ssc" "neet"
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.search.query_understanding import understand_multimodal_query  # noqa: E402
from app.search.multimodal_retrieval import search_by_multimodal_signals  # noqa: E402


async def run(queries):
    for q in queries:
        signals = await understand_multimodal_query({"textQuery": q}, use_llm=False)
        res = search_by_multimodal_signals(signals)
        print(f"=== Query: {q} ===")
        for cat in ["documents", "videos", "images", "audio"]:
            items = res.get(cat, [])
            if items:
                print(f"  {cat}:")
                for it in items:
                    print(f"    [{it.get('relevanceScore')}] {it.get('title', '')}")


if __name__ == "__main__":
    asyncio.run(run(sys.argv[1:] or ["modi", "ssc", "neet"]))
