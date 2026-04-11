"""Hierarchical context retriever — semantic search + hotness + recursive scoring."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from geospark.context.geo_context import ContextTier, GeoContext, HotnessStats
from geospark.context.storage import ContextStore


def _word_overlap_score(query: str, content: str) -> float:
    """Simple word overlap similarity (fallback when no embeddings)."""
    q_words = set(query.lower().split())
    c_words = set(content.lower().split())
    if not q_words:
        return 0.0
    if query.lower() in content.lower():
        return 0.9
    overlap = len(q_words & c_words)
    if overlap == 0:
        return 0.0
    return min(overlap / len(q_words), 0.8)


class RetrievalResult(BaseModel):
    """A single result from a context retrieval query."""

    context: GeoContext
    semantic_score: float = 0.0
    hotness_score: float = 0.0
    parent_score: float = 0.0
    final_score: float = 0.0
    tier_loaded: ContextTier = ContextTier.L0
    matched_bbox: bool = True
    matched_temporal: bool = True


class RetrievalStats(BaseModel):
    """Statistics from a retrieval call."""

    total_candidates: int = 0
    filtered_by_bbox: int = 0
    filtered_by_temporal: int = 0
    filtered_by_archive: int = 0
    returned: int = 0
    convergence_rounds: int = 0
    query_terms: list[str] = Field(default_factory=list)


class ContextRetriever:
    """Retrieves geospatial contexts with hierarchical scoring.

    Combines four signals:
    1. Semantic similarity between query and context abstract/overview
    2. Hotness score (access frequency + recency)
    3. Parent context score (propagated down the hierarchy)
    4. Spatial and temporal filter matches

    Final score formula:
        final = semantic_weight * semantic
              + hotness_weight * hotness
              + parent_weight * parent_score

    Defaults: semantic=0.6, hotness=0.2, parent=0.2
    """

    # Default weights
    DEFAULT_SEMANTIC_WEIGHT = 0.6
    DEFAULT_HOTNESS_WEIGHT = 0.2
    DEFAULT_PARENT_WEIGHT = 0.2
    MAX_CONVERGENCE_ROUNDS = 3

    def __init__(
        self,
        store: ContextStore,
        semantic_weight: float | None = None,
        hotness_weight: float | None = None,
        parent_weight: float | None = None,
        hotness_decay: float = 0.1,
    ) -> None:
        self._store = store
        self._semantic_weight = semantic_weight or self.DEFAULT_SEMANTIC_WEIGHT
        self._hotness_weight = hotness_weight or self.DEFAULT_HOTNESS_WEIGHT
        self._parent_weight = parent_weight or self.DEFAULT_PARENT_WEIGHT
        self._hotness_decay = hotness_decay

        # Normalize weights if they don't sum to 1.0
        total = self._semantic_weight + self._hotness_weight + self._parent_weight
        if total > 0 and abs(total - 1.0) > 0.001:
            self._semantic_weight /= total
            self._hotness_weight /= total
            self._parent_weight /= total

    # -------------------------------------------------------------------
    # Main retrieval
    # -------------------------------------------------------------------

    def retrieve(
        self,
        query: str = "",
        bbox: list[float] | None = None,
        temporal_start: datetime | None = None,
        temporal_end: datetime | None = None,
        category: str | None = None,
        limit: int = 10,
        tier: ContextTier = ContextTier.L0,
        include_archived: bool = False,
    ) -> tuple[list[RetrievalResult], RetrievalStats]:
        """Retrieve relevant contexts for a query.

        Args:
            query: Text query for semantic matching (optional)
            bbox: Spatial filter [min_lon, min_lat, max_lon, max_lat] (optional)
            temporal_start: Start of temporal range filter (optional)
            temporal_end: End of temporal range filter (optional)
            category: Restrict to a category (e.g. "missions")
            limit: Max results to return
            tier: Loading tier (L0/L1/L2) — affects what's populated in results
            include_archived: Include archived contexts

        Returns:
            (results, stats) tuple. Results sorted by final_score descending.
        """
        stats = RetrievalStats(query_terms=query.split() if query else [])

        candidates = self._store.list_all(
            category=category, include_archived=include_archived
        )
        stats.total_candidates = len(candidates)

        # Apply spatial filter
        if bbox is not None:
            before = len(candidates)
            candidates = [c for c in candidates if c.intersects_bbox(bbox)]
            stats.filtered_by_bbox = before - len(candidates)

        # Apply temporal filter
        if temporal_start is not None or temporal_end is not None:
            before = len(candidates)
            candidates = [
                c for c in candidates
                if c.within_temporal_range(temporal_start, temporal_end)
            ]
            stats.filtered_by_temporal = before - len(candidates)

        # Score each candidate
        results: list[RetrievalResult] = []
        uri_to_result: dict[str, RetrievalResult] = {}

        for ctx in candidates:
            semantic_score = self._semantic_score(query, ctx)
            hotness = ctx.compute_hotness(decay_rate=self._hotness_decay)

            result = RetrievalResult(
                context=ctx,
                semantic_score=semantic_score,
                hotness_score=hotness.score,
                parent_score=0.0,  # Filled in by propagation pass
                final_score=0.0,
                tier_loaded=tier,
            )
            results.append(result)
            uri_to_result[ctx.uri] = result

        # Propagate parent scores recursively
        convergence_rounds = self._propagate_parent_scores(uri_to_result)
        stats.convergence_rounds = convergence_rounds

        # Compute final scores
        for r in results:
            r.final_score = round(
                self._semantic_weight * r.semantic_score
                + self._hotness_weight * r.hotness_score
                + self._parent_weight * r.parent_score,
                4,
            )

        # Filter out zero-score results and sort
        results = [r for r in results if r.final_score > 0.001]
        results.sort(key=lambda r: r.final_score, reverse=True)
        results = results[:limit]

        stats.returned = len(results)
        return results, stats

    # -------------------------------------------------------------------
    # Scoring components
    # -------------------------------------------------------------------

    def _semantic_score(self, query: str, ctx: GeoContext) -> float:
        """Compute semantic similarity between query and context content."""
        if not query:
            return 0.5  # No query = neutral score, rely on hotness/parent

        # Combine abstract, name, and tags into searchable text
        searchable_parts = [ctx.abstract, ctx.name]
        searchable_parts.extend(ctx.tags)
        if ctx.overview:
            # Include overview values
            searchable_parts.extend(str(v) for v in ctx.overview.values())
        searchable = " ".join(searchable_parts)

        return _word_overlap_score(query, searchable)

    def _propagate_parent_scores(
        self,
        uri_to_result: dict[str, RetrievalResult],
        alpha: float = 0.5,
    ) -> int:
        """Recursively propagate parent context scores to children.

        For each child, parent_score = alpha * parent.semantic_score +
        (1-alpha) * parent.parent_score. Iterates until convergence or
        MAX_CONVERGENCE_ROUNDS.

        Returns number of rounds run.
        """
        if not uri_to_result:
            return 0

        for round_num in range(1, self.MAX_CONVERGENCE_ROUNDS + 1):
            changed = False
            for _uri, result in uri_to_result.items():
                parent_uri = result.context.parent_uri
                if parent_uri and parent_uri in uri_to_result:
                    parent_result = uri_to_result[parent_uri]
                    new_parent_score = (
                        alpha * parent_result.semantic_score
                        + (1 - alpha) * parent_result.parent_score
                    )
                    if abs(new_parent_score - result.parent_score) > 0.001:
                        result.parent_score = round(new_parent_score, 4)
                        changed = True
            if not changed:
                return round_num
        return self.MAX_CONVERGENCE_ROUNDS

    # -------------------------------------------------------------------
    # Convenience queries
    # -------------------------------------------------------------------

    def nearby(
        self,
        bbox: list[float],
        limit: int = 10,
        category: str | None = None,
    ) -> list[RetrievalResult]:
        """Find contexts that intersect a bounding box, ranked by hotness."""
        results, _ = self.retrieve(bbox=bbox, limit=limit, category=category)
        return results

    def recent(
        self,
        start: datetime,
        end: datetime | None = None,
        limit: int = 10,
        category: str | None = None,
    ) -> list[RetrievalResult]:
        """Find contexts with temporal range in a given window."""
        results, _ = self.retrieve(
            temporal_start=start,
            temporal_end=end,
            limit=limit,
            category=category,
        )
        return results

    def hottest(
        self,
        limit: int = 10,
        category: str | None = None,
        include_archived: bool = False,
    ) -> list[HotnessStats]:
        """Return the top-N hottest contexts by hotness score alone."""
        contexts = self._store.list_all(
            category=category, include_archived=include_archived
        )
        scored = [ctx.compute_hotness(decay_rate=self._hotness_decay) for ctx in contexts]
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:limit]

    def coldest(
        self,
        limit: int = 10,
        category: str | None = None,
    ) -> list[HotnessStats]:
        """Return the N coldest contexts — candidates for archival."""
        contexts = self._store.list_all(category=category, include_archived=False)
        scored = [ctx.compute_hotness(decay_rate=self._hotness_decay) for ctx in contexts]
        scored.sort(key=lambda s: s.score)
        return scored[:limit]

    def archive_cold(
        self,
        threshold: float = 0.1,
        category: str | None = None,
    ) -> list[str]:
        """Archive all contexts with hotness score below threshold.

        Returns list of archived URIs.
        """
        contexts = self._store.list_all(category=category, include_archived=False)
        archived: list[str] = []
        for ctx in contexts:
            hotness = ctx.compute_hotness(decay_rate=self._hotness_decay)
            if hotness.score < threshold and self._store.archive(ctx.uri):
                archived.append(ctx.uri)
        return archived
