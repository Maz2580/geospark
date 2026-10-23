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
import re
import time
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from geospark.agents.amenities import find_amenities
from geospark.engine.core import Engine
from geospark.engine.spatial_reasoner import SpatialReasoner
from geospark.knowledge.graph import SpatialKnowledgeGraph
from geospark.knowledge.loaders import OverpassLoader
from geospark.mcp_servers.launcher import MCPServerLauncher
from geospark.utils.aio import run_sync


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
        locations, params = self._separate_place_types(locations, params)
        locations = self._join_comma_places(goal, locations, intent)
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
                # e.g. an ambiguous name, or a match found only near the named area
                for caveat in geo_result.get("warnings") or []:
                    if caveat not in result.findings.setdefault("caveats", []):
                        result.findings["caveats"].append(caveat)
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
        elif intent == "weather":
            self._get_weather(result, geocoded)
        elif intent == "elevation":
            self._get_elevations(result, geocoded)
        elif intent == "air_quality":
            self._get_air_quality(result, geocoded)
        elif intent == "fire_detection":
            self._detect_fires(result, geocoded)
        elif intent == "environmental":
            self._get_weather(result, geocoded)
            self._get_air_quality(result, geocoded)
            self._detect_fires(result, geocoded)
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
  "intent": "one of: find_nearby, distance, analyze_area, check_relationship, elevation, weather, air_quality, fire_detection, environmental",
  "params": {{
    "amenity_type": "type of thing to find (hospital, school, park, etc.) or null",
    "radius_m": radius in meters or 3000,
    "relationship": "contains, intersects, within, or null"
  }}
}}

