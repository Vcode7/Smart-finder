"""
app/library/vector_store.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Per-library vector store: SQLite `vectors` table (float16, full dimension) is the
source of truth; one FAISS index per space is a rebuildable cache keyed by vectors.id.

Index tiers per space:
  * fewer than IVF_THRESHOLD vectors: IndexIDMap2(IndexScalarQuantizer fp16) — exact
  * from IVF_THRESHOLD: IndexIVFPQ (trained on a sample), candidates re-scored exactly
    from the SQLite float16 vectors

Persistence: `checkpoint()` serializes each dirty index (atomic replace) and records the
highest vector id it contains (vectors are inserted by one writer in id order, so every
lower id is in the index too). On load, rows added after the checkpoint are replayed and
deletions recorded in vector_tombstones are re-applied, so a crash never desyncs the
index from SQLite. A tombstone is dropped one checkpoint after it was seen, by which time
its removal is certainly part of the saved index. Index files are written through Python file I/O (serialize_index),
which — unlike faiss.write_index — handles non-ASCII paths on Windows.
"""
from __future__ import annotations

import math
import os
import threading
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import faiss

from app.library.db import LibraryDB

SPACE_DIMS: Dict[str, int] = {"text": 1024, "clip": 1024, "face": 512, "clap": 512}
IVF_THRESHOLD = int(os.environ.get("SMARTFIND_IVF_THRESHOLD", "200000"))
EXACT_SUBSET_LIMIT = 20000      # filtered searches over at most this many ids are scored exactly
RERANK_FACTOR = 8               # IVF-PQ candidates per requested result
_BATCH = 10000


def encode(vec: Sequence[float]) -> bytes:
    arr = np.asarray(vec, dtype=np.float32)
    norm = float(np.linalg.norm(arr))
    if norm > 0:
        arr = arr / norm
    return arr.astype(np.float16).tobytes()


def decode(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float16).astype(np.float32)


def _normalized(vecs: np.ndarray) -> np.ndarray:
    vecs = np.asarray(vecs, dtype=np.float32)
    if vecs.ndim == 1:
        vecs = vecs[None, :]
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return np.ascontiguousarray(vecs / norms, dtype=np.float32)


