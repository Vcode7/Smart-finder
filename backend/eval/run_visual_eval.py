"""
Image-embedder quality check against your own libraries (read-only).

    venv\\Scripts\\python.exe eval\\run_visual_eval.py [--k 5] [--queries eval\\visual_queries.json]

Unlike run_eval.py, captions, OCR text and keywords play no part: each query is embedded
into the image space and every library's image vectors are ranked, one entry per file.
Reports where the first expected file appears, Recall@1, Recall@k and MRR. Run it
before and after changing the image model.
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SEARCH_DEPTH = 1000


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--queries", type=Path, default=Path(__file__).with_name("visual_queries.json"))
    args = ap.parse_args()

    from app.database.session import run_migrations
    from app.library.manager import get_library_manager
    from app.search.model_pipeline import get_multimodal_text_embedding

    run_migrations()
    manager = get_library_manager()
    manager.load_all()
    libs = [lib for lib in manager.online() if lib.db is not None and lib.vectors is not None]
    cases = json.loads(args.queries.read_text(encoding="utf-8"))["queries"]

    top1, hits, rr_total, times = 0, 0, 0.0, []
    for case in cases:
        t0 = time.time()
        vec = get_multimodal_text_embedding(case["query"])
        times.append(time.time() - t0)
        if vec is None:
            print(f"SKIP  image model unavailable for: {case['query']}")
            continue
        found = []
        for lib in libs:
            for vid, score in lib.vectors.search("clip", vec, SEARCH_DEPTH):
                found.append((score, lib, vid))
        found.sort(key=lambda x: x[0], reverse=True)
        files, seen = [], set()
        for score, lib, vid in found:
            row = lib.db.one("SELECT s.id, s.rel_path FROM vectors v JOIN sources s ON s.id = v.source_id "
                             "WHERE v.id = ?", (vid,))
            if row is None or (lib.id, row["id"]) in seen:
                continue
            seen.add((lib.id, row["id"]))
            files.append((score, row["rel_path"]))
        rank = next((i + 1 for i, (_, path) in enumerate(files)
                     if any(e.lower() in path.lower() for e in case["expect"])), None)
        top1 += 1 if rank == 1 else 0
        hits += 1 if rank and rank <= args.k else 0
        rr_total += 1.0 / rank if rank else 0.0
        mark = "PASS" if rank and rank <= args.k else "MISS"
        print(f"{mark}  rank={rank or '-':<4} {case['query'][:56]:56s}  [{case.get('kind', '')}]")
        if files and (not rank or rank > 1):
            print(f"        top: {files[0][0]:.3f} {Path(files[0][1]).name[:70]}")
    n = len(cases)
    print(f"\nRecall@1: {top1}/{n} = {top1 / n:.2f}   Recall@{args.k}: {hits}/{n} = {hits / n:.2f}   "
          f"MRR: {rr_total / n:.3f}   median query embedding: {sorted(times)[n // 2] * 1000:.0f} ms")
    manager.close_all()


if __name__ == "__main__":
    main()