Intent guide:
- elevation: how high a place is (elevation, altitude, height above sea level)
- weather: questions about temperature, rain, forecast, climate conditions
- air_quality: questions about pollution, PM2.5, air quality, smog
- fire_detection: questions about wildfires, active fires, burning
- environmental: broad questions about environment, conditions, or livability that combine multiple data sources"""

        try:
            resp = httpx.post(
                f"{self._ollama_url}/api/chat",
                json={
                    "model": self._model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "options": {"num_predict": 200},  # bounded: the parsed question is a short JSON object; JSON mode can otherwise pad with blank space until the timeout
                    "format": "json",
                },
                timeout=60,
            )
            resp.raise_for_status()
            content = resp.json().get("message", {}).get("content", "{}")
            parsed = json.loads(content)
            params = parsed.get("params") or {}
            # A distance written in the question is a fact, not something for the model to guess:
            # it sometimes drops "within 2km" and falls back to its default 3000.
            stated = self._stated_radius(goal)
            if stated:
                params["radius_m"] = stated
            # "How high is ...?" has no list intent the model reliably picks; it fell back to a nearby search
            if self._asks_elevation(goal) and parsed.get("intent") != "distance":
                parsed["intent"] = "elevation"
            # The question's wording decides the relationship, like a stated distance: live, the model
            # returned the string "null", and "contains" for "Is Federation Square in Melbourne?".
            if parsed.get("intent") == "check_relationship":
                worded = self._stated_relationship(goal)
                if worded:
                    params["relationship"] = worded
                elif params.get("relationship") not in self._RELATIONSHIPS:
                    params["relationship"] = "within"
            return (
                parsed.get("locations", []),
                parsed.get("intent", "find_nearby"),
                params,
            )
        except Exception:
            return self._fallback_parse(goal)

    @classmethod
    def _separate_place_types(
        cls, locations: list[str], params: dict[str, Any],
    ) -> tuple[list[str], dict[str, Any]]:
        """Keep place names and things-to-find apart.

        The model sometimes lists "hospitals" or "schools" as locations (they were then geocoded to a
        hospital in New York and a place in the West Bank) or joins types as "hospital,school".
        """
        raw = params.get("amenity_type")
        parts = raw if isinstance(raw, list) else re.split(r"\s*(?:,|/|&|\band\b)\s*", str(raw or ""))
        types: list[str] = []
        for part in parts:
            word = str(part).strip().lower()
            if word and word not in ("null", "none"):
                types.append(cls._AMENITIES.get(word, word.rstrip("s") if word.endswith("s") and len(word) > 3 else word))
        places = []
        for loc in locations:
            key = str(loc).strip().lower()
            if key in cls._AMENITIES:
                types.append(cls._AMENITIES[key])
            else:
                places.append(loc)
        out = dict(params)
        unique = list(dict.fromkeys(types))
        out["amenity_type"] = (unique[0] if len(unique) == 1 else unique) if unique else None
        return places, out

    def _boundary(self, name: str) -> dict[str, Any] | None:
        """A place's boundary from OpenStreetMap (Nominatim), or None (see agents.amenities.place_boundary)."""
        from geospark.agents.amenities import place_boundary

        return place_boundary(name)

    _RELATIONSHIPS: ClassVar[frozenset[str]] = frozenset(
        {"contains", "within", "intersects", "touches", "crosses", "overlaps", "disjoint"})

    @staticmethod
    def _stated_relationship(goal: str) -> str | None:
        """The relationship a question asks about, from its wording ("Is A inside B?" -> within)."""
        g = goal.lower()
        if re.search(r"\b(?:contains?|containing|include[sd]?)\b", g):
            return "contains"
        if re.search(r"\b(?:inside|within|in)\b", g):
            return "within"
        for word in ("intersects", "overlaps", "touches", "crosses", "disjoint"):
            if word.rstrip("s") in g:
                return word.rstrip("s") + ("s" if word != "disjoint" else "")
        return None

    @staticmethod
    def _asks_elevation(goal: str) -> bool:
        return bool(re.search(r"\b(?:elevation|altitude|how high|height above sea|above sea level)\b", goal, re.I))

    @classmethod
    def _join_comma_places(cls, goal: str, locations: list[str], intent: str) -> list[str]:
        """The model splits "Mount Wellington, Hobart" into two places; the question wrote one.

        Consecutive names joined by a comma in the question are merged, unless a two-place question
        (a distance) would be left with one place.
        """
        if len(locations) < 2:
            return locations
        merged = [str(locations[0])]
        for loc in locations[1:]:
            pattern = re.escape(merged[-1].split(", ")[-1]) + r"\s*,\s*" + re.escape(str(loc))
            if re.search(pattern, goal, re.I):
                merged[-1] = f"{merged[-1]}, {loc}"
            else:
                merged.append(str(loc))
        if intent in cls._SINGLE_PLACE_INTENTS or len(merged) >= 2:
            return merged
        return locations

    @staticmethod
    def _stated_radius(goal: str) -> int | None:
        """A search distance written in the question ("within 2km", "500 m", "1.5 kilometres"), in metres."""
        match = re.search(r"(\d+(?:\.\d+)?)\s*(km|kilometres?|kilometers?|m|metres?|meters?)\b", goal, re.I)
        if not match:
            return None
        value, unit = float(match.group(1)), match.group(2).lower()
        return int(value * 1000 if unit.startswith("k") else value)

    # Words that start a sentence or link phrases but are never place names on their own
    _NOT_PLACES: ClassVar[frozenset[str]] = frozenset({
        "find", "what", "where", "how", "is", "are", "the", "within", "near", "from", "to",
        "all", "any", "show", "list", "which", "who", "get", "give", "me", "and", "or",
        "between", "around", "in", "of", "a", "an", "nearest", "closest", "best",
        "check", "does", "do", "can", "tell", "compute", "calculate",
        # topic words that often open a question ("Weather in Paris")
        "weather", "forecast", "temperature", "air", "pollution", "fires", "wildfires",
        "distance", "nearby", "local", "current",
    })
    # Intents that concern one place: "Federation Square, Melbourne" is one address there
    _SINGLE_PLACE_INTENTS: ClassVar[frozenset[str]] = frozenset({
        "find_nearby", "elevation", "weather", "air_quality", "fire_detection", "analyze_area", "environmental",
    })
    # Lower-case words allowed inside a multi-word place name ("Bay of Islands", "Rio de Janeiro")
    _PLACE_CONNECTORS: ClassVar[frozenset[str]] = frozenset({"of", "de", "du", "la", "le", "del", "da", "di", "van", "von", "upon"})
    _AMENITIES: ClassVar[dict[str, str]] = {
        "hospital": "hospital", "hospitals": "hospital", "clinic": "clinic", "clinics": "clinic",
        "school": "school", "schools": "school", "university": "university", "universities": "university",
        "pharmacy": "pharmacy", "pharmacies": "pharmacy", "park": "park", "parks": "park",
        "cafe": "cafe", "cafes": "cafe", "coffee": "cafe", "restaurant": "restaurant",
        "restaurants": "restaurant", "library": "library", "libraries": "library",
        "supermarket": "supermarket", "supermarkets": "supermarket", "bank": "bank", "banks": "bank",
        "police": "police", "fire station": "fire_station", "fire stations": "fire_station",
        "bus stop": "bus_stop", "bus stops": "bus_stop",
        "station": "station", "stations": "station", "museum": "museum", "museums": "museum",
        "hotel": "hotel", "hotels": "hotel", "playground": "playground", "playgrounds": "playground",
        "gym": "fitness_centre", "gyms": "fitness_centre", "doctor": "doctors", "doctors": "doctors",
    }

    @classmethod
    def _fallback_parse(cls, goal: str) -> tuple[list[str], str, dict[str, Any]]:
        """Rule-based goal parsing, used when the LLM is unavailable.

        Groups consecutive capitalised words into one place ("Eiffel Tower", "Rio de
        Janeiro"), and reads a radius ("2km", "500 m") and an amenity type from the text.
        """
        import re

        tokens = re.findall(r"[\w'.-]+|[,;:?!()]", goal)
        locations: list[str] = []
        joined_by_comma: list[bool] = []  # was location i separated from i-1 only by a comma?
        current: list[str] = []
        since_last = ""  # punctuation/words seen since the previous location ended

        def flush() -> None:
            nonlocal since_last
            while current and current[-1].lower() in cls._PLACE_CONNECTORS:
                current.pop()  # a trailing connector isn't part of the name
            if current:
                joined_by_comma.append(bool(locations) and since_last == ",")
                locations.append(" ".join(current))
                since_last = ""
            current.clear()

        for raw in tokens:
            word = raw.strip(".")
            if not word or not (word[0].isalpha() or word[0].isdigit()):
                flush()
                since_last += raw if raw in ",;:" else " "
                continue
            lower = word.lower()
            starts_place = word[0].isupper() and lower not in cls._NOT_PLACES and lower not in cls._AMENITIES
            if starts_place or (current and word[0].isupper()) or (current and lower in cls._PLACE_CONNECTORS):
                current.append(word)
            else:
                flush()
                since_last += " "
        flush()

        params: dict[str, Any] = {"radius_m": cls._stated_radius(goal) or 3000}

        gl = goal.lower()
        for phrase in sorted(cls._AMENITIES, key=len, reverse=True):
            if re.search(rf"\b{re.escape(phrase)}\b", gl):
                params["amenity_type"] = cls._AMENITIES[phrase]
                break

        intent = "find_nearby"
        if "distance" in gl or "how far" in gl or " far " in f" {gl} ":
            intent = "distance"
        elif "contain" in gl or "inside" in gl or (re.match(r"\s*(?:is|are)\s+.+\b(?:in|within)\b", gl)
                                                        and "amenity_type" not in params and not cls._stated_radius(goal)):
            intent = "check_relationship"
            params["relationship"] = cls._stated_relationship(goal)
        elif cls._asks_elevation(goal):
            intent = "elevation"
        elif "weather" in gl or "temperature" in gl or "forecast" in gl or "rain" in gl:
            intent = "weather"
        elif "air quality" in gl or "pollution" in gl or "pm2.5" in gl or "smog" in gl:
            intent = "air_quality"
        elif ("fire" in gl and "fire station" not in gl) or "wildfire" in gl or "burning" in gl:
            intent = "fire_detection"
        elif "environment" in gl or "livability" in gl or "conditions" in gl:
            intent = "environmental"

        # "Federation Square, Melbourne" and "Paris, France" each name one place. Merge
        # comma-joined names, unless a two-place question would be left with one place.
        if len(locations) > 1:
            merged: list[str] = [locations[0]]
            for loc, comma in zip(locations[1:], joined_by_comma[1:], strict=True):
                if comma:
                    merged[-1] = f"{merged[-1]}, {loc}"
                else:
                    merged.append(loc)
            if intent in cls._SINGLE_PLACE_INTENTS or len(merged) >= 2:
                locations = merged

        return locations, intent, params

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
                    "warnings": (result.get("metadata") or {}).get("warnings") or [],
                }
        return {"coordinates": None, "error": "Geocoding failed"}

    # Looked up when an area is analysed, or nearby things are asked for without a type
    EVERYDAY_SERVICES: ClassVar[list[str]] = ["hospital", "school", "pharmacy", "supermarket", "cafe"]

    def _find_nearby(
        self,
        result: AgentResult,
        geocoded: dict[str, dict],
        params: dict[str, Any],
    ) -> None:
        """Find nearby amenities for geocoded locations (OpenStreetMap, Overture Maps as fallback)."""
        amenity = params.get("amenity_type")
        if isinstance(amenity, list):
            types = [a for a in amenity if a] or list(self.EVERYDAY_SERVICES)
        else:
            types = [amenity] if amenity else list(self.EVERYDAY_SERVICES)
        label = ", ".join(types)
        radius = params.get("radius_m", 3000)

        for loc_name, geo in geocoded.items():
            coords = geo.get("coordinates")
            if not coords:
                continue

            t0 = time.time()
            lon, lat = coords[0], coords[1]
            try:
                lookup = find_amenities(lat, lon, radius, types, self._overpass)
                searched = lookup.radius_m
                center = {"type": "Point", "coordinates": [lon, lat]}
                nearby = []
                counts: dict[str, int] = {}
                for kind, entities in lookup.by_type.items():
                    for ent in entities:
                        dist = SpatialReasoner.calculate_distance(center, ent.geometry)
                        if dist <= searched:
                            counts[kind] = counts.get(kind, 0) + 1
                            nearby.append({
                                "name": ent.name,
                                "type": kind,
                                "distance_m": round(dist),
                                "coordinates": ent.geometry.get("coordinates"),
                            })
                nearby.sort(key=lambda x: x["distance_m"])

                result.findings.setdefault("nearby", {})[loc_name] = {
                    "amenity_type": label,
                    "radius_m": searched,
                    "count": len(nearby),
                    "by_type": counts,
                    "items": nearby[:20],
                    "source": lookup.source,
                }
                for caveat in lookup.warnings:
                    if caveat not in result.findings.setdefault("caveats", []):
                        result.findings["caveats"].append(caveat)
                if lookup.unavailable:  # unknown, not "none": surfaces in the summary's fixed gap note
                    result.steps.append(AgentStep(
                        action="find_nearby",
                        description=f"{', '.join(lookup.unavailable)} near {loc_name}",
                        error="not retrieved: OpenStreetMap was unavailable and no reliable fallback exists",
                    ))
                result.steps.append(AgentStep(
                    action="find_nearby",
                    description=f"Found {len(nearby)} {label} within {round(searched)}m of {loc_name} "
                                f"({'OpenStreetMap' if lookup.source == 'openstreetmap-overpass' else 'Overture Maps'})",
                    result={"count": len(nearby), "by_type": counts,
                            "nearest": nearby[0]["name"] if nearby else None},
                    duration_s=round(time.time() - t0, 1),
                ))
            except Exception as e:
                result.steps.append(AgentStep(
                    action="find_nearby",
                    description=f"Search {label} near {loc_name}",
                    error=str(e),
                    duration_s=round(time.time() - t0, 1),
                ))

    def _get_elevations(self, result: AgentResult, geocoded: dict[str, dict]) -> None:
        """Ground elevation at each geocoded place (Copernicus DEM, Open Elevation as fallback)."""
        elevations = []
        for loc_name, geo in geocoded.items():
            coords = geo.get("coordinates")
            if not coords:
                continue
            t0 = time.time()
            reply = self._launcher.handle_tool_call("get_elevation", {
                "explanation": f"Elevation of {loc_name}", "latitude": coords[1], "longitude": coords[0],
            })
            body = reply.get("result") if reply.get("status") == "success" else None
            if not body or body.get("elevation_m") is None:
                result.steps.append(AgentStep(action="elevation", description=f"Elevation of {loc_name}",
                                              error="no elevation data", duration_s=round(time.time() - t0, 1)))
                continue
            elevations.append({"place": geo.get("name", loc_name), "elevation_m": body["elevation_m"],
                               "coordinates": coords})
            result.steps.append(AgentStep(
                action="elevation", description=f"{loc_name}: {body['elevation_m']} m above sea level",
                result=body, duration_s=round(time.time() - t0, 1),
            ))
        if elevations:
            result.findings["elevations"] = elevations
            result.findings.setdefault("caveats", []).append(
                "Elevation is the ground height at the geocoded point of each place, from a 30 m terrain "
                "model; for a mountain this can be below the summit if the point is not the peak.")

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
        relationship = params.get("relationship")
        if relationship not in self._RELATIONSHIPS:
            relationship = "within"
        locations = list(geocoded.items())

        for i, (name_a, geo_a) in enumerate(locations):
            for name_b, geo_b in locations[i + 1:]:
                geom_a = geo_a.get("geometry")
                geom_b = geo_b.get("geometry")
                if not geom_a or not geom_b:
                    continue
                # Geocoding gives a point; "is A inside B" needs B's boundary. A point can't contain
                # anything, so comparing two points would always answer "no".
                needs_area = {"within": ["b"], "contains": ["a"]}.get(relationship, ["a", "b"])
                missing = []
                for side, name, geo in (("a", name_a, geo_a), ("b", name_b, geo_b)):
                    if side in needs_area and (geo.get("geometry") or {}).get("type") == "Point":
                        boundary = self._boundary(name)
                        if boundary:
                            geo["geometry"] = boundary
                            result.findings.setdefault("caveats", []).append(
                                f"{name}: boundary from OpenStreetMap (Nominatim), simplified.")
                        else:
                            missing.append(name)
                if missing and len(missing) == len(needs_area):
                    result.steps.append(AgentStep(
                        action="check_relationship",
                        description=f"Check {relationship}: {name_a} vs {name_b}",
                        error=f"no boundary found for {', '.join(missing)}, and a single point cannot "
                              "contain anything, so this can't be checked",
                    ))
                    continue
                geom_a, geom_b = geo_a.get("geometry"), geo_b.get("geometry")

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

    def _get_weather(
        self,
        result: AgentResult,
        geocoded: dict[str, dict],
    ) -> None:
        """Fetch weather data for geocoded locations."""

        from geospark.data_channels.weather import WeatherChannel

        for loc_name, geo in geocoded.items():
            coords = geo.get("coordinates")
            if not coords:
                continue
            lon, lat = coords[0], coords[1]
            t0 = time.time()
            try:

                async def _run(_lat=lat, _lon=lon):
                    ch = WeatherChannel()
                    return await ch.search(lat=_lat, lon=_lon, filters={"forecast_days": 3})

                ch_result = run_sync(_run())
                if ch_result.errors:
                    result.steps.append(AgentStep(
                        action="weather",
                        description=f"Weather for {loc_name}",
                        error=ch_result.errors[0],
                        duration_s=round(time.time() - t0, 1),
                    ))
                    continue

                current = next(
                    (f for f in ch_result.features if f.get("type") == "current_weather"),
                    None,
                )
                forecasts = [
                    f for f in ch_result.features if f.get("type") == "daily_forecast"
                ]
                weather_data = {
                    "current": current,
                    "forecast": forecasts,
                }
                result.findings.setdefault("weather", {})[loc_name] = weather_data
                desc = (
                    f"Weather at {loc_name}: "
                    f"{current.get('weather_description', '?')}, "
                    f"{current.get('temperature_c')}°C"
                    if current
                    else f"Weather data retrieved for {loc_name}"
                )
                result.steps.append(AgentStep(
                    action="weather",
                    description=desc,
                    result=weather_data,
                    duration_s=round(time.time() - t0, 1),
                ))
            except Exception as e:
                result.steps.append(AgentStep(
                    action="weather",
                    description=f"Weather for {loc_name}",
                    error=str(e),
                    duration_s=round(time.time() - t0, 1),
                ))

    def _get_air_quality(
        self,
        result: AgentResult,
        geocoded: dict[str, dict],
    ) -> None:
        """Fetch air quality data for geocoded locations."""

        from geospark.data_channels.air_quality import AirQualityChannel

        for loc_name, geo in geocoded.items():
            coords = geo.get("coordinates")
            if not coords:
                continue
            lon, lat = coords[0], coords[1]
            t0 = time.time()
            try:

                async def _run(_lat=lat, _lon=lon):
                    ch = AirQualityChannel()
                    return await ch.search(lat=_lat, lon=_lon, filters={"limit": 5})

                ch_result = run_sync(_run())
                if ch_result.errors:
                    result.steps.append(AgentStep(
                        action="air_quality",
                        description=f"Air quality for {loc_name}",
                        error=ch_result.errors[0],
                        duration_s=round(time.time() - t0, 1),
                    ))
                    continue

                stations = ch_result.features
                result.findings.setdefault("air_quality", {})[loc_name] = {
                    "stations": stations,
                    "count": len(stations),
                }
                if stations:
                    aqi = stations[0].get("aqi_category", "?")
                    desc = f"Air quality at {loc_name}: {aqi} ({len(stations)} stations)"
                else:
                    desc = f"No air quality stations found near {loc_name}"
                result.steps.append(AgentStep(
                    action="air_quality",
                    description=desc,
                    result={"stations_found": len(stations)},
                    duration_s=round(time.time() - t0, 1),
                ))
            except Exception as e:
                result.steps.append(AgentStep(
                    action="air_quality",
                    description=f"Air quality for {loc_name}",
                    error=str(e),
                    duration_s=round(time.time() - t0, 1),
                ))

    def _detect_fires(
        self,
        result: AgentResult,
        geocoded: dict[str, dict],
    ) -> None:
        """Check for active fires near geocoded locations."""

        from geospark.data_channels.fires import FiresChannel

        for loc_name, geo in geocoded.items():
            coords = geo.get("coordinates")
            if not coords:
                continue
            lon, lat = coords[0], coords[1]
            t0 = time.time()
            try:

                async def _run(_lat=lat, _lon=lon):
                    ch = FiresChannel()
                    return await ch.search(lat=_lat, lon=_lon, filters={"days": 2})

                ch_result = run_sync(_run())
                if ch_result.errors:
                    result.steps.append(AgentStep(
                        action="fire_detection",
                        description=f"Fire detection for {loc_name}",
                        error=ch_result.errors[0],
                        duration_s=round(time.time() - t0, 1),
                    ))
                    continue

                fires = ch_result.features
                result.findings.setdefault("fires", {})[loc_name] = {
                    "detections": fires,
                    "count": len(fires),
                }
                if fires:
                    desc = f"Active fires near {loc_name}: {len(fires)} detections"
                else:
                    desc = f"No active fires detected near {loc_name}"
                result.steps.append(AgentStep(
                    action="fire_detection",
                    description=desc,
                    result={"fires_detected": len(fires)},
                    duration_s=round(time.time() - t0, 1),
                ))
            except Exception as e:
                result.steps.append(AgentStep(
                    action="fire_detection",
                    description=f"Fire detection for {loc_name}",
                    error=str(e),
                    duration_s=round(time.time() - t0, 1),
                ))

    def _generate_summary(self, result: AgentResult) -> str:
        """Generate a human-readable summary of the findings."""
        import httpx

        findings_str = json.dumps(result.findings, indent=2, default=str)[:3000]
        steps_str = "\n".join(
            f"- {s.description}" for s in result.steps if not s.error
        )

        failed = [s.description for s in result.steps if s.error]
        # A failed lookup is stated in fixed wording after the model's text, so it can never be
        # phrased as "there are none" or filled in from general knowledge.
        gap_note = (" Not included because the data could not be retrieved: " + "; ".join(failed) + ".") if failed else ""
        found_something = any(k not in ("geocoded", "caveats") for k in result.findings)
        if failed and not found_something:
            # Nothing but failures to report: a model asked to summarise this tends to say
            # "none were found", which is wrong. Say plainly what could not be done.
            reasons = "; ".join(f"{s.description} ({s.error})" for s in result.steps if s.error)
            needs_setup = any(("not set" in (s.error or "")) or ("API_KEY" in (s.error or "")) for s in result.steps)
            advice = ("This server has not been given the free API key it needs for that."
                      if needs_setup else "Please try again in a few minutes.")
            return f"This could not be answered: {reasons}. {advice}"

        prompt = f"""Summarize these spatial analysis findings in 2-4 sentences.
Use ONLY the facts listed below and be specific with their numbers and distances.
Do not add general knowledge about the place or anything that is not listed.
Do not mention anything the steps below did not find.

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
                    "options": {"num_predict": 320},  # bounded: a 2-4 sentence summary
                },
                timeout=60,
            )
            resp.raise_for_status()
            return resp.json().get("message", {}).get("content", "").strip() + gap_note
        except Exception:
            # Fallback: build summary from findings
            parts = [f"Analysis for: {result.goal}"]
            if "distances" in result.findings:
                for d in result.findings["distances"]:
                    parts.append(f"{d['from']} to {d['to']}: {d['distance_km']} km")
            for e in result.findings.get("elevations", []):
                parts.append(f"{e['place']}: {e['elevation_m']} m above sea level")
            for rel in result.findings.get("relationships", []):
                parts.append(f"{rel['a']} {rel['relationship']} {rel['b']}: {'yes' if rel['result'] else 'no'}")
            if "nearby" in result.findings:
                for loc, data in result.findings["nearby"].items():
                    parts.append(
                        f"Found {data['count']} {data['amenity_type']}(s) "
                        f"within {data['radius_m']}m of {loc}"
                    )
            return ". ".join(parts) + gap_note