class _SpaceIndex:
    def __init__(self, space: str, dim: int, db: LibraryDB, path: Path):
        self.space = space
        self.dim = dim
        self.db = db
        self.path = path
        self.lock = threading.RLock()
        self.index: Optional[faiss.Index] = None
        self.kind = "flat"
        self.dirty = False
        self.rebuilding = False
        self.max_id = 0          # highest vector id contained in the index
        self.tomb_mark = 0       # tombstone rowid watermark seen at the previous checkpoint

    # ── construction ─────────────────────────────────────────────────────────
    def _new_flat(self) -> faiss.Index:
        base = faiss.IndexScalarQuantizer(self.dim, faiss.ScalarQuantizer.QT_fp16, faiss.METRIC_INNER_PRODUCT)
        return faiss.IndexIDMap2(base)

    def _iter_rows(self, after_id: int = 0) -> Iterable[Tuple[np.ndarray, np.ndarray]]:
        last = after_id
        while True:
            rows = self.db.all(
                "SELECT id, emb FROM vectors WHERE space = ? AND id > ? ORDER BY id LIMIT ?",
                (self.space, last, _BATCH),
            )
            if not rows:
                return
            ids = np.array([r["id"] for r in rows], dtype=np.int64)
            vecs = np.stack([decode(r["emb"]) for r in rows])
            last = int(ids[-1])
            yield ids, vecs

    def _count_rows(self) -> int:
        return int(self.db.scalar("SELECT COUNT(*) FROM vectors WHERE space = ?", (self.space,), 0))

    def _build_ivfpq(self, n: int) -> faiss.Index:
        nlist = max(64, int(4 * math.sqrt(n)))
        m = 64 if self.dim % 64 == 0 else 32
        quantizer = faiss.IndexFlatIP(self.dim)
        index = faiss.IndexIVFPQ(quantizer, self.dim, nlist, m, 8, faiss.METRIC_INNER_PRODUCT)
        sample_size = min(n, max(nlist * 40, 50000))
        rows = self.db.all(
            "SELECT emb FROM vectors WHERE space = ? ORDER BY RANDOM() LIMIT ?",
            (self.space, sample_size),
        )
        train = _normalized(np.stack([decode(r["emb"]) for r in rows]))
        index.train(train)
        index.nprobe = min(64, max(16, nlist // 32))
        return index

    def rebuild(self) -> None:
        """Rebuild this space's index from SQLite (picks the tier by size)."""
        n = self._count_rows()
        kind = "ivfpq" if n >= IVF_THRESHOLD else "flat"
        index = self._build_ivfpq(n) if kind == "ivfpq" else self._new_flat()
        max_id = 0
        for ids, vecs in self._iter_rows():
            index.add_with_ids(_normalized(vecs), ids)
            max_id = int(ids[-1])
        with self.lock:
            # Replay anything added while we were building
            for ids, vecs in self._iter_rows(after_id=max_id):
                index.add_with_ids(_normalized(vecs), ids)
                max_id = int(ids[-1])
            self.index = index
            self.kind = kind
            self.max_id = max(self.max_id, max_id)
            self.dirty = True
        self.checkpoint()

    def load(self) -> None:
        state = self.db.one("SELECT checkpoint_max_id, index_kind, dim FROM vector_state WHERE space = ?", (self.space,))
        loaded = None
        if state and self.path.exists() and int(state.get("dim") or self.dim) == self.dim:
            try:
                data = np.frombuffer(self.path.read_bytes(), dtype=np.uint8)
                loaded = faiss.deserialize_index(data)
                if loaded.d != self.dim:
                    loaded = None
            except Exception as e:
                print(f"[VectorStore] Could not read {self.path.name} ({e}); rebuilding from SQLite")
                loaded = None
        if loaded is None:
            if self._count_rows() == 0:
                with self.lock:
                    self.index = self._new_flat()
                    self.kind = "flat"
                return
            self.rebuild()
            return

        checkpoint_id = int(state["checkpoint_max_id"] or 0)
        with self.lock:
            self.index = loaded
            self.kind = state.get("index_kind") or "flat"
            self.max_id = checkpoint_id
            replayed = 0
            for ids, vecs in self._iter_rows(after_id=checkpoint_id):
                self.index.add_with_ids(_normalized(vecs), ids)
                replayed += len(ids)
                self.max_id = int(ids[-1])
            tomb_rows = self.db.all(
                "SELECT rowid AS rid, vec_id FROM vector_tombstones WHERE space = ?", (self.space,)
            )
            if tomb_rows:
                self.index.remove_ids(np.array([r["vec_id"] for r in tomb_rows], dtype=np.int64))
                self.tomb_mark = max(int(r["rid"]) for r in tomb_rows)
            if replayed or tomb_rows:
                self.dirty = True

    # ── persistence ──────────────────────────────────────────────────────────
    def checkpoint(self) -> bool:
        with self.lock:
            if self.index is None:
                return False
            if not self.dirty:
                clean_mark = self.tomb_mark
            else:
                clean_mark = None
        if clean_mark is not None:
            # Nothing changed since the last save, so it reflects every tombstone seen then
            if clean_mark:
                with self.db.write() as c:
                    c.execute("DELETE FROM vector_tombstones WHERE space = ? AND rowid <= ?", (self.space, clean_mark))
            return False
        with self.lock:
            prev_mark = self.tomb_mark
            self.tomb_mark = int(self.db.scalar(
                "SELECT COALESCE(MAX(rowid), 0) FROM vector_tombstones WHERE space = ?", (self.space,), 0
            ) or 0)
            data = faiss.serialize_index(self.index)
            max_id = self.max_id
            kind = self.kind
            self.dirty = False
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_bytes(data.tobytes())
        os.replace(tmp, self.path)
        with self.db.write() as c:
            c.execute(
                """INSERT INTO vector_state (space, checkpoint_max_id, index_kind, dim)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(space) DO UPDATE SET checkpoint_max_id = excluded.checkpoint_max_id,
                       index_kind = excluded.index_kind, dim = excluded.dim""",
                (self.space, max_id, kind, self.dim),
            )
            # Removals seen at the previous checkpoint were applied long before this save
            c.execute("DELETE FROM vector_tombstones WHERE space = ? AND rowid <= ?", (self.space, prev_mark))
        return True

    # ── mutation ─────────────────────────────────────────────────────────────
    def add(self, ids: np.ndarray, vecs: np.ndarray) -> None:
        if len(ids) == 0:
            return
        with self.lock:
            if self.index is None:
                self.index = self._new_flat()
            ids = np.asarray(ids, dtype=np.int64)
            self.index.add_with_ids(_normalized(vecs), ids)
            self.max_id = max(self.max_id, int(ids.max()))
            self.dirty = True

    def remove(self, ids: Sequence[int]) -> None:
        if not ids:
            return
        with self.lock:
            if self.index is not None:
                self.index.remove_ids(np.array(list(ids), dtype=np.int64))
                self.dirty = True

    @property
    def ntotal(self) -> int:
        with self.lock:
            return int(self.index.ntotal) if self.index is not None else 0

    # ── search ───────────────────────────────────────────────────────────────
    def _exact(self, q: np.ndarray, ids: Sequence[int], k: int) -> List[Tuple[int, float]]:
        out: List[Tuple[int, float]] = []
        id_list = list(ids)
        for i in range(0, len(id_list), 900):
            part = id_list[i:i + 900]
            ph = ",".join("?" * len(part))
            rows = self.db.all(f"SELECT id, emb FROM vectors WHERE id IN ({ph})", part)
            if not rows:
                continue
            mat = np.stack([decode(r["emb"]) for r in rows])
            scores = mat @ q
            out.extend((int(r["id"]), float(s)) for r, s in zip(rows, scores))
        out.sort(key=lambda x: x[1], reverse=True)
        return out[:k]

    def search(self, query: Sequence[float], k: int, allowed_ids: Optional[Sequence[int]] = None) -> List[Tuple[int, float]]:
        q = _normalized(np.asarray(query, dtype=np.float32))[0]
        if q.shape[0] != self.dim:
            return []
        if allowed_ids is not None:
            if not allowed_ids:
                return []
            if len(allowed_ids) <= EXACT_SUBSET_LIMIT:
                return self._exact(q, allowed_ids, k)
        with self.lock:
            if self.index is None or self.index.ntotal == 0:
                return []
            fetch = min(self.index.ntotal, k * RERANK_FACTOR if self.kind == "ivfpq" else k)
            params = None
            if allowed_ids is not None:
                sel = faiss.IDSelectorBatch(np.array(list(allowed_ids), dtype=np.int64))
                if self.kind == "ivfpq":
                    # SearchParametersIVF defaults to nprobe=1, which would override the index setting
                    params = faiss.SearchParametersIVF(sel=sel, nprobe=faiss.extract_index_ivf(self.index).nprobe)
                else:
                    params = faiss.SearchParameters(sel=sel)
            if params is not None:
                scores, ids = self.index.search(q[None, :], fetch, params=params)
            else:
                scores, ids = self.index.search(q[None, :], fetch)
        hits = [(int(i), float(s)) for i, s in zip(ids[0], scores[0]) if i >= 0]
        if self.kind == "ivfpq" and hits:
            # PQ scores are approximate: re-score candidates exactly from SQLite
            return self._exact(q, [i for i, _ in hits], k)
        return hits[:k]


class VectorStore:
    def __init__(self, db: LibraryDB, vectors_dir: Path):
        self.db = db
        self.dir = Path(vectors_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.spaces: Dict[str, _SpaceIndex] = {
            name: _SpaceIndex(name, dim, db, self.dir / f"{name}.faiss") for name, dim in SPACE_DIMS.items()
        }
        for s in self.spaces.values():
            s.load()

    # ── writes (two-phase: rows inside the caller's transaction, index after commit) ──
    @staticmethod
    def insert_rows(conn, space: str, rows: Sequence[Tuple[int, str, Sequence[float]]]) -> List[int]:
        """Insert (entity_id, source_id, vector) rows; returns vector ids. Call inside db.write()."""
        ids = []
        for entity_id, source_id, vec in rows:
            cur = conn.execute(
                "INSERT INTO vectors (space, entity_id, source_id, emb) VALUES (?, ?, ?, ?)",
                (space, int(entity_id), source_id, encode(vec)),
            )
            ids.append(int(cur.lastrowid))
        return ids

    def index_rows(self, space: str, ids: Sequence[int], vecs: Sequence[Sequence[float]]) -> None:
        """Add committed rows to the FAISS index (after the transaction commits)."""
        if ids:
            self.spaces[space].add(np.asarray(ids, dtype=np.int64), np.asarray(vecs, dtype=np.float32))
            self._maybe_upgrade(space)

    def collect_source(self, conn, source_id: str) -> Dict[str, List[int]]:
        """Delete a source's vector rows and record tombstones. Call inside db.write()."""
        by_space: Dict[str, List[int]] = {}
        for r in conn.execute("SELECT id, space FROM vectors WHERE source_id = ?", (source_id,)).fetchall():
            by_space.setdefault(r["space"], []).append(int(r["id"]))
        if by_space:
            # Tombstones for every id (also ones newer than the last save: a checkpoint may be
            # serializing them right now); removing an id the saved index lacks is a no-op.
            for space, ids in by_space.items():
                conn.executemany(
                    "INSERT OR IGNORE INTO vector_tombstones (space, vec_id) VALUES (?, ?)",
                    [(space, i) for i in ids],
                )
            conn.execute("DELETE FROM vectors WHERE source_id = ?", (source_id,))
        return by_space

    def collect_entities(self, conn, space: str, entity_ids: Sequence[int]) -> Dict[str, List[int]]:
        """Delete the vectors of specific entities (e.g. some chunks). Call inside db.write()."""
        vec_ids: List[int] = []
        ids = list(entity_ids)
        for i in range(0, len(ids), 900):
            part = ids[i:i + 900]
            ph = ",".join("?" * len(part))
            vec_ids.extend(int(r["id"]) for r in conn.execute(
                f"SELECT id FROM vectors WHERE space = ? AND entity_id IN ({ph})", [space, *part]
            ).fetchall())
        if vec_ids:
            conn.executemany("INSERT OR IGNORE INTO vector_tombstones (space, vec_id) VALUES (?, ?)",
                             [(space, v) for v in vec_ids])
            for i in range(0, len(vec_ids), 900):
                part = vec_ids[i:i + 900]
                conn.execute(f"DELETE FROM vectors WHERE id IN ({','.join('?' * len(part))})", part)
        return {space: vec_ids} if vec_ids else {}

    def unindex(self, by_space: Dict[str, List[int]]) -> None:
        for space, ids in by_space.items():
            if space in self.spaces:
                self.spaces[space].remove(ids)

    def add(self, space: str, rows: Sequence[Tuple[int, str, Sequence[float]]]) -> List[int]:
        """Convenience: insert rows in their own transaction and index them."""
        with self.db.write() as c:
            ids = self.insert_rows(c, space, rows)
        self.index_rows(space, ids, [r[2] for r in rows])
        return ids

    def remove_source(self, source_id: str) -> None:
        with self.db.write() as c:
            by_space = self.collect_source(c, source_id)
        self.unindex(by_space)

    # ── which model made a space's vectors ────────────────────────────────────
    def space_model(self, space: str) -> Optional[str]:
        return self.db.scalar("SELECT model FROM vector_state WHERE space = ?", (space,))

    def reset_space(self, space: str, model: str) -> int:
        """
        Drop every vector of one space (rows, tombstones and saved index) and record the
        model its new vectors come from, in one transaction. Returns how many were dropped.
        """
        idx = self.spaces[space]
        with idx.lock:
            # First: interrupted anywhere after this, the index is rebuilt from SQLite on load
            idx.path.unlink(missing_ok=True)
            with self.db.write() as c:
                n = c.execute("DELETE FROM vectors WHERE space = ?", (space,)).rowcount
                c.execute("DELETE FROM vector_tombstones WHERE space = ?", (space,))
                # checkpoint() never touches the model column
                c.execute(
                    """INSERT INTO vector_state (space, checkpoint_max_id, index_kind, dim, model) VALUES (?, 0, 'flat', ?, ?)
                       ON CONFLICT(space) DO UPDATE SET checkpoint_max_id = 0, model = excluded.model""",
                    (space, idx.dim, model),
                )
            idx.index = idx._new_flat()
            idx.kind = "flat"
            idx.max_id = 0
            idx.tomb_mark = 0
            idx.dirty = True
        idx.checkpoint()
        return n

    # ── search ───────────────────────────────────────────────────────────────
    def search(self, space: str, query: Sequence[float], k: int, allowed_ids: Optional[Sequence[int]] = None) -> List[Tuple[int, float]]:
        if space not in self.spaces or query is None:
            return []
        return self.spaces[space].search(query, k, allowed_ids)

    # ── maintenance ──────────────────────────────────────────────────────────
    def _maybe_upgrade(self, space: str) -> None:
        idx = self.spaces[space]
        if idx.kind == "flat" and idx.ntotal >= IVF_THRESHOLD and not idx.rebuilding:
            idx.rebuilding = True

            def _run():
                try:
                    print(f"[VectorStore] {space}: {idx.ntotal} vectors — switching to IVF-PQ")
                    t0 = time.time()
                    idx.rebuild()
                    print(f"[VectorStore] {space}: IVF-PQ ready in {time.time() - t0:.1f}s")
                finally:
                    idx.rebuilding = False

            threading.Thread(target=_run, name=f"ivf-upgrade-{space}", daemon=True).start()

    def checkpoint(self) -> None:
        for s in self.spaces.values():
            try:
                s.checkpoint()
            except Exception as e:
                print(f"[VectorStore] Checkpoint failed for {s.space}: {e}")

    def stats(self) -> Dict[str, Dict[str, object]]:
        return {name: {"vectors": s.ntotal, "index": s.kind} for name, s in self.spaces.items()}
