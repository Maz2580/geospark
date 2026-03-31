"""
GeoAgent — Autonomous spatial reasoning agent.

Takes a natural language goal, plans multi-step spatial analysis,
executes each step using GeoSpark tools, and returns structured results.

Usage:
    agent = GeoAgent(engine)
    result = agent.run("Find all hospitals within 3km of the Eiffel Tower")
    print(result.summary)
"""

from __future__ import annotations

import json
import time
from typing import Any

from pydantic import BaseModel, Field

from geospark.engine.core import Engine
from geospark.engine.spatial_reasoner import SpatialReasoner
from geospark.knowledge.graph import SpatialKnowledgeGraph
from geospark.knowledge.loaders import OverpassLoader
from geospark.mcp_servers.launcher import MCPServerLauncher


class AgentStep(BaseModel):
    """A single step executed by the agent."""

    action: str
    description: str
    result: dict[str, Any] = Field(default_factory=dict)
    duration_s: float = 0.0
    error: str | None = None


class AgentResult(BaseModel):
    """Complete result from a GeoAgent run."""

    goal: str
    steps: list[AgentStep] = Field(default_factory=list)
    findings: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""
    total_duration_s: float = 0.0


class GeoAgent:
    """Autonomous spatial reasoning agent.

    Plans and executes multi-step spatial analyses using GeoSpark tools.
    Works with Ollama (local, free) or OpenRouter as the reasoning LLM.
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
        self._graph = SpatialKnowledgeGraph()

        import os

        self._ollama_url = ollama_url or os.getenv(
            "OLLAMA_BASE_URL", "http://localhost:11434"
        )
        self._model = model or os.getenv("GEOSPARK_OLLAMA_MODEL", "qwen2.5:7b")

    def run(self, goal: str) -> AgentResult:
        """Execute an autonomous spatial analysis for the given goal.

        Args:
            goal: Natural language description of the spatial task.

        Returns:
            AgentResult with steps, findings, and summary.
        """
        start = time.time()
        result = AgentResult(goal=goal)

        # Step 1: Extract locations and intent from the goal
        locations, intent, params = self._parse_goal(goal)
        result.steps.append(AgentStep(
            action="parse_goal",
            description=f"Extracted locations: {locations}, intent: {intent}",
            result={"locations": locations, "intent": intent, "params": params},
        ))

        # Step 2: Geocode all mentioned locations
        geocoded = {}
        for loc in locations:
            t0 = time.time()
            geo_result = self._geocode(loc)
            step = AgentStep(
                action="geocode",
                description=f"Geocode: {loc}",
                result=geo_result,
                duration_s=round(time.time() - t0, 1),
            )
            if not geo_result.get("coordinates"):
                step.error = f"Failed to geocode: {loc}"
            else:
                geocoded[loc] = geo_result
            result.steps.append(step)

        result.findings["geocoded"] = geocoded

        # Step 3: Execute intent-specific analysis
        if intent == "find_nearby":
            self._find_nearby(result, geocoded, params)
        elif intent == "distance":
            self._compute_distances(result, geocoded)
        elif intent == "analyze_area":
            self._analyze_area(result, geocoded, params)
        elif intent == "check_relationship":
            self._check_relationships(result, geocoded, params)
        else:
            # Generic: try to find nearby amenities for each location
            self._find_nearby(result, geocoded, params)

        # Step 4: Generate summary
        t0 = time.time()
        summary = self._generate_summary(result)
        result.summary = summary
        result.steps.append(AgentStep(
            action="summarize",
            description="Generate findings summary",
            result={"summary_length": len(summary)},
            duration_s=round(time.time() - t0, 1),
        ))

        result.total_duration_s = round(time.time() - start, 1)
        return result

    def _parse_goal(
        self, goal: str
    ) -> tuple[list[str], str, dict[str, Any]]:
        """Extract locations, intent, and parameters from a goal string."""
        import httpx

        prompt = f"""Analyze this spatial task and extract structured information.
Task: {goal}

