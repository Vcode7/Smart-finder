"""
Count the files in every library's index (used by `smartfinder-ctl files`).

    venv/bin/python scripts/index_stats.py          # table
    venv/bin/python scripts/index_stats.py --json   # machine-readable
    venv/bin/python scripts/index_stats.py --summary  # one line (smartfinder-ctl status)

Reads the databases read-only, so it works while Smart Finder is running or stopped and
needs no login. Same counts as the Libraries page (app/library/manager.py summary()).
"""
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings  # noqa: E402

COLUMNS = ("indexed", "queued", "processing", "failed")


def _open_ro(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def collect() -> dict:
    db_path = settings.resolved_db_path
    if not db_path.exists():
        return {"database": str(db_path), "libraries": [], "totals": {}, "error": "database not created yet"}
    with _open_ro(db_path) as conn:
        rows = conn.execute(
            "SELECT id, name, kind, root_path, index_path FROM libraries ORDER BY created_at"
        ).fetchall()
    libraries = []
    totals = {c: 0 for c in COLUMNS + ("other", "total")}
    for row in rows:
        lib = {
            "id": row["id"], "name": row["name"], "kind": row["kind"], "path": row["root_path"],
            "online": row["kind"] == "linked" or bool(row["root_path"] and Path(row["root_path"]).is_dir()),
            "counts": {}, "total": 0, "error": None,
        }
        index_db = Path(row["index_path"]) / "index.db"
        if not index_db.exists():
            lib["error"] = "no index yet" if lib["online"] else "folder not available"
        else:
            try:
                with _open_ro(index_db) as conn:
                    lib["counts"] = {r["status"]: r["n"] for r in conn.execute(
                        "SELECT status, COUNT(*) AS n FROM sources GROUP BY status")}
            except sqlite3.Error as e:
                lib["error"] = str(e)
        lib["total"] = sum(lib["counts"].values())
        for c in COLUMNS:
            totals[c] += lib["counts"].get(c, 0)
        totals["other"] += lib["total"] - sum(lib["counts"].get(c, 0) for c in COLUMNS)
        totals["total"] += lib["total"]
        libraries.append(lib)
    return {"database": str(db_path), "libraries": libraries, "totals": totals}


def print_table(stats: dict) -> None:
    if stats.get("error"):
        print(f"No libraries: {stats['error']} ({stats['database']})")
        return
    head = ("Library", "Online") + tuple(c.capitalize() for c in COLUMNS) + ("Other", "Total")
    lines = []
    for lib in stats["libraries"]:
        c = lib["counts"]
        other = lib["total"] - sum(c.get(k, 0) for k in COLUMNS)
        lines.append((lib["name"], "yes" if lib["online"] else "NO")
                     + tuple(str(c.get(k, 0)) for k in COLUMNS) + (str(other), str(lib["total"])))
    t = stats["totals"]
    lines.append(("TOTAL", "") + tuple(str(t[k]) for k in COLUMNS) + (str(t["other"]), str(t["total"])))
    widths = [max(len(r[i]) for r in [head] + lines) for i in range(len(head))]
    fmt = "  ".join(f"{{:<{w}}}" if i < 2 else f"{{:>{w}}}" for i, w in enumerate(widths))
    print(fmt.format(*head))
    print("  ".join("-" * w for w in widths))
    for i, r in enumerate(lines):
        if i == len(lines) - 1:
            print("  ".join("-" * w for w in widths))
        print(fmt.format(*r))
    for lib in stats["libraries"]:
        where = lib["path"] or "(individually linked files)"
        note = f"  [{lib['error']}]" if lib["error"] else ""
        print(f"  {lib['name']}: {where}{note}")


def main() -> int:
    stats = collect()
    if "--json" in sys.argv[1:]:
        print(json.dumps(stats, indent=2))
    elif "--summary" in sys.argv[1:]:
        t = stats["totals"]
        if stats.get("error"):
            print(stats["error"])
        else:
            print(f"{t['indexed']} indexed in {len(stats['libraries'])} libraries "
                  f"({t['queued'] + t['processing']} waiting, {t['failed']} failed)")
    else:
        print_table(stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
