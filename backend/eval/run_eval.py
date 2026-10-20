"""
Search quality check against your own libraries (read-only).

    venv\\Scripts\\python.exe eval\\run_eval.py [--k 5] [--queries eval\\queries.json]

For each labelled query it reports where the first expected file appears, then
Recall@k (share of queries with an expected file in the top k) and MRR (mean of
1 / rank of the first expected file). Run it before and after changing weights,
calibration or models.
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--queries", type=Path, default=Path(__file__).with_name("queries.json"))
    args = ap.parse_args()

    from app.database.session import run_migrations
    from app.library.manager import get_library_manager
    from app.search.engine import SearchEngine
    from app.search.model_pipeline import warmup_query_models
    from app.search.plan import build_plan

    run_migrations()
    manager = get_library_manager()
    manager.load_all()
    warmup_query_models()
    engine = SearchEngine(manager)
    cases = json.loads(args.queries.read_text(encoding="utf-8"))["queries"]

    hits, rr_total, times = 0, 0.0, []
    for case in cases:
        t0 = time.time()
        results = engine.search(build_plan(case["query"]), 20).all()
        times.append(time.time() - t0)
        rank = next((i + 1 for i, r in enumerate(results)
                     if any(e.lower() in (r["relPath"] or r["title"]).lower() for e in case["expect"])), None)
        if rank and rank <= args.k:
            hits += 1
        rr_total += 1.0 / rank if rank else 0.0
        top = results[0] if results else None
        mark = "PASS" if rank and rank <= args.k else "MISS"
        print(f"{mark}  rank={rank or '-':<3} {case['query'][:48]:48s}  [{case.get('kind', '')}]")
        if top and (not rank or rank > 1):
            print(f"        top: {top['relevanceScore']:.2f} {top['title'][:70]}")
    n = len(cases)
    print(f"\nRecall@{args.k}: {hits}/{n} = {hits / n:.2f}   MRR: {rr_total / n:.3f}   "
          f"median latency: {sorted(times)[n // 2] * 1000:.0f} ms")
    manager.close_all()


if __name__ == "__main__":
    main()
