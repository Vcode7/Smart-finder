"""
app/people/cluster.py
~~~~~~~~~~~~~~~~~~~~~
People: faces grouped across every library, with names that survive regrouping.

Grouping. Every face with an identity vector (buffalo_l ArcFace) is linked to its nearest
neighbours when the similarity is at least LINK and the two faces are in each other's
top-K lists (mutual k-NN keeps one blurry face from chaining two people together). The
connected groups with at least MIN_GROUP faces become people.

Stable ids. A group keeps the person id most of its faces already had, so names stay
attached to the right group when it grows or is regrouped.

Corrections. A face assigned by hand (person_locked = 1) stays with that person — or with
nobody, for "not this person" — and anchors its group; two people that were assigned by
hand are never merged by the grouping.

Faces without a vector (repeated appearances in one video) follow their video track.
"""
from __future__ import annotations

import threading
import time
import uuid
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.database.session import db_all, db_get, get_db_context
from app.library.manager import LibraryManager, get_library_manager
from app.library.vector_store import decode

LINK = 0.50
K = 12
MIN_GROUP = 2

_lock = threading.Lock()
_last_signature: Optional[Tuple] = None


def _fp16(vec: np.ndarray) -> bytes:
    v = vec.astype(np.float32)
    n = float(np.linalg.norm(v)) or 1.0
    return (v / n).astype(np.float16).tobytes()


class _Union:
    """Union-find that refuses to join two groups anchored to different people."""

    def __init__(self, anchors: List[Optional[str]]):
        self.parent = list(range(len(anchors)))
        self.anchor = list(anchors)

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        pa, pb = self.anchor[ra], self.anchor[rb]
        if pa and pb and pa != pb:
            return
        self.parent[rb] = ra
        self.anchor[ra] = pa or pb


def _signature(manager: LibraryManager) -> Tuple:
    parts = []
    for lib in manager.online():
        if lib.db is None:
            continue
        row = lib.db.one("SELECT COUNT(*) AS n, COALESCE(MAX(id), 0) AS m FROM vectors WHERE space = 'face'")
        locked = lib.db.scalar("SELECT COUNT(*) FROM faces WHERE person_locked = 1", (), 0)
        parts.append((lib.id, row["n"], row["m"], locked))
    return tuple(sorted(parts))


