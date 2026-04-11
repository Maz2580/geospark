"""Spatial intelligence — enhanced memory with facts, episodes, contradictions, and auto-linking."""
from __future__ import annotations

import enum
import json
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, Field

from geospark.memory.vector_store import VectorStore

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class MemoryAction(str, enum.Enum):
    """Actions the update pipeline can take on a candidate memory."""

    ADD = "add"
    UPDATE = "update"
    REPLACE = "replace"
    DELETE = "delete"
    NOOP = "noop"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class SpatialFact(BaseModel):
    """Persistent spatial knowledge — time-agnostic truths.

    Examples: "The Eiffel Tower is at 48.8566°N, 2.2944°E",
              "Melbourne CBD uses EPSG:32755",
              "User's farm covers 420 hectares".
    """

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    content: str
    source: str = ""  # Where the fact came from (tool, user, agent)
    confidence: float = 1.0  # 0.0-1.0
    geometry: dict[str, Any] | None = None
    tags: list[str] = []
    connections: list[str] = []  # IDs of related facts/episodes
    is_active: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SpatialEpisode(BaseModel):
    """Timestamped spatial observation — events anchored in time.

    Examples: "PM2.5 was 42 µg/m³ in Delhi on 2026-04-09",
              "3 active fires detected near California on 2026-04-08",
              "Temperature was 28°C at Federation Square at 14:00".
    """

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    content: str
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = ""
    importance: float = 0.5  # 0.0-1.0, higher = more significant
    session_id: str = ""
    geometry: dict[str, Any] | None = None
    tags: list[str] = []
    connections: list[str] = []
    is_active: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MemoryConnection(BaseModel):
    """Bidirectional link between two memories."""

    source_id: str
    target_id: str
    similarity: float = 0.0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Contradiction(BaseModel):
    """A detected contradiction between two spatial facts."""

    fact_a_id: str
    fact_a_content: str
    fact_b_id: str
    fact_b_content: str
    similarity: float = 0.0
    detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class IntelligenceStats(BaseModel):
    """Statistics about the spatial intelligence store."""

    total_facts: int = 0
    active_facts: int = 0
    total_episodes: int = 0
    active_episodes: int = 0
    total_connections: int = 0
    contradictions_found: int = 0
    vector_store_count: int = 0
    using_faiss: bool = False


# ---------------------------------------------------------------------------
# Embedding helpers
# ---------------------------------------------------------------------------