Respond with ONLY valid JSON (no markdown, no explanation):
{{
  "locations": ["list of place names mentioned"],
  "intent": "one of: find_nearby, distance, analyze_area, check_relationship",
  "params": {{
    "amenity_type": "type of thing to find (hospital, school, park, etc.) or null",
    "radius_m": radius in meters or 3000,
    "relationship": "contains, intersects, within, or null"
  }}
}}"""

        try:
            resp = httpx.post(
                f"{self._ollama_url}/api/chat",
                json={
                    "model": self._model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "format": "json",
                },
                timeout=60,
            )
            resp.raise_for_status()
            content = resp.json().get("message", {}).get("content", "{}")
            parsed = json.loads(content)
            return (
                parsed.get("locations", []),
                parsed.get("intent", "find_nearby"),
                parsed.get("params", {}),
            )
        except Exception:
            # Fallback: simple keyword extraction
            locations = []
            # Look for capitalized words as potential locations
            for word in goal.split():
                if word[0].isupper() and word.lower() not in {
                    "find", "what", "where", "how", "is", "are", "the",
                    "within", "near", "from", "to", "all", "any",
                }:
                    locations.append(word)

            intent = "find_nearby"
            if "distance" in goal.lower() or "far" in goal.lower():
                intent = "distance"
            elif "contain" in goal.lower() or "inside" in goal.lower():
                intent = "check_relationship"

            return locations, intent, {"radius_m": 3000}

    def _geocode(self, location: str) -> dict[str, Any]:
        """Geocode a location name."""
        result = self._launcher.handle_tool_call("geocode", {
            "explanation": f"Geocoding {location}",
            "query": location,
        })
        if result.get("status") == "success":
            features = result.get("result", {}).get("features", [])
            if features:
                coords = features[0].get("geometry", {}).get("coordinates", [])
                name = features[0].get("properties", {}).get("display_name", location)
                return {
                    "coordinates": coords,
                    "name": name,
                    "geometry": features[0].get("geometry"),
                }
        return {"coordinates": None, "error": "Geocoding failed"}

    def _find_nearby(
        self,
        result: AgentResult,
        geocoded: dict[str, dict],
        params: dict[str, Any],
    ) -> None:
        """Find nearby amenities for geocoded locations."""
        amenity = params.get("amenity_type", "hospital")
        radius = params.get("radius_m", 3000)

        if not amenity:
            amenity = "hospital"

        for loc_name, geo in geocoded.items():
            coords = geo.get("coordinates")
            if not coords:
                continue

            t0 = time.time()
            lon, lat = coords[0], coords[1]
            # Create bbox around the point
            delta = radius / 111320  # Approximate degrees
            bbox = (lat - delta, lon - delta, lat + delta, lon + delta)

            try:
                entities = self._overpass.load_amenities(bbox, amenity)
                # Compute distances from the center point
                center = {"type": "Point", "coordinates": [lon, lat]}
                nearby = []
                for ent in entities:
                    dist = SpatialReasoner.calculate_distance(center, ent.geometry)
                    if dist <= radius:
                        nearby.append({
                            "name": ent.name,
                            "distance_m": round(dist),
                            "coordinates": ent.geometry.get("coordinates"),
                        })
                nearby.sort(key=lambda x: x["distance_m"])

                result.findings.setdefault("nearby", {})[loc_name] = {
                    "amenity_type": amenity,
                    "radius_m": radius,
                    "count": len(nearby),
                    "items": nearby[:20],
                }
                result.steps.append(AgentStep(
                    action="find_nearby",
                    description=f"Found {len(nearby)} {amenity}(s) within {radius}m of {loc_name}",
                    result={"count": len(nearby), "nearest": nearby[0]["name"] if nearby else None},
                    duration_s=round(time.time() - t0, 1),
                ))
            except Exception as e:
                result.steps.append(AgentStep(
                    action="find_nearby",
                    description=f"Search {amenity} near {loc_name}",
                    error=str(e),
                    duration_s=round(time.time() - t0, 1),
                ))

    def _compute_distances(
        self,
        result: AgentResult,
        geocoded: dict[str, dict],
    ) -> None:
        """Compute distances between all geocoded location pairs."""
        locations = list(geocoded.items())
        distances = []

        for i, (name_a, geo_a) in enumerate(locations):
            for name_b, geo_b in locations[i + 1:]:
                coords_a = geo_a.get("coordinates")
                coords_b = geo_b.get("coordinates")
                if not coords_a or not coords_b:
                    continue

                geom_a = {"type": "Point", "coordinates": coords_a}
                geom_b = {"type": "Point", "coordinates": coords_b}
                dist = SpatialReasoner.calculate_distance(geom_a, geom_b)
                distances.append({
                    "from": name_a,
                    "to": name_b,
                    "distance_m": round(dist, 1),
                    "distance_km": round(dist / 1000, 2),
                })

        result.findings["distances"] = distances
        for d in distances:
            result.steps.append(AgentStep(
                action="distance",
                description=f"{d['from']} → {d['to']}: {d['distance_km']} km",
                result=d,
            ))

    def _analyze_area(
        self,
        result: AgentResult,
        geocoded: dict[str, dict],
        params: dict[str, Any],
    ) -> None:
        """Analyze an area: boundary, amenities, accessibility."""
        for loc_name, geo in geocoded.items():
            coords = geo.get("coordinates")
            if not coords:
                continue

            # Get elevation
            t0 = time.time()
            elev_result = self._launcher.handle_tool_call("get_elevation", {
                "explanation": f"Get elevation at {loc_name}",
                "latitude": coords[1],
                "longitude": coords[0],
            })
            elevation = None
            if elev_result.get("status") == "success" and elev_result.get("result"):
                elevation = elev_result["result"].get("elevation_m")

            result.findings.setdefault("analysis", {})[loc_name] = {
                "coordinates": coords,
                "elevation_m": elevation,
            }
            result.steps.append(AgentStep(
                action="elevation",
                description=f"Elevation at {loc_name}: {elevation}m",
                result={"elevation_m": elevation},
                duration_s=round(time.time() - t0, 1),
            ))

        # Also find nearby amenities
        self._find_nearby(result, geocoded, params)

    def _check_relationships(
        self,
        result: AgentResult,
        geocoded: dict[str, dict],
        params: dict[str, Any],
    ) -> None:
        """Check spatial relationships between geocoded locations."""
        relationship = params.get("relationship", "contains")
        locations = list(geocoded.items())

        for i, (name_a, geo_a) in enumerate(locations):
            for name_b, geo_b in locations[i + 1:]:
                geom_a = geo_a.get("geometry")
                geom_b = geo_b.get("geometry")
                if not geom_a or not geom_b:
                    continue

                try:
                    holds = SpatialReasoner.check_relationship(
                        geom_a, geom_b, relationship
                    )
                    result.findings.setdefault("relationships", []).append({
                        "a": name_a,
                        "b": name_b,
                        "relationship": relationship,
                        "result": holds,
                    })
                    result.steps.append(AgentStep(
                        action="check_relationship",
                        description=f"{name_a} {relationship} {name_b}: {holds}",
                        result={"holds": holds},
                    ))
                except Exception as e:
                    result.steps.append(AgentStep(
                        action="check_relationship",
                        description=f"Check {relationship}: {name_a} vs {name_b}",
                        error=str(e),
                    ))

    def _generate_summary(self, result: AgentResult) -> str:
        """Generate a human-readable summary of the findings."""
        import httpx

        findings_str = json.dumps(result.findings, indent=2, default=str)[:3000]
        steps_str = "\n".join(
            f"- {s.description}" for s in result.steps if not s.error
        )

        prompt = f"""Summarize these spatial analysis findings in 2-4 sentences.
Be specific with numbers and distances.

Goal: {result.goal}

Steps completed:
{steps_str}

Findings:
{findings_str}

Write a clear, concise summary:"""

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
            # Fallback: build summary from findings
            parts = [f"Analysis for: {result.goal}"]
            if "distances" in result.findings:
                for d in result.findings["distances"]:
                    parts.append(f"{d['from']} to {d['to']}: {d['distance_km']} km")
            if "nearby" in result.findings:
                for loc, data in result.findings["nearby"].items():
                    parts.append(
                        f"Found {data['count']} {data['amenity_type']}(s) "
                        f"within {data['radius_m']}m of {loc}"
                    )
            return ". ".join(parts)