def recluster(manager: Optional[LibraryManager] = None) -> Dict[str, Any]:
    """Regroup every face into people (blocking; seconds for tens of thousands of faces)."""
    import faiss
    manager = manager or get_library_manager()
    with _lock:
        t0 = time.time()
        entries: List[Dict[str, Any]] = []
        vecs: List[np.ndarray] = []
        for lib in manager.online():
            if lib.db is None:
                continue
            for r in lib.db.all(
                "SELECT f.id AS face_id, f.source_id, f.person_id, f.person_locked, f.quality, f.crop_path, v.emb "
                "FROM vectors v JOIN faces f ON f.id = v.entity_id WHERE v.space = 'face'"
            ):
                entries.append({"lib": lib, "face_id": r["face_id"], "source_id": r["source_id"],
                                "person_id": r["person_id"], "locked": bool(r["person_locked"]),
                                "quality": r["quality"] or 0.0, "crop": r["crop_path"]})
                vecs.append(decode(r["emb"]))
        n = len(entries)
        groups: Dict[int, List[int]] = {}
        if n:
            X = np.stack(vecs).astype(np.float32)
            X /= np.linalg.norm(X, axis=1, keepdims=True) + 1e-12
            # Faces marked "not this person" (locked, no person) take part in nothing
            anchors = [e["person_id"] if e["locked"] else None for e in entries]
            excluded = {i for i, e in enumerate(entries) if e["locked"] and not e["person_id"]}
            uf = _Union(anchors)
            k = min(K + 1, n)
            index = faiss.IndexFlatIP(X.shape[1])
            index.add(X)
            sims, nbrs = index.search(X, k)
            near = [{int(j) for j, s in zip(nbrs[i], sims[i]) if j != i and j >= 0 and s >= LINK}
                    for i in range(n)]
            for i in range(n):
                if i in excluded:
                    continue
                for j in near[i]:
                    if j not in excluded and i in near[j]:
                        uf.union(i, j)
            # Faces assigned to the same person by hand belong together
            by_locked: Dict[str, int] = {}
            for i, e in enumerate(entries):
                if e["locked"] and e["person_id"]:
                    if e["person_id"] in by_locked:
                        uf.union(by_locked[e["person_id"]], i)
                    else:
                        by_locked[e["person_id"]] = i
            for i in range(n):
                if i not in excluded:
                    groups.setdefault(uf.find(i), []).append(i)

        # Groups → person ids (keep the id most faces already had; anchors win)
        known = {r["id"]: r for r in db_all("SELECT id, name FROM persons")}
        assigned: Dict[int, Optional[str]] = {}
        taken: set = set()
        ordered = sorted(groups.values(), key=len, reverse=True)
        plan: List[Tuple[str, List[int]]] = []
        for members in ordered:
            anchor = next((entries[i]["person_id"] for i in members if entries[i]["locked"] and entries[i]["person_id"]), None)
            if len(members) < MIN_GROUP and anchor is None:
                for i in members:
                    assigned[i] = None
                continue
            pid = anchor
            if pid is None:
                votes = Counter(entries[i]["person_id"] for i in members
                                if entries[i]["person_id"] and entries[i]["person_id"] in known)
                pid = next((p for p, _ in votes.most_common() if p not in taken), None)
            if pid is None or pid in taken:
                pid = str(uuid.uuid4())
            taken.add(pid)
            for i in members:
                assigned[i] = pid
            plan.append((pid, members))
        for i, e in enumerate(entries):
            if e["locked"]:
                assigned[i] = e["person_id"]   # a hand assignment is never overridden

        # Write face assignments (only changes), then video-track members
        changed = 0
        by_lib: Dict[str, List[Tuple[Optional[str], int]]] = {}
        libs = {}
        for i, e in enumerate(entries):
            new = assigned.get(i)
            if new != e["person_id"]:
                by_lib.setdefault(e["lib"].id, []).append((new, e["face_id"]))
                libs[e["lib"].id] = e["lib"]
                changed += 1
        for lib_id, updates in by_lib.items():
            with libs[lib_id].db.write() as c:
                c.executemany("UPDATE faces SET person_id = ? WHERE id = ?", updates)
        for lib in manager.online():
            if lib.db is None:
                continue
            lib.db.execute(
                "UPDATE faces SET person_id = (SELECT f2.person_id FROM faces f2 "
                "  WHERE f2.source_id = faces.source_id AND f2.track_id = faces.track_id "
                "  AND f2.person_id IS NOT NULL ORDER BY f2.quality DESC LIMIT 1) "
                "WHERE track_id IS NOT NULL AND person_locked = 0 AND id NOT IN "
                "  (SELECT entity_id FROM vectors WHERE space = 'face')"
            )

        # People table: centroids, counts and a cover face for every group
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        with get_db_context() as conn:
            for pid, members in plan:
                centroid = np.mean(X[members], axis=0)
                cover = max(members, key=lambda i: (entries[i]["crop"] is not None, entries[i]["quality"]))
                ce = entries[cover]
                cover_ref = f"{ce['lib'].id}:{ce['source_id']}:{ce['face_id']}"
                conn.execute(
                    """INSERT INTO persons (id, name, centroid, face_count, cover_face, hidden, created_at, updated_at)
                       VALUES (?, NULL, ?, ?, ?, 0, ?, ?)
                       ON CONFLICT(id) DO UPDATE SET centroid = excluded.centroid, face_count = excluded.face_count,
                           cover_face = excluded.cover_face, updated_at = excluded.updated_at""",
                    (pid, _fp16(centroid), len(members), cover_ref, now, now),
                )
            used = [pid for pid, _ in plan]
            if used:
                conn.execute(f"UPDATE persons SET face_count = 0 WHERE id NOT IN ({','.join('?' * len(used))})", used)
            else:
                conn.execute("UPDATE persons SET face_count = 0")
            conn.execute("DELETE FROM persons WHERE face_count = 0 AND (name IS NULL OR name = '')")
            conn.commit()

        global _last_signature
        _last_signature = _signature(manager)
        return {"faces": n, "people": len(plan), "changed": changed, "seconds": round(time.time() - t0, 2)}


