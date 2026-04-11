"""Vector store — embedding storage with FAISS or numpy fallback."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

try:
    import faiss

    _FAISS_AVAILABLE = True
except ImportError:
    _FAISS_AVAILABLE = False


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two vectors."""
    dot = float(np.dot(a, b))
    norm_a = float(np.linalg.norm(a))
    norm_b = float(np.linalg.norm(b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class VectorStore:
    """Embedding vector store with FAISS acceleration or numpy fallback.

    Stores vectors keyed by string IDs. Supports add, search (top-k by
    cosine similarity), remove, and persistence to disk.
    """

    def __init__(self, dimension: int = 0, storage_path: str | Path | None = None) -> None:
        self._dimension = dimension
        self._storage_path = Path(storage_path) if storage_path else None
        self._ids: list[str] = []
        self._vectors: list[np.ndarray] = []
        self._index: Any | None = None  # FAISS index when available
        self._use_faiss = _FAISS_AVAILABLE

        if self._storage_path:
            meta_path = self._storage_path.with_suffix(".json")
            if meta_path.exists():
                self._load()

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def count(self) -> int:
        return len(self._ids)

    @property
    def using_faiss(self) -> bool:
        return self._use_faiss and self._index is not None

    def _build_faiss_index(self) -> None:
        """Build or rebuild FAISS index from stored vectors."""
        if not self._use_faiss or self._dimension == 0 or not self._vectors:
            return
        # Inner product on L2-normalized vectors = cosine similarity
        self._index = faiss.IndexFlatIP(self._dimension)
        matrix = np.array(self._vectors, dtype=np.float32)
        # L2 normalize
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        matrix = matrix / norms
        self._index.add(matrix)

    def add(self, vector_id: str, vector: list[float] | np.ndarray) -> None:
        """Add a vector with an associated ID."""
        vec = np.array(vector, dtype=np.float32)
        if self._dimension == 0:
            self._dimension = len(vec)
        elif len(vec) != self._dimension:
            raise ValueError(
                f"Vector dimension {len(vec)} does not match store dimension {self._dimension}"
            )

        # Replace if ID already exists
        if vector_id in self._ids:
            idx = self._ids.index(vector_id)
            self._vectors[idx] = vec
            # Rebuild FAISS index (it doesn't support in-place update)
            self._build_faiss_index()
        else:
            self._ids.append(vector_id)
            self._vectors.append(vec)
            # Add to FAISS index incrementally
            if self._use_faiss and self._index is not None:
                norm = float(np.linalg.norm(vec))
                normalized = (vec / norm).reshape(1, -1) if norm > 0 else vec.reshape(1, -1)
                self._index.add(normalized)
            elif self._use_faiss and len(self._vectors) >= 1:
                self._build_faiss_index()

    def search(
        self,
        query: list[float] | np.ndarray,
        top_k: int = 5,
        threshold: float = 0.0,
    ) -> list[tuple[str, float]]:
        """Find the top-k most similar vectors by cosine similarity.

        Returns list of (id, score) tuples sorted by descending similarity.
        """
        if not self._vectors:
            return []

        query_vec = np.array(query, dtype=np.float32)

        if self.using_faiss:
            return self._search_faiss(query_vec, top_k, threshold)
        return self._search_numpy(query_vec, top_k, threshold)

    def _search_faiss(
        self, query: np.ndarray, top_k: int, threshold: float
    ) -> list[tuple[str, float]]:
        """FAISS-accelerated search."""
        norm = float(np.linalg.norm(query))
        if norm == 0:
            return []
        normalized = (query / norm).reshape(1, -1)

        k = min(top_k, len(self._ids))
        distances, indices = self._index.search(normalized, k)

        results = []
        for score, idx in zip(distances[0], indices[0], strict=False):
            if idx < 0 or idx >= len(self._ids):
                continue
            if score >= threshold:
                results.append((self._ids[idx], float(score)))
        return results

    def _search_numpy(
        self, query: np.ndarray, top_k: int, threshold: float
    ) -> list[tuple[str, float]]:
        """Numpy fallback search using cosine similarity."""
        results = []
        for i, vec in enumerate(self._vectors):
            score = _cosine_similarity(query, vec)
            if score >= threshold:
                results.append((self._ids[i], score))
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    def remove(self, vector_id: str) -> bool:
        """Remove a vector by ID. Returns True if found and removed."""
        if vector_id not in self._ids:
            return False
        idx = self._ids.index(vector_id)
        self._ids.pop(idx)
        self._vectors.pop(idx)
        # Rebuild FAISS index (doesn't support removal)
        if self._use_faiss and self._vectors:
            self._build_faiss_index()
        elif self._use_faiss:
            self._index = None
        return True

    def get_vector(self, vector_id: str) -> np.ndarray | None:
        """Get a vector by ID."""
        if vector_id not in self._ids:
            return None
        idx = self._ids.index(vector_id)
        return self._vectors[idx]

    def save(self, path: str | Path | None = None) -> Path:
        """Persist vectors and IDs to disk."""
        save_path = Path(path) if path else self._storage_path
        if save_path is None:
            raise ValueError("No storage path specified")
        save_path.parent.mkdir(parents=True, exist_ok=True)

        # Save as .npz for vectors + .json for IDs/metadata
        vectors_path = save_path.with_suffix(".npz")
        meta_path = save_path.with_suffix(".json")

        if self._vectors:
            np.savez_compressed(vectors_path, vectors=np.array(self._vectors, dtype=np.float32))
        elif vectors_path.exists():
            vectors_path.unlink()

        meta = {"ids": self._ids, "dimension": self._dimension}
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
        return save_path

    def _load(self) -> None:
        """Load vectors and IDs from disk."""
        if self._storage_path is None:
            return

        meta_path = self._storage_path.with_suffix(".json")
        vectors_path = self._storage_path.with_suffix(".npz")

        if not meta_path.exists():
            return

        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        self._ids = meta.get("ids", [])
        self._dimension = meta.get("dimension", 0)

        if vectors_path.exists():
            data = np.load(vectors_path)
            self._vectors = [data["vectors"][i] for i in range(len(data["vectors"]))]
        else:
            self._vectors = []

        if self._vectors:
            self._build_faiss_index()

    def clear(self) -> int:
        """Remove all vectors. Returns count of removed vectors."""
        count = len(self._ids)
        self._ids.clear()
        self._vectors.clear()
        self._index = None
        return count
