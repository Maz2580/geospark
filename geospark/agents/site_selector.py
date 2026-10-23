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

from geospark.agents.amenities import AmenityLookupError, find_amenities
from geospark.engine.core import Engine
from geospark.engine.spatial_reasoner import SpatialReasoner
from geospark.knowledge.loaders import OverpassLoader
from geospark.mcp_servers.launcher import MCPServerLauncher
from geospark.protocol.provenance import Provenance


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
    radius_m: float = 0.0  # the radius actually searched
    # What could not be looked up, and what a reader should know about the data
    data_gaps: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    provenance: list[Provenance] = Field(default_factory=list)


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
        result.radius_m = radius_m
        if not near_types:
            result.summary = (f"Nothing to rank in {within}: give at least one kind of place the site "
                              "should be near (for example near=['school']).")
            result.duration_s = round(time.time() - start, 1)
            return result

        # Steps 2-3: the "near" and "avoid" amenities, in one lookup (OpenStreetMap, then Overture Maps)
        try:
            lookup = find_amenities(lat, lon, radius_m, near_types + avoid_types, self._overpass)
        except AmenityLookupError:
            result.data_gaps = near_types + avoid_types
            result.summary = (f"Could not rank sites in {within}: the nearby places "
                              f"({', '.join(near_types + avoid_types)}) could not be retrieved from "
                              "OpenStreetMap or Overture Maps. Please try again in a few minutes.")
            result.duration_s = round(time.time() - start, 1)
            return result
        radius_m = lookup.radius_m
        result.radius_m = radius_m
        result.caveats.extend(lookup.warnings)
        result.data_gaps = list(lookup.unavailable)
        missing = [t for t in near_types + avoid_types if t in lookup.unavailable]
        if missing:
            # Ranking on the remaining criteria would answer a different question than the one asked
            result.summary = (f"Could not rank sites in {within}: {', '.join(missing)} could not be "
                              "retrieved (OpenStreetMap was unavailable and there is no reliable fallback "
                              "for them), and a ranking without them would not answer this request. "
                              "Please try again in a few minutes.")
            result.duration_s = round(time.time() - start, 1)
            return result
        result.provenance = list(lookup.provenance)

        def as_features(kind: str) -> list[dict[str, Any]]:
            return [{"name": e.name, "coordinates": e.geometry.get("coordinates", []), "geometry": e.geometry}
                    for e in lookup.by_type.get(kind, [])]

        near_features = {kind: as_features(kind) for kind in near_types}
        avoid_features = {kind: as_features(kind) for kind in avoid_types}

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
            # Nothing to anchor a site to: say so rather than inventing a "center" candidate
            result.summary = (f"No {' or '.join(near_types)} found within {round(radius_m)} m of {within}, "
                              "so no site can be ranked. Try a larger area or different criteria.")
            result.duration_s = round(time.time() - start, 1)
            return result

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
                        # Skip self-matches (distance < 10m means same feature)
                        if d > 10:
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
Use ONLY the facts below. Scores add up closeness to each "near" criterion (1 per criterion when one is
right next to the site, 0 when the nearest is at the search radius); higher is better.
Give the real distances from the details; do not claim anything the details do not show.

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