def maybe_recluster(manager: Optional[LibraryManager] = None) -> Optional[Dict[str, Any]]:
    """Regroup only when faces or hand assignments changed since the last run."""
    manager = manager or get_library_manager()
    if _signature(manager) == _last_signature:
        return None
    return recluster(manager)


# ── corrections ──────────────────────────────────────────────────────────────
def assign_face(manager: LibraryManager, lib_id: str, face_id: int, person_id: Optional[str]) -> None:
    """Put a face with a person (or with nobody: "not this person") and keep it there."""
    lib = manager.require(lib_id)
    assert lib.db is not None
    if person_id and not db_get("SELECT 1 FROM persons WHERE id = ?", (person_id,)):
        raise ValueError("Unknown person")
    lib.db.execute("UPDATE faces SET person_id = ?, person_locked = 1 WHERE id = ?", (person_id, face_id))


def merge(manager: LibraryManager, source_pid: str, target_pid: str) -> int:
    """'These are the same person': every face of source_pid moves to target_pid (kept there)."""
    if source_pid == target_pid:
        return 0
    if not db_get("SELECT 1 FROM persons WHERE id = ?", (target_pid,)):
        raise ValueError("Unknown person")
    moved = 0
    for lib in manager.online():
        if lib.db is None:
            continue
        moved += lib.db.execute(
            "UPDATE faces SET person_id = ?, person_locked = 1 WHERE person_id = ?", (target_pid, source_pid))
        # Both sides are now confirmed as one person: lock the target's faces too, or the
        # next regrouping could hand the id to one half and give the other half a new one
        lib.db.execute("UPDATE faces SET person_locked = 1 WHERE person_id = ?", (target_pid,))
    src = db_get("SELECT name FROM persons WHERE id = ?", (source_pid,))
    tgt = db_get("SELECT name FROM persons WHERE id = ?", (target_pid,))
    with get_db_context() as conn:
        if src and src.get("name") and not (tgt or {}).get("name"):
            conn.execute("UPDATE persons SET name = ? WHERE id = ?", (src["name"], target_pid))
        conn.execute("DELETE FROM persons WHERE id = ?", (source_pid,))
        conn.commit()
    return moved


def people_named_in(text: str) -> List[Dict[str, Any]]:
    """People whose name appears in the text (whole words, any case), longest names first."""
    import re
    low = f" {re.sub(r'[^0-9a-zA-Zऀ-ॿ]+', ' ', (text or '').lower())} "
    found = []
    for r in db_all("SELECT id, name, centroid FROM persons WHERE name IS NOT NULL AND name != '' AND hidden = 0"):
        name = re.sub(r"[^0-9a-zA-Zऀ-ॿ]+", " ", r["name"].lower()).strip()
        if name and f" {name} " in low:
            found.append({"id": r["id"], "name": r["name"], "match": name,
                          "centroid": decode(r["centroid"]).tolist() if r["centroid"] else None})
    found.sort(key=lambda p: len(p["match"]), reverse=True)
    return found


def person_face_vectors(manager: LibraryManager, person_id: str, limit: int = 6) -> List[List[float]]:
    """The person's best face vectors across libraries (for searching by name)."""
    picked: List[Tuple[float, List[float]]] = []
    for lib in manager.online():
        if lib.db is None:
            continue
        for r in lib.db.all(
            "SELECT f.quality, v.emb FROM faces f JOIN vectors v ON v.space = 'face' AND v.entity_id = f.id "
            "WHERE f.person_id = ? ORDER BY f.quality DESC LIMIT ?", (person_id, limit)
        ):
            picked.append((r["quality"] or 0.0, decode(r["emb"]).tolist()))
    picked.sort(key=lambda x: x[0], reverse=True)
    return [v for _, v in picked[:limit]]
