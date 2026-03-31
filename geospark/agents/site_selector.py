"""
SiteSelector — Optimal location finding agent.

Given criteria (near X, avoid Y, within Z), evaluates candidate
locations and ranks them by a multi-criteria spatial score.

Usage:
    selector = SiteSelector(engine)
    result = selector.find(
        within="Melbourne CBD",
        near=["hospital", "school"],
        facility_type="pharmacy",
    )
    print(result.best)
"""

from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, Field

from geospark.engine.core import Engine
from geospark.engine.spatial_reasoner import SpatialReasoner
from geospark.knowledge.loaders import OverpassLoader
from geospark.mcp_servers.launcher import MCPServerLauncher


class SiteCandidate(BaseModel):
    """A scored candidate location."""

    name: str
    coordinates: list[float]
    score: float = 0.0
    details: dict[str, Any] = Field(default_factory=dict)


class SiteResult(BaseModel):
    """Result of a site selection analysis."""

    query: str
    within: str
    near_criteria: list[str] = Field(default_factory=list)
    avoid_criteria: list[str] = Field(default_factory=list)
    candidates: list[SiteCandidate] = Field(default_factory=list)
    best: SiteCandidate | None = None
    summary: str = ""
    duration_s: float = 0.0


class SiteSelector:
    """Multi-criteria spatial site selection.

    Evaluates locations based on proximity to desired amenities
    and distance from undesired features.
    """

    def __init__(
        self,
        engine: Engine | None = None,
        ollama_url: str | None = None,
        model: str | None = None,
    ) -> None:
        self.engine = engine or Engine(tools=["geocoder", "terrain"])
        self._launcher = MCPServerLauncher()
        self._overpass = OverpassLoader()

        import os

        self._ollama_url = ollama_url or os.getenv(
            "OLLAMA_BASE_URL", "http://localhost:11434"
        )
        self._model = model or os.getenv("GEOSPARK_OLLAMA_MODEL", "qwen2.5:7b")

    def find(
        self,
        within: str,
        near: list[str] | None = None,
        avoid: list[str] | None = None,
        facility_type: str = "restaurant",
        radius_m: float = 5000,
        max_candidates: int = 10,
    ) -> SiteResult:
        """Find optimal locations matching spatial criteria.

        Args:
            within: Area to search (city name, neighborhood).
            near: Amenity types to be close to (e.g. ["hospital", "school"]).
            avoid: Amenity types to stay away from (e.g. ["industrial"]).
            facility_type: What kind of facility to place (for context).
            radius_m: Search radius from center of 'within' area.
            max_candidates: Maximum candidates to return.

        Returns:
            SiteResult with ranked candidates.
        """
        start = time.time()
        near_types = near or []
        avoid_types = avoid or []

        result = SiteResult(
            query=f"Best {facility_type} location in {within}",
            within=within,
            near_criteria=near_types,
            avoid_criteria=avoid_types,
        )

        # Step 1: Geocode the 'within' area
        geo = self._launcher.handle_tool_call("geocode", {
            "explanation": f"Geocoding search area: {within}",
            "query": within,
        })
        if geo.get("status") != "success":
            result.summary = f"Could not geocode: {within}"
            return result

        features = geo.get("result", {}).get("features", [])
        if not features:
            result.summary = f"No results for: {within}"
            return result

        center_coords = features[0].get("geometry", {}).get("coordinates", [])
        if len(center_coords) < 2:
            result.summary = "Invalid coordinates"
            return result

        lon, lat = center_coords[0], center_coords[1]
        center = {"type": "Point", "coordinates": [lon, lat]}
        delta = radius_m / 111320
        bbox = (lat - delta, lon - delta, lat + delta, lon + delta)

        # Step 2: Load all "near" amenities
        near_features: dict[str, list[dict[str, Any]]] = {}
        for amenity in near_types:
            try:
                entities = self._overpass.load_amenities(bbox, amenity)
                near_features[amenity] = [
                    {
                        "name": e.name,
                        "coordinates": e.geometry.get("coordinates", []),
                        "geometry": e.geometry,
                    }
                    for e in entities
                ]
            except Exception:
                near_features[amenity] = []

        # Step 3: Load "avoid" amenities
        avoid_features: dict[str, list[dict[str, Any]]] = {}
        for amenity in avoid_types:
            try:
                entities = self._overpass.load_amenities(bbox, amenity)
                avoid_features[amenity] = [
                    {
                        "name": e.name,
                        "coordinates": e.geometry.get("coordinates", []),
                        "geometry": e.geometry,
                    }
                    for e in entities
                ]
            except Exception:
                avoid_features[amenity] = []

        # Step 4: Use "near" feature locations as candidate sites
        # Each "near" amenity location is a potential candidate
        # (the logic: a good site is where multiple desired amenities converge)
        candidate_points: list[dict[str, Any]] = []
        for amenity, feats in near_features.items():
            for f in feats[:20]:  # Cap per type
                candidate_points.append({
                    "name": f"{f['name']} area",
                    "coordinates": f["coordinates"],
                    "geometry": f["geometry"],
                    "source_amenity": amenity,
                })

        if not candidate_points:
            # Fallback: use the center point
            candidate_points.append({
                "name": f"{within} center",
                "coordinates": [lon, lat],
                "geometry": center,
            })

        # Step 5: Score each candidate
        scored: list[SiteCandidate] = []
        for cp in candidate_points:
            cp_geom = cp["geometry"]
            score = 0.0
            details: dict[str, Any] = {}

            # Score proximity to "near" amenities
            for amenity, feats in near_features.items():
                if not feats:
                    continue
                distances = []
                for f in feats:
                    try:
                        d = SpatialReasoner.calculate_distance(cp_geom, f["geometry"])
                        distances.append(d)
                    except Exception:
                        continue
                if distances:
                    nearest = min(distances)
                    # Closer = higher score (normalize by radius)
                    proximity_score = max(0, 1 - nearest / radius_m)
                    score += proximity_score
                    details[f"nearest_{amenity}_m"] = round(nearest)

            # Penalize proximity to "avoid" amenities
            for amenity, feats in avoid_features.items():
                if not feats:
                    continue
                distances = []
                for f in feats:
                    try:
                        d = SpatialReasoner.calculate_distance(cp_geom, f["geometry"])
                        distances.append(d)
                    except Exception:
                        continue
                if distances:
                    nearest = min(distances)
                    # Closer = lower score (penalty)
                    penalty = max(0, 1 - nearest / radius_m) * 0.5
                    score -= penalty
                    details[f"nearest_{amenity}_m"] = round(nearest)

            scored.append(SiteCandidate(
                name=cp["name"],
                coordinates=cp["coordinates"],
                score=round(score, 3),
                details=details,
            ))

        # Step 6: Rank and deduplicate
        scored.sort(key=lambda c: c.score, reverse=True)

        # Deduplicate by proximity (remove candidates within 100m of a higher-scored one)
        unique: list[SiteCandidate] = []
        for candidate in scored:
            too_close = False
            for existing in unique:
                try:
                    d = SpatialReasoner.calculate_distance(
                        {"type": "Point", "coordinates": candidate.coordinates},
                        {"type": "Point", "coordinates": existing.coordinates},
                    )
                    if d < 100:
                        too_close = True
                        break
                except Exception:
                    continue
            if not too_close:
                unique.append(candidate)
            if len(unique) >= max_candidates:
                break

        result.candidates = unique
        result.best = unique[0] if unique else None

        # Step 7: Generate summary
        result.summary = self._generate_summary(result)
        result.duration_s = round(time.time() - start, 1)
        return result

    def _generate_summary(self, result: SiteResult) -> str:
        """Generate a summary of site selection results."""
        import json

        import httpx

        if not result.candidates:
            return f"No suitable locations found in {result.within}."

        best = result.best
        top3 = result.candidates[:3]
        top_info = json.dumps(
            [{"name": c.name, "score": c.score, "details": c.details} for c in top3],
            default=str,
        )

        prompt = f"""Summarize site selection results in 2-3 sentences.

Goal: {result.query}
Search area: {result.within}
Near criteria: {result.near_criteria}
Avoid criteria: {result.avoid_criteria}
Top 3 candidates: {top_info}
Best: {best.name if best else 'none'} (score: {best.score if best else 0})

Summary:"""

        try:
            resp = httpx.post(
                f"{self._ollama_url}/api/chat",
                json={
                    "model": self._model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                },
                timeout=60,
            )
            resp.raise_for_status()
            return resp.json().get("message", {}).get("content", "").strip()
        except Exception:
            if best:
                return (
                    f"Best location: {best.name} (score: {best.score}). "
                    f"Found {len(result.candidates)} candidates in {result.within}."
                )
            return f"No suitable locations found in {result.within}."