def _get_embedding(
    text: str,
    ollama_url: str = "http://localhost:11434",
    model: str = "qwen2.5:7b",
) -> list[float] | None:
    """Get embedding vector from Ollama. Returns None on failure."""
    try:
        resp = httpx.post(
            f"{ollama_url}/api/embed",
            json={"model": model, "input": text},
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json()["embeddings"][0]
    except Exception:
        return None


def _word_overlap_score(query: str, content: str) -> float:
    """Simple word overlap similarity as fallback for embeddings."""
    q_words = set(query.lower().split())
    c_words = set(content.lower().split())
    if not q_words:
        return 0.0
    overlap = len(q_words & c_words)
    if overlap == 0:
        return 0.0
    # Exact substring bonus
    if query.lower() in content.lower():
        return 0.9
    return min(overlap / len(q_words), 0.8)


# ---------------------------------------------------------------------------
# SpatialIntelligence
# ---------------------------------------------------------------------------


class SpatialIntelligence:
    """Enhanced spatial memory with embeddings, contradictions, and auto-linking.

    Inspired by context-memory (dual memory + LLM-driven update),
    ReMe (compaction), and OpenViking (tiered retrieval).

    Features:
    - Dual memory: facts (timeless knowledge) + episodes (timestamped events)
    - Embedding-based recall via VectorStore (FAISS or numpy)
    - Contradiction detection between conflicting facts
    - Auto-linking of related memories (cosine similarity > threshold)
    - Memory compaction: summarize old episodes, preserve key facts
    """

    LINK_THRESHOLD = 0.6  # Minimum similarity for auto-linking

    def __init__(
        self,
        storage_dir: str | Path | None = None,
        ollama_url: str | None = None,
        embed_model: str | None = None,
    ) -> None:
        if storage_dir is None:
            storage_dir = Path.home() / ".geospark" / "intelligence"
        self._storage_dir = Path(storage_dir)
        self._storage_dir.mkdir(parents=True, exist_ok=True)

        self._ollama_url = ollama_url or "http://localhost:11434"
        self._embed_model = embed_model or "qwen2.5:7b"
        self._embedding_available: bool | None = None

        # Data stores
        self._facts: list[SpatialFact] = []
        self._episodes: list[SpatialEpisode] = []
        self._connections: list[MemoryConnection] = []

        # Vector store for embedding-based search
        self._vector_store = VectorStore(
            storage_path=self._storage_dir / "vectors"
        )

        self._load()

    # -------------------------------------------------------------------
    # Embedding availability
    # -------------------------------------------------------------------

    def _check_embedding(self) -> bool:
        """Check if Ollama embedding is reachable (cached after first check)."""
        if self._embedding_available is not None:
            return self._embedding_available
        emb = _get_embedding("test", self._ollama_url, self._embed_model)
        self._embedding_available = emb is not None
        return self._embedding_available

    def _embed(self, text: str) -> list[float] | None:
        """Get embedding for text, or None if unavailable."""
        if not self._check_embedding():
            return None
        return _get_embedding(text, self._ollama_url, self._embed_model)

    # -------------------------------------------------------------------
    # Remember
    # -------------------------------------------------------------------

    def remember_fact(
        self,
        content: str,
        source: str = "",
        confidence: float = 1.0,
        geometry: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> SpatialFact:
        """Store a new spatial fact."""
        fact = SpatialFact(
            content=content,
            source=source,
            confidence=confidence,
            geometry=geometry,
            tags=tags or [],
        )
        self._facts.append(fact)

        # Embed and index
        emb = self._embed(content)
        if emb:
            self._vector_store.add(f"fact:{fact.id}", emb)

        # Auto-link
        self._auto_link(fact.id, content, is_fact=True)

        self._save()
        return fact

    def remember_episode(
        self,
        content: str,
        occurred_at: datetime | None = None,
        source: str = "",
        importance: float = 0.5,
        session_id: str = "",
        geometry: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> SpatialEpisode:
        """Store a timestamped spatial observation."""
        episode = SpatialEpisode(
            content=content,
            occurred_at=occurred_at or datetime.now(timezone.utc),
            source=source,
            importance=importance,
            session_id=session_id,
            geometry=geometry,
            tags=tags or [],
        )
        self._episodes.append(episode)

        # Embed and index
        emb = self._embed(content)
        if emb:
            self._vector_store.add(f"episode:{episode.id}", emb)

        # Auto-link
        self._auto_link(episode.id, content, is_fact=False)

        self._save()
        return episode

    # -------------------------------------------------------------------
    # Recall
    # -------------------------------------------------------------------

    def recall(
        self,
        query: str,
        limit: int = 10,
        include_inactive: bool = False,
        memory_type: str | None = None,  # "fact", "episode", or None for both
    ) -> list[dict[str, Any]]:
        """Retrieve relevant memories using embedding similarity + recency.

        Returns a list of dicts with keys: id, type, content, score,
        source, connections, created_at, and type-specific fields.
        """
        results: list[tuple[float, dict[str, Any]]] = []

        # Try embedding-based search first
        emb = self._embed(query)
        embedding_scores: dict[str, float] = {}
        if emb:
            matches = self._vector_store.search(emb, top_k=limit * 3, threshold=0.1)
            embedding_scores = {vid: score for vid, score in matches}

        # Score all memories
        now = datetime.now(timezone.utc)

        if memory_type != "episode":
            for fact in self._facts:
                if not include_inactive and not fact.is_active:
                    continue
                score = self._score_memory(
                    f"fact:{fact.id}", fact.content, query, fact.created_at,
                    now, embedding_scores,
                )
                if score > 0.01:
                    results.append((score, {
                        "id": fact.id,
                        "type": "fact",
                        "content": fact.content,
                        "score": round(score, 4),
                        "source": fact.source,
                        "confidence": fact.confidence,
                        "geometry": fact.geometry,
                        "tags": fact.tags,
                        "connections": fact.connections,
                        "is_active": fact.is_active,
                        "created_at": fact.created_at.isoformat(),
                    }))

        if memory_type != "fact":
            for ep in self._episodes:
                if not include_inactive and not ep.is_active:
                    continue
                score = self._score_memory(
                    f"episode:{ep.id}", ep.content, query, ep.created_at,
                    now, embedding_scores, importance=ep.importance,
                )
                if score > 0.01:
                    results.append((score, {
                        "id": ep.id,
                        "type": "episode",
                        "content": ep.content,
                        "score": round(score, 4),
                        "source": ep.source,
                        "importance": ep.importance,
                        "occurred_at": ep.occurred_at.isoformat(),
                        "geometry": ep.geometry,
                        "tags": ep.tags,
                        "connections": ep.connections,
                        "is_active": ep.is_active,
                        "created_at": ep.created_at.isoformat(),
                    }))

        results.sort(key=lambda x: x[0], reverse=True)
        return [r[1] for r in results[:limit]]

    def _score_memory(
        self,
        vector_id: str,
        content: str,
        query: str,
        created_at: datetime,
        now: datetime,
        embedding_scores: dict[str, float],
        importance: float = 1.0,
    ) -> float:
        """Combined score: similarity * importance * recency.

        Weights: 60% similarity + 20% recency + 20% importance.
        """
        # Similarity: prefer embedding, fall back to word overlap
        if vector_id in embedding_scores:
            similarity = embedding_scores[vector_id]
        else:
            similarity = _word_overlap_score(query, content)

        if similarity < 0.01:
            return 0.0

        # Recency: exponential decay over 90 days
        age_days = (now - created_at).total_seconds() / 86400
        recency = math.exp(-0.01 * age_days)  # half-life ≈ 69 days

        return similarity * 0.6 + recency * 0.2 + importance * 0.2

    # -------------------------------------------------------------------
    # Auto-linking
    # -------------------------------------------------------------------

    def _auto_link(self, memory_id: str, content: str, is_fact: bool) -> None:
        """Find and create bidirectional links to related memories."""
        emb = self._embed(content)
        if not emb:
            return

        prefix = "fact:" if is_fact else "episode:"
        vector_id = f"{prefix}{memory_id}"

        matches = self._vector_store.search(emb, top_k=6, threshold=self.LINK_THRESHOLD)
        for match_vid, score in matches:
            if match_vid == vector_id:
                continue
            # Extract target ID
            target_id = match_vid.split(":", 1)[1] if ":" in match_vid else match_vid

            # Avoid duplicate connections
            exists = any(
                (c.source_id == memory_id and c.target_id == target_id)
                or (c.source_id == target_id and c.target_id == memory_id)
                for c in self._connections
            )
            if exists:
                continue

            # Create bidirectional connection
            conn = MemoryConnection(
                source_id=memory_id,
                target_id=target_id,
                similarity=score,
            )
            self._connections.append(conn)

            # Update connection lists on both memories
            self._add_connection_to_memory(memory_id, target_id)
            self._add_connection_to_memory(target_id, memory_id)

    def _add_connection_to_memory(self, memory_id: str, connected_id: str) -> None:
        """Add a connection ID to a fact or episode's connection list."""
        for f in self._facts:
            if f.id == memory_id and connected_id not in f.connections:
                f.connections.append(connected_id)
                return
        for e in self._episodes:
            if e.id == memory_id and connected_id not in e.connections:
                e.connections.append(connected_id)
                return

    # -------------------------------------------------------------------
    # Contradiction detection
    # -------------------------------------------------------------------

    def find_contradictions(self, threshold: float = 0.7) -> list[Contradiction]:
        """Find potentially contradicting active facts.

        Two facts are contradictory if they are highly similar (above
        threshold) but not identical — meaning they likely describe the
        same entity with different values.

        Strategy: high similarity + different content = likely contradiction.
        """
        contradictions: list[Contradiction] = []
        active_facts = [f for f in self._facts if f.is_active]

        for i, fa in enumerate(active_facts):
            for fb in active_facts[i + 1:]:
                # Skip if identical content
                if fa.content.strip() == fb.content.strip():
                    continue

                # Check similarity
                sim = self._similarity_between(fa.id, fa.content, fb.id, fb.content)
                if sim >= threshold:
                    contradictions.append(Contradiction(
                        fact_a_id=fa.id,
                        fact_a_content=fa.content,
                        fact_b_id=fb.id,
                        fact_b_content=fb.content,
                        similarity=round(sim, 4),
                    ))

        return contradictions

    def _similarity_between(
        self, id_a: str, content_a: str, id_b: str, content_b: str
    ) -> float:
        """Compute similarity between two memories."""
        vec_a = self._vector_store.get_vector(f"fact:{id_a}")
        vec_b = self._vector_store.get_vector(f"fact:{id_b}")
        if vec_a is not None and vec_b is not None:
            from geospark.memory.vector_store import _cosine_similarity
            return _cosine_similarity(vec_a, vec_b)
        return _word_overlap_score(content_a, content_b)

    def resolve_contradiction(
        self, keep_id: str, remove_id: str
    ) -> bool:
        """Resolve a contradiction by keeping one fact and deactivating the other."""
        for f in self._facts:
            if f.id == remove_id:
                f.is_active = False
                f.updated_at = datetime.now(timezone.utc)
                self._save()
                return True
        return False

    # -------------------------------------------------------------------
    # Update pipeline (ADD / UPDATE / REPLACE / DELETE / NOOP)
    # -------------------------------------------------------------------

    def update_memory(
        self,
        candidate_content: str,
        action: MemoryAction,
        target_id: str | None = None,
        source: str = "",
    ) -> dict[str, Any]:
        """Execute a memory update action.

        Args:
            candidate_content: The new content to process.
            action: The action to take (ADD, UPDATE, REPLACE, DELETE, NOOP).
            target_id: The ID of the existing memory to update/replace/delete.
            source: Source attribution.

        Returns:
            Dict with action taken and affected memory ID.
        """
        if action == MemoryAction.ADD:
            fact = self.remember_fact(candidate_content, source=source)
            return {"action": "add", "id": fact.id, "content": fact.content}

        if action == MemoryAction.UPDATE and target_id:
            for f in self._facts:
                if f.id == target_id and f.is_active:
                    f.content = candidate_content
                    f.updated_at = datetime.now(timezone.utc)
                    f.source = source or f.source
                    # Re-embed
                    emb = self._embed(candidate_content)
                    if emb:
                        self._vector_store.add(f"fact:{f.id}", emb)
                    self._save()
                    return {"action": "update", "id": f.id, "content": f.content}
            return {"action": "noop", "reason": "target not found"}

        if action == MemoryAction.REPLACE and target_id:
            # Deactivate old, create new
            for f in self._facts:
                if f.id == target_id:
                    f.is_active = False
                    f.updated_at = datetime.now(timezone.utc)
                    break
            new_fact = self.remember_fact(candidate_content, source=source)
            return {
                "action": "replace",
                "removed_id": target_id,
                "new_id": new_fact.id,
                "content": new_fact.content,
            }

        if action == MemoryAction.DELETE and target_id:
            for f in self._facts:
                if f.id == target_id:
                    f.is_active = False
                    f.updated_at = datetime.now(timezone.utc)
                    self._vector_store.remove(f"fact:{f.id}")
                    self._save()
                    return {"action": "delete", "id": target_id}
            return {"action": "noop", "reason": "target not found"}

        return {"action": "noop", "reason": "no action needed"}

    # -------------------------------------------------------------------
    # Extract from tool results
    # -------------------------------------------------------------------

    def extract_from_result(
        self,
        tool_name: str,
        result: dict[str, Any],
        session_id: str = "",
    ) -> list[dict[str, Any]]:
        """Parse a tool result into facts and episodes.

        Uses rule-based extraction (no LLM needed). Extracts location
        facts and timestamped observations from common tool result shapes.
        """
        extracted: list[dict[str, Any]] = []

        # Geocoding results → facts
        if tool_name in ("geocode", "reverse_geocode"):
            features = result.get("features", [])
            for f in features[:3]:
                props = f.get("properties", {})
                coords = f.get("geometry", {}).get("coordinates", [])
                if props.get("display_name") and len(coords) >= 2:
                    content = (
                        f"{props['display_name']} is located at "
                        f"{coords[1]:.6f}°N, {coords[0]:.6f}°E"
                    )
                    fact = self.remember_fact(
                        content,
                        source=f"tool:{tool_name}",
                        geometry=f.get("geometry"),
                        tags=["location", "geocoded"],
                    )
                    extracted.append({"type": "fact", "id": fact.id, "content": content})

        # Weather results → episodes
        elif tool_name == "weather":
            features = result.get("features", [])
            for f in features:
                if f.get("type") == "current_weather":
                    content = (
                        f"Weather at {f.get('location', '?')}: "
                        f"{f.get('temperature_c', '?')}°C, "
                        f"{f.get('weather_description', '?')}, "
                        f"humidity {f.get('humidity_pct', '?')}%"
                    )
                    ep = self.remember_episode(
                        content,
                        source=f"tool:{tool_name}",
                        importance=0.4,
                        session_id=session_id,
                        tags=["weather", "conditions"],
                    )
                    extracted.append({"type": "episode", "id": ep.id, "content": content})

        # Air quality → episodes
        elif tool_name == "air_quality":
            features = result.get("features", [])
            for f in features[:3]:
                m = f.get("measurements", {})
                pm25 = m.get("pm25", {}).get("value")
                if pm25 is not None:
                    content = (
                        f"Air quality at {f.get('station_name', '?')}: "
                        f"PM2.5 = {pm25} µg/m³, "
                        f"category: {f.get('aqi_category', '?')}"
                    )
                    ep = self.remember_episode(
                        content,
                        source=f"tool:{tool_name}",
                        importance=0.6,
                        session_id=session_id,
                        geometry={"type": "Point", "coordinates": f.get("coordinates", [])},
                        tags=["air_quality", "pollution"],
                    )
                    extracted.append({"type": "episode", "id": ep.id, "content": content})

        # Fire detections → episodes (high importance)
        elif tool_name == "fires":
            features = result.get("features", [])
            if features:
                count = len(features)
                location = result.get("metadata", {}).get("location", "unknown")
                content = (
                    f"{count} active fire(s) detected near {location}"
                )
                ep = self.remember_episode(
                    content,
                    source=f"tool:{tool_name}",
                    importance=0.9,
                    session_id=session_id,
                    tags=["fire", "hazard", "urgent"],
                )
                extracted.append({"type": "episode", "id": ep.id, "content": content})

        # Distance calculations → facts
        elif tool_name == "distance":
            dist_km = result.get("distance_km")
            if dist_km is not None:
                content = (
                    f"Distance: {dist_km:.2f} km "
                    f"(geodesic on WGS84 ellipsoid)"
                )
                fact = self.remember_fact(
                    content,
                    source=f"tool:{tool_name}",
                    tags=["distance", "measurement"],
                )
                extracted.append({"type": "fact", "id": fact.id, "content": content})

        # Elevation → facts
        elif tool_name == "elevation":
            elev = result.get("elevation_m")
            if elev is not None:
                lat = result.get("latitude", "?")
                lon = result.get("longitude", "?")
                content = f"Elevation at ({lat}, {lon}): {elev} m above sea level"
                fact = self.remember_fact(
                    content,
                    source=f"tool:{tool_name}",
                    tags=["elevation", "terrain"],
                )
                extracted.append({"type": "fact", "id": fact.id, "content": content})

        return extracted

    # -------------------------------------------------------------------
    # Compaction
    # -------------------------------------------------------------------

    def compact(self, max_age_days: int = 30, keep_important: float = 0.7) -> dict[str, int]:
        """Compact old episodes: deactivate low-importance old ones.

        Keeps episodes that are recent (< max_age_days) or important
        (>= keep_important threshold). All facts are preserved.

        Returns counts of compacted and kept episodes.
        """
        now = datetime.now(timezone.utc)
        compacted = 0
        kept = 0

        for ep in self._episodes:
            if not ep.is_active:
                continue
            age_days = (now - ep.created_at).total_seconds() / 86400
            if age_days > max_age_days and ep.importance < keep_important:
                ep.is_active = False
                self._vector_store.remove(f"episode:{ep.id}")
                compacted += 1
            else:
                kept += 1

        if compacted > 0:
            self._save()

        return {"compacted": compacted, "kept": kept, "facts_preserved": len(self._facts)}

    # -------------------------------------------------------------------
    # Stats
    # -------------------------------------------------------------------

    def stats(self) -> IntelligenceStats:
        """Return statistics about the intelligence store."""
        active_facts = sum(1 for f in self._facts if f.is_active)
        active_episodes = sum(1 for e in self._episodes if e.is_active)
        contradictions = len(self.find_contradictions())

        return IntelligenceStats(
            total_facts=len(self._facts),
            active_facts=active_facts,
            total_episodes=len(self._episodes),
            active_episodes=active_episodes,
            total_connections=len(self._connections),
            contradictions_found=contradictions,
            vector_store_count=self._vector_store.count,
            using_faiss=self._vector_store.using_faiss,
        )

    # -------------------------------------------------------------------
    # Accessors
    # -------------------------------------------------------------------

    def get_fact(self, fact_id: str) -> SpatialFact | None:
        """Get a specific fact by ID."""
        for f in self._facts:
            if f.id == fact_id:
                return f
        return None

    def get_episode(self, episode_id: str) -> SpatialEpisode | None:
        """Get a specific episode by ID."""
        for e in self._episodes:
            if e.id == episode_id:
                return e
        return None

    def list_facts(self, active_only: bool = True, limit: int = 50) -> list[SpatialFact]:
        """List stored facts."""
        facts = self._facts
        if active_only:
            facts = [f for f in facts if f.is_active]
        return facts[:limit]

    def list_episodes(self, active_only: bool = True, limit: int = 50) -> list[SpatialEpisode]:
        """List stored episodes."""
        episodes = self._episodes
        if active_only:
            episodes = [e for e in episodes if e.is_active]
        return sorted(episodes, key=lambda e: e.occurred_at, reverse=True)[:limit]

    def get_connections_for(self, memory_id: str) -> list[MemoryConnection]:
        """Get all connections involving a specific memory."""
        return [
            c for c in self._connections
            if c.source_id == memory_id or c.target_id == memory_id
        ]

    # -------------------------------------------------------------------
    # Persistence
    # -------------------------------------------------------------------

    def _save(self) -> None:
        """Persist all data to disk."""
        data = {
            "facts": [f.model_dump(mode="json") for f in self._facts],
            "episodes": [e.model_dump(mode="json") for e in self._episodes],
            "connections": [c.model_dump(mode="json") for c in self._connections],
        }
        path = self._storage_dir / "intelligence.json"
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

        # Save vector store
        if self._vector_store.count > 0:
            self._vector_store.save()

    def _load(self) -> None:
        """Load data from disk."""
        path = self._storage_dir / "intelligence.json"
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self._facts = [SpatialFact.model_validate(f) for f in data.get("facts", [])]
            self._episodes = [
                SpatialEpisode.model_validate(e) for e in data.get("episodes", [])
            ]
            self._connections = [
                MemoryConnection.model_validate(c) for c in data.get("connections", [])
            ]
        except (json.JSONDecodeError, KeyError):
            pass

    def clear(self) -> dict[str, int]:
        """Clear all intelligence data."""
        counts = {
            "facts": len(self._facts),
            "episodes": len(self._episodes),
            "connections": len(self._connections),
            "vectors": self._vector_store.count,
        }
        self._facts.clear()
        self._episodes.clear()
        self._connections.clear()
        self._vector_store.clear()
        self._save()
        return counts
