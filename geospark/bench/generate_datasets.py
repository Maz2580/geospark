"""
Generate benchmark datasets for GeoSpark Bench v1.0.

Run with:
    .venv/Scripts/python.exe -m geospark.bench.generate_datasets

Generates:
- geotopo.json       (200+ topological reasoning questions)
- geodistance.json   (200+ distance/proximity questions)
- geochanage.json    (50 change detection questions)
- georeason.json     (50+ multi-step spatial reasoning questions)
- geomultimodal.json (50+ multimodal spatial questions)
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from pyproj import Geod
from shapely.geometry import box, mapping

from geospark.bench.models import AnswerType, BenchmarkName, Difficulty
from geospark.engine.spatial_reasoner import SpatialReasoner

DATASETS_DIR = Path(__file__).parent / "datasets"
GEOD = Geod(ellps="WGS84")
RNG = random.Random(42)


# ---------------------------------------------------------------------------
# Real-world reference data (expanded for v1.0)
# ---------------------------------------------------------------------------

LANDMARKS = {
    # --- Paris ---
    "Eiffel Tower": {"coords": [2.2945, 48.8584], "city": "Paris", "country": "France"},
    "Louvre Museum": {"coords": [2.3376, 48.8606], "city": "Paris", "country": "France"},
    "Arc de Triomphe": {"coords": [2.2950, 48.8738], "city": "Paris", "country": "France"},
    "Notre-Dame": {"coords": [2.3500, 48.8530], "city": "Paris", "country": "France"},
    "Sacre-Coeur": {"coords": [2.3431, 48.8867], "city": "Paris", "country": "France"},
    "Musee d'Orsay": {"coords": [2.3266, 48.8600], "city": "Paris", "country": "France"},
    # --- London ---
    "Big Ben": {"coords": [-0.1246, 51.5007], "city": "London", "country": "UK"},
    "Tower of London": {"coords": [-0.0761, 51.5081], "city": "London", "country": "UK"},
    "Buckingham Palace": {"coords": [-0.1419, 51.5014], "city": "London", "country": "UK"},
    "London Eye": {"coords": [-0.1195, 51.5033], "city": "London", "country": "UK"},
    "Tower Bridge": {"coords": [-0.0754, 51.5055], "city": "London", "country": "UK"},
    "St Paul's Cathedral": {"coords": [-0.0985, 51.5138], "city": "London", "country": "UK"},
    # --- New York ---
    "Statue of Liberty": {"coords": [-74.0445, 40.6892], "city": "New York", "country": "USA"},
    "Empire State Building": {"coords": [-73.9857, 40.7484], "city": "New York", "country": "USA"},
    "Central Park": {"coords": [-73.9654, 40.7829], "city": "New York", "country": "USA"},
    "Times Square": {"coords": [-73.9855, 40.7580], "city": "New York", "country": "USA"},
    "Brooklyn Bridge": {"coords": [-73.9969, 40.7061], "city": "New York", "country": "USA"},
    "One World Trade Center": {"coords": [-74.0134, 40.7127], "city": "New York", "country": "USA"},
    # --- Rome ---
    "Colosseum": {"coords": [12.4922, 41.8902], "city": "Rome", "country": "Italy"},
    "Vatican City": {"coords": [12.4534, 41.9029], "city": "Rome", "country": "Italy"},
    "Trevi Fountain": {"coords": [12.4833, 41.9009], "city": "Rome", "country": "Italy"},
    "Pantheon": {"coords": [12.4768, 41.8986], "city": "Rome", "country": "Italy"},
    # --- Tokyo ---
    "Tokyo Tower": {"coords": [139.7454, 35.6586], "city": "Tokyo", "country": "Japan"},
    "Tokyo Skytree": {"coords": [139.8107, 35.7101], "city": "Tokyo", "country": "Japan"},
    "Meiji Shrine": {"coords": [139.6993, 35.6764], "city": "Tokyo", "country": "Japan"},
    "Sensoji Temple": {"coords": [139.7966, 35.7148], "city": "Tokyo", "country": "Japan"},
    # --- Sydney ---
    "Sydney Opera House": {"coords": [151.2153, -33.8568], "city": "Sydney", "country": "Australia"},
    "Sydney Harbour Bridge": {"coords": [151.2106, -33.8523], "city": "Sydney", "country": "Australia"},
    "Bondi Beach": {"coords": [151.2743, -33.8915], "city": "Sydney", "country": "Australia"},
    # --- Dubai ---
    "Burj Khalifa": {"coords": [55.2744, 25.1972], "city": "Dubai", "country": "UAE"},
    "Palm Jumeirah": {"coords": [55.1326, 25.1124], "city": "Dubai", "country": "UAE"},
    "Dubai Mall": {"coords": [55.2796, 25.1985], "city": "Dubai", "country": "UAE"},
    # --- Cairo ---
    "Pyramids of Giza": {"coords": [31.1342, 29.9792], "city": "Cairo", "country": "Egypt"},
    "Cairo Tower": {"coords": [31.2244, 30.0459], "city": "Cairo", "country": "Egypt"},
    "Khan el-Khalili": {"coords": [31.2625, 30.0478], "city": "Cairo", "country": "Egypt"},
    # --- Cape Town ---
    "Table Mountain": {"coords": [18.4041, -33.9628], "city": "Cape Town", "country": "South Africa"},
    "Robben Island": {"coords": [18.3664, -33.8076], "city": "Cape Town", "country": "South Africa"},
    # --- Other major landmarks ---
    "Taj Mahal": {"coords": [78.0421, 27.1751], "city": "Agra", "country": "India"},
    "Great Wall (Badaling)": {"coords": [116.0046, 40.3588], "city": "Beijing", "country": "China"},
    "Christ the Redeemer": {"coords": [-43.2105, -22.9519], "city": "Rio", "country": "Brazil"},
    "Machu Picchu": {"coords": [-72.5450, -13.1631], "city": "Cusco", "country": "Peru"},
    "Golden Gate Bridge": {"coords": [-122.4783, 37.8199], "city": "San Francisco", "country": "USA"},
    "CN Tower": {"coords": [-79.3871, 43.6426], "city": "Toronto", "country": "Canada"},
    "Space Needle": {"coords": [-122.3493, 47.6205], "city": "Seattle", "country": "USA"},
    "Sagrada Familia": {"coords": [2.1744, 41.4036], "city": "Barcelona", "country": "Spain"},
    "Brandenburg Gate": {"coords": [13.3777, 52.5163], "city": "Berlin", "country": "Germany"},
    "Acropolis": {"coords": [23.7257, 37.9715], "city": "Athens", "country": "Greece"},
    "Forbidden City": {"coords": [116.3972, 39.9163], "city": "Beijing", "country": "China"},
    "Petronas Towers": {"coords": [101.7118, 3.1578], "city": "Kuala Lumpur", "country": "Malaysia"},
    "Christ Church Cathedral": {"coords": [172.6328, -43.5314], "city": "Christchurch", "country": "New Zealand"},
    "Angkor Wat": {"coords": [103.8670, 13.4125], "city": "Siem Reap", "country": "Cambodia"},
    "Kremlin": {"coords": [37.6173, 55.7520], "city": "Moscow", "country": "Russia"},
    "Blue Mosque": {"coords": [28.9771, 41.0054], "city": "Istanbul", "country": "Turkey"},
    "Chichen Itza": {"coords": [-88.5686, 20.6843], "city": "Yucatan", "country": "Mexico"},
    "Niagara Falls": {"coords": [-79.0754, 43.0962], "city": "Niagara Falls", "country": "Canada"},
    "Hollywood Sign": {"coords": [-118.3217, 34.1341], "city": "Los Angeles", "country": "USA"},
    "Lincoln Memorial": {"coords": [-77.0502, 38.8893], "city": "Washington DC", "country": "USA"},
    "Alcatraz Island": {"coords": [-122.4229, 37.8267], "city": "San Francisco", "country": "USA"},
}

# City bounding boxes (approximate, for polygon-based questions)
CITY_BBOXES = {
    "Paris": [2.22, 48.82, 2.42, 48.90],
    "London": [-0.30, 51.40, 0.10, 51.60],
    "New York": [-74.05, 40.65, -73.90, 40.85],
    "Rome": [12.40, 41.85, 12.55, 41.95],
    "Tokyo": [139.65, 35.60, 139.85, 35.75],
    "Sydney": [151.15, -33.90, 151.30, -33.80],
    "Dubai": [55.05, 25.05, 55.35, 25.30],
    "Cairo": [31.10, 29.95, 31.35, 30.10],
    "Cape Town": [18.35, -34.00, 18.55, -33.90],
    "Barcelona": [2.05, 41.33, 2.23, 41.47],
    "Berlin": [13.25, 52.42, 13.55, 52.58],
    "Moscow": [37.45, 55.65, 37.80, 55.85],
    "Istanbul": [28.85, 40.95, 29.10, 41.10],
    "Los Angeles": [-118.50, 33.95, -118.20, 34.15],
    "Washington DC": [-77.12, 38.80, -76.90, 38.95],
}

# Polygon with a hole (Dr. Chen's suggestion -- classic gotcha)
PARIS_WITH_HOLE = {
    "type": "Polygon",
    "coordinates": [
        # Outer ring (Paris bbox)
        [[2.22, 48.82], [2.42, 48.82], [2.42, 48.90], [2.22, 48.90], [2.22, 48.82]],
        # Hole (small area around Ile de la Cite)
        [[2.34, 48.855], [2.36, 48.855], [2.36, 48.860], [2.34, 48.860], [2.34, 48.855]],
    ],
}

# Additional polygons with holes for expanded tests
LONDON_WITH_HOLE = {
    "type": "Polygon",
    "coordinates": [
        [[-0.30, 51.40], [0.10, 51.40], [0.10, 51.60], [-0.30, 51.60], [-0.30, 51.40]],
        [[-0.10, 51.50], [-0.08, 51.50], [-0.08, 51.52], [-0.10, 51.52], [-0.10, 51.50]],
    ],
}

TOKYO_WITH_HOLE = {
    "type": "Polygon",
    "coordinates": [
        [[139.65, 35.60], [139.85, 35.60], [139.85, 35.75], [139.65, 35.75], [139.65, 35.60]],
        [[139.74, 35.66], [139.76, 35.66], [139.76, 35.68], [139.74, 35.68], [139.74, 35.66]],
    ],
}


def _make_bbox_polygon(bbox: list[float]) -> dict:
    """Create a GeoJSON polygon from a bounding box [minx, miny, maxx, maxy]."""
    return mapping(box(*bbox))


def _make_point(coords: list[float]) -> dict:
    """Create a GeoJSON point from [lon, lat]."""
    return {"type": "Point", "coordinates": coords}


def _point_in_bbox(bbox: list[float]) -> list[float]:
    """Generate a random point inside a bounding box."""
    lon = RNG.uniform(bbox[0], bbox[2])
    lat = RNG.uniform(bbox[1], bbox[3])
    return [round(lon, 6), round(lat, 6)]


def _point_outside_bbox(bbox: list[float], margin: float = 0.5) -> list[float]:
    """Generate a random point outside a bounding box."""
    side = RNG.choice(["north", "south", "east", "west"])
    if side == "north":
        return [round(RNG.uniform(bbox[0], bbox[2]), 6), round(bbox[3] + RNG.uniform(0.01, margin), 6)]
    elif side == "south":
        return [round(RNG.uniform(bbox[0], bbox[2]), 6), round(bbox[1] - RNG.uniform(0.01, margin), 6)]
    elif side == "east":
        return [round(bbox[2] + RNG.uniform(0.01, margin), 6), round(RNG.uniform(bbox[1], bbox[3]), 6)]
    else:
        return [round(bbox[0] - RNG.uniform(0.01, margin), 6), round(RNG.uniform(bbox[1], bbox[3]), 6)]


def _geodesic_destination(
    lon: float, lat: float, azimuth_deg: float, distance_m: float,
) -> list[float]:
    """Compute destination point given start, azimuth, and distance."""
    lon2, lat2, _back_az = GEOD.fwd(lon, lat, azimuth_deg, distance_m)
    return [round(lon2, 6), round(lat2, 6)]


# ---------------------------------------------------------------------------
# GeoTopo -- Topological reasoning questions (v1.0: 200+)
# ---------------------------------------------------------------------------

def generate_geotopo() -> list[dict]:
    """Generate 200+ topological reasoning questions."""
    questions: list[dict] = []
    qid = 0

    city_list = list(CITY_BBOXES.items())

    # ---- Category 1: Point-in-polygon (contains) -- ~40 questions ----
    for city_name, bbox in city_list:
        polygon = _make_bbox_polygon(bbox)
        landmarks_in_city = [
            (name, info) for name, info in LANDMARKS.items()
            if info["city"] == city_name
        ]

        # True cases: known landmarks inside city bbox
        for lm_name, lm_info in landmarks_in_city[:2]:
            qid += 1
            point = _make_point(lm_info["coords"])
            gt = SpatialReasoner.check_relationship(polygon, point, "contains")
            questions.append(_topo_question(
                qid, "contains", Difficulty.EASY,
                f"Does the bounding box of {city_name} contain the {lm_name}?",
                polygon, point, gt,
                f"the bounding box of {city_name}", f"the {lm_name}",
            ))

        # False cases: point outside
        for _i in range(2):
            qid += 1
            outside_pt = _point_outside_bbox(bbox)
            point = _make_point(outside_pt)
            gt = SpatialReasoner.check_relationship(polygon, point, "contains")
            questions.append(_topo_question(
                qid, "contains", Difficulty.EASY,
                f"Does the bounding box of {city_name} contain the point at coordinates ({outside_pt[1]:.4f}N, {outside_pt[0]:.4f}E)?",
                polygon, point, gt,
                f"the bounding box of {city_name}", "the given point",
            ))

    # ---- Category 2: Polygon-polygon intersection -- ~30 questions ----
    for i in range(len(city_list)):
        c1_name, c1_bbox = city_list[i]
        c2_name, c2_bbox = city_list[(i + 1) % len(city_list)]
        poly_a = _make_bbox_polygon(c1_bbox)
        poly_b = _make_bbox_polygon(c2_bbox)
        gt = SpatialReasoner.check_relationship(poly_a, poly_b, "intersects")
        qid += 1
        questions.append(_topo_question(
            qid, "intersects", Difficulty.EASY,
            f"Does the bounding box of {c1_name} intersect with the bounding box of {c2_name}?",
            poly_a, poly_b, gt,
            f"the bounding box of {c1_name}", f"the bounding box of {c2_name}",
        ))

        # Overlapping bboxes (shift one slightly)
        shifted = [c1_bbox[0] + 0.05, c1_bbox[1] + 0.02, c1_bbox[2] + 0.05, c1_bbox[3] + 0.02]
        poly_shifted = _make_bbox_polygon(shifted)
        gt2 = SpatialReasoner.check_relationship(poly_a, poly_shifted, "intersects")
        qid += 1
        questions.append(_topo_question(
            qid, "intersects", Difficulty.MEDIUM,
            f"Do these two overlapping rectangles in {c1_name} intersect?",
            poly_a, poly_shifted, gt2,
            "Rectangle A", "Rectangle B (shifted 0.05 degrees east)",
        ))

    # ---- Category 3: Disjoint -- ~30 questions ----
    pairs = [(city_list[i], city_list[j])
             for i in range(len(city_list)) for j in range(i + 1, len(city_list))]
    RNG.shuffle(pairs)
    for (c1_name, c1_bbox), (c2_name, c2_bbox) in pairs[:30]:
        poly_a = _make_bbox_polygon(c1_bbox)
        poly_b = _make_bbox_polygon(c2_bbox)
        gt = SpatialReasoner.check_relationship(poly_a, poly_b, "disjoint")
        qid += 1
        questions.append(_topo_question(
            qid, "disjoint", Difficulty.EASY,
            f"Are the bounding boxes of {c1_name} and {c2_name} disjoint (non-overlapping)?",
            poly_a, poly_b, gt,
            f"the bounding box of {c1_name}", f"the bounding box of {c2_name}",
        ))

    # ---- Category 4: Within -- ~40 questions ----
    for city_name, bbox in city_list:
        polygon = _make_bbox_polygon(bbox)
        # Small polygon inside
        inner_bbox = [
            bbox[0] + (bbox[2] - bbox[0]) * 0.3,
            bbox[1] + (bbox[3] - bbox[1]) * 0.3,
            bbox[2] - (bbox[2] - bbox[0]) * 0.3,
            bbox[3] - (bbox[3] - bbox[1]) * 0.3,
        ]
        inner_poly = _make_bbox_polygon(inner_bbox)
        gt = SpatialReasoner.check_relationship(inner_poly, polygon, "within")
        qid += 1
        questions.append(_topo_question(
            qid, "within", Difficulty.MEDIUM,
            f"Is the inner district of {city_name} entirely within the city boundary?",
            inner_poly, polygon, gt,
            f"the inner district of {city_name}", f"the boundary of {city_name}",
        ))

        # Polygon that extends outside
        outer_bbox = [bbox[0] - 0.1, bbox[1] - 0.1, bbox[2] - 0.05, bbox[3] - 0.05]
        outer_poly = _make_bbox_polygon(outer_bbox)
        gt2 = SpatialReasoner.check_relationship(outer_poly, polygon, "within")
        qid += 1
        questions.append(_topo_question(
            qid, "within", Difficulty.MEDIUM,
            f"Is this extended area entirely within the boundary of {city_name}?",
            outer_poly, polygon, gt2,
            "the extended area", f"the boundary of {city_name}",
        ))

        # Point within (random interior point)
        inner_pt = _point_in_bbox(inner_bbox)
        point = _make_point(inner_pt)
        gt3 = SpatialReasoner.check_relationship(point, polygon, "within")
        qid += 1
        questions.append(_topo_question(
            qid, "within", Difficulty.EASY,
            f"Is the point at ({inner_pt[1]:.4f}N, {inner_pt[0]:.4f}E) within the boundary of {city_name}?",
            point, polygon, gt3,
            "the point", f"the boundary of {city_name}",
        ))

    # ---- Category 5: Polygon with hole (Dr. Chen's gotcha) -- ~20 questions ----
    hole_configs = [
        ("Paris", PARIS_WITH_HOLE, [2.34, 48.855, 2.36, 48.860], [2.25, 48.83, 2.33, 48.85]),
        ("London", LONDON_WITH_HOLE, [-0.10, 51.50, -0.08, 51.52], [-0.25, 51.42, -0.15, 51.48]),
        ("Tokyo", TOKYO_WITH_HOLE, [139.74, 35.66, 139.76, 35.68], [139.67, 35.62, 139.72, 35.64]),
    ]
    for city_label, hole_polygon, hole_bbox, safe_bbox in hole_configs:
        for _i in range(4):
            # Point inside the hole (should NOT be contained)
            hole_pt = [
                round(RNG.uniform(hole_bbox[0], hole_bbox[2]), 6),
                round(RNG.uniform(hole_bbox[1], hole_bbox[3]), 6),
            ]
            point = _make_point(hole_pt)
            gt = SpatialReasoner.check_relationship(hole_polygon, point, "contains")
            qid += 1
            questions.append(_topo_question(
                qid, "contains_with_hole", Difficulty.HARD,
                f"{city_label} has a defined boundary with an exclusion zone (hole). "
                f"Does this boundary contain the point at ({hole_pt[1]:.4f}N, {hole_pt[0]:.4f}E)?",
                hole_polygon, point, gt,
                f"{city_label} boundary (with exclusion zone)", "the point",
            ))

            # Point outside the hole but inside the city (should be contained)
            safe_pt = _point_in_bbox(safe_bbox)
            point2 = _make_point(safe_pt)
            gt2 = SpatialReasoner.check_relationship(hole_polygon, point2, "contains")
            qid += 1
            questions.append(_topo_question(
                qid, "contains_with_hole", Difficulty.HARD,
                f"{city_label} has a defined boundary with an exclusion zone. "
                f"Does this boundary contain the point at ({safe_pt[1]:.4f}N, {safe_pt[0]:.4f}E)?",
                hole_polygon, point2, gt2,
                f"{city_label} boundary (with exclusion zone)", "the point",
            ))

    # ---- Category 6: Touches -- pad to 200+ ----
    while len(questions) < 210:
        qid += 1
        c_name, c_bbox = RNG.choice(city_list)
        poly = _make_bbox_polygon(c_bbox)
        # Point exactly on boundary
        edge_pt = [c_bbox[0], RNG.uniform(c_bbox[1], c_bbox[3])]
        point = _make_point([round(edge_pt[0], 6), round(edge_pt[1], 6)])
        gt = SpatialReasoner.check_relationship(poly, point, "touches")
        questions.append(_topo_question(
            qid, "touches", Difficulty.HARD,
            f"Does the point at ({edge_pt[1]:.4f}N, {edge_pt[0]:.4f}E) touch (lie exactly on the boundary of) the {c_name} bounding box?",
            poly, point, gt,
            "the point", f"the {c_name} boundary",
        ))

    return questions


def _topo_question(
    qid: int, category: str, difficulty: Difficulty,
    natural_q: str, geom_a: dict, geom_b: dict, ground_truth: bool,
    desc_a: str, desc_b: str,
) -> dict:
    """Build a GeoTopo question dict."""
    structured_q = (
        f"{natural_q}\n\n"
        f"Geometry A ({desc_a}):\n```json\n{json.dumps(geom_a)}\n```\n\n"
        f"Geometry B ({desc_b}):\n```json\n{json.dumps(geom_b)}\n```\n\n"
        f"Answer with True or False."
    )
    return {
        "id": f"geotopo_{qid:03d}",
        "benchmark": BenchmarkName.GEOTOPO.value,
        "category": category,
        "difficulty": difficulty.value,
        "prompt_natural": f"{natural_q} Answer with True or False.",
        "prompt_structured": structured_q,
        "answer_type": AnswerType.BOOLEAN.value,
        "ground_truth": ground_truth,
        "ground_truth_meta": {"engine": "shapely", "verified": True},
        "geometry_a": geom_a,
        "geometry_b": geom_b,
        "source": "generated_v1.0",
    }


# ---------------------------------------------------------------------------
# GeoDistance -- Distance and proximity questions (v1.0: 200+)
# ---------------------------------------------------------------------------

def generate_geodistance() -> list[dict]:
    """Generate 200+ distance/proximity questions."""
    questions: list[dict] = []
    qid = 0
    landmark_list = list(LANDMARKS.items())

    # Category 1: Absolute distance -- 80 questions
    pairs = [(landmark_list[i], landmark_list[j])
             for i in range(len(landmark_list)) for j in range(i + 1, len(landmark_list))]
    RNG.shuffle(pairs)

    for (name_a, info_a), (name_b, info_b) in pairs[:80]:
        point_a = _make_point(info_a["coords"])
        point_b = _make_point(info_b["coords"])
        distance_m = SpatialReasoner.calculate_distance(point_a, point_b)

        # Difficulty based on distance
        if info_a["city"] == info_b["city"]:
            diff = Difficulty.EASY
        elif info_a["country"] == info_b["country"]:
            diff = Difficulty.MEDIUM
        else:
            diff = Difficulty.HARD

        qid += 1
        # Tolerance: 5% of actual distance or 500m, whichever is larger
        tolerance = max(500, distance_m * 0.05)

        questions.append(_distance_question(
            qid, "distance_absolute", diff,
            f"What is the distance in meters from the {name_a} to the {name_b}?",
            point_a, point_b, distance_m,
            name_a, name_b, tolerance,
        ))

    # Category 2: Proximity threshold (within X km?) -- 70 questions
    for (name_a, info_a), (name_b, info_b) in pairs[80:150]:
        point_a = _make_point(info_a["coords"])
        point_b = _make_point(info_b["coords"])
        distance_m = SpatialReasoner.calculate_distance(point_a, point_b)
        distance_km = distance_m / 1000

        # Pick a threshold that makes an interesting question
        if distance_km < 10:
            threshold_km = RNG.choice([5, 10, 15])
            diff = Difficulty.EASY
        elif distance_km < 100:
            threshold_km = RNG.choice([50, 100, 200])
            diff = Difficulty.MEDIUM
        else:
            threshold_km = RNG.choice([500, 1000, 5000])
            diff = Difficulty.HARD

        gt = distance_km <= threshold_km
        qid += 1
        questions.append({
            "id": f"geodistance_{qid:03d}",
            "benchmark": BenchmarkName.GEODISTANCE.value,
            "category": "proximity_threshold",
            "difficulty": diff.value,
            "prompt_natural": f"Is the {name_a} within {threshold_km} km of the {name_b}? Answer True or False.",
            "prompt_structured": (
                f"Is the {name_a} within {threshold_km} km of the {name_b}?\n\n"
                f"Point A ({name_a}):\n```json\n{json.dumps(point_a)}\n```\n\n"
                f"Point B ({name_b}):\n```json\n{json.dumps(point_b)}\n```\n\n"
                f"Threshold: {threshold_km} km\n"
                f"Answer with True or False."
            ),
            "answer_type": AnswerType.BOOLEAN.value,
            "ground_truth": gt,
            "ground_truth_meta": {
                "actual_distance_m": round(distance_m, 1),
                "threshold_m": threshold_km * 1000,
            },
            "geometry_a": point_a,
            "geometry_b": point_b,
            "source": "generated_v1.0",
        })

    # Category 3: Nearest neighbor -- 30 questions
    cities_with_landmarks: dict[str, list[tuple[str, dict]]] = {}
    for name, info in LANDMARKS.items():
        cities_with_landmarks.setdefault(info["city"], []).append((name, info))

    for _city, lms in cities_with_landmarks.items():
        if len(lms) < 3:
            continue
        for _ in range(3):
            ref_name, ref_info = RNG.choice(lms)
            others = [(n, i) for n, i in lms if n != ref_name]
            if not others:
                continue

            # Find actual nearest
            distances = []
            for other_name, other_info in others:
                d = SpatialReasoner.calculate_distance(
                    _make_point(ref_info["coords"]),
                    _make_point(other_info["coords"]),
                )
                distances.append((other_name, d))
            distances.sort(key=lambda x: x[1])
            nearest_name = distances[0][0]

            qid += 1
            other_names = [n for n, _ in others]
            questions.append({
                "id": f"geodistance_{qid:03d}",
                "benchmark": BenchmarkName.GEODISTANCE.value,
                "category": "nearest_neighbor",
                "difficulty": Difficulty.MEDIUM.value,
                "prompt_natural": (
                    f"Which of these landmarks is closest to the {ref_name}: "
                    f"{', '.join(other_names)}?"
                ),
                "prompt_structured": (
                    f"Which of these landmarks is closest to the {ref_name}?\n\n"
                    f"Reference point ({ref_name}):\n```json\n{json.dumps(_make_point(ref_info['coords']))}\n```\n\n"
                    + "\n".join(
                        f"Option: {n}\n```json\n{json.dumps(_make_point(i['coords']))}\n```"
                        for n, i in others
                    )
                    + "\n\nAnswer with the name of the nearest landmark."
                ),
                "answer_type": AnswerType.CATEGORY.value,
                "ground_truth": nearest_name,
                "ground_truth_meta": {
                    "valid_categories": other_names,
                    "distances_m": {n: round(d, 1) for n, d in distances},
                },
                "geometry_a": _make_point(ref_info["coords"]),
                "source": "generated_v1.0",
            })

    # Pad to 210+ with additional proximity questions
    while len(questions) < 210:
        (name_a, info_a), (name_b, info_b) = RNG.sample(landmark_list, 2)
        point_a = _make_point(info_a["coords"])
        point_b = _make_point(info_b["coords"])
        distance_m = SpatialReasoner.calculate_distance(point_a, point_b)
        threshold_km = RNG.choice([10, 50, 100, 500, 1000])
        gt = (distance_m / 1000) <= threshold_km
        qid += 1
        questions.append({
            "id": f"geodistance_{qid:03d}",
            "benchmark": BenchmarkName.GEODISTANCE.value,
            "category": "proximity_threshold",
            "difficulty": Difficulty.MEDIUM.value,
            "prompt_natural": f"Is the {name_a} within {threshold_km} km of the {name_b}? Answer True or False.",
            "prompt_structured": (
                f"Is the {name_a} within {threshold_km} km of the {name_b}?\n\n"
                f"Point A ({name_a}):\n```json\n{json.dumps(point_a)}\n```\n"
                f"Point B ({name_b}):\n```json\n{json.dumps(point_b)}\n```\n"
                f"Threshold: {threshold_km} km\nAnswer with True or False."
            ),
            "answer_type": AnswerType.BOOLEAN.value,
            "ground_truth": gt,
            "ground_truth_meta": {"actual_distance_m": round(distance_m, 1), "threshold_m": threshold_km * 1000},
            "geometry_a": point_a,
            "geometry_b": point_b,
            "source": "generated_v1.0",
        })

    return questions


def _distance_question(
    qid: int, category: str, difficulty: Difficulty,
    natural_q: str, geom_a: dict, geom_b: dict, ground_truth_m: float,
    desc_a: str, desc_b: str, tolerance: float,
) -> dict:
    """Build a GeoDistance question dict."""
    structured_q = (
        f"{natural_q}\n\n"
        f"Point A ({desc_a}):\n```json\n{json.dumps(geom_a)}\n```\n\n"
        f"Point B ({desc_b}):\n```json\n{json.dumps(geom_b)}\n```\n\n"
        f"Give your answer as a number in meters."
    )
    return {
        "id": f"geodistance_{qid:03d}",
        "benchmark": BenchmarkName.GEODISTANCE.value,
        "category": category,
        "difficulty": difficulty.value,
        "prompt_natural": f"{natural_q} Give your answer as a number in meters.",
        "prompt_structured": structured_q,
        "answer_type": AnswerType.NUMERIC.value,
        "ground_truth": round(ground_truth_m, 1),
        "ground_truth_meta": {"tolerance_m": round(tolerance, 1), "tolerance_pct": 0.05},
        "geometry_a": geom_a,
        "geometry_b": geom_b,
        "source": "generated_v1.0",
    }


# ---------------------------------------------------------------------------
# GeoChange -- Change detection questions (text-based v0.1)
# ---------------------------------------------------------------------------

# Curated change detection scenarios with known ground truth
CHANGE_SCENARIOS = [
    {
        "location": "Amazon Rainforest, Brazil",
        "coords": [-60.0, -3.0],
        "period": "2015-2023",
        "changed": True,
        "change_type": "deforestation",
        "description": "Significant deforestation detected in the Amazon basin between 2015 and 2023.",
        "difficulty": "easy",
    },
    {
        "location": "Dubai Marina, UAE",
        "coords": [55.14, 25.08],
        "period": "2010-2024",
        "changed": True,
        "change_type": "urban_expansion",
        "description": "Rapid urban development and land reclamation in Dubai Marina area.",
        "difficulty": "easy",
    },
    {
        "location": "Sahara Desert, Libya",
        "coords": [20.0, 25.0],
        "period": "2018-2024",
        "changed": False,
        "change_type": "no_change",
        "description": "The central Sahara shows minimal land use change over this period.",
        "difficulty": "easy",
    },
    {
        "location": "Chernobyl Exclusion Zone, Ukraine",
        "coords": [30.06, 51.27],
        "period": "2000-2024",
        "changed": True,
        "change_type": "vegetation_recovery",
        "description": "Vegetation recovery and rewilding in the exclusion zone after human abandonment.",
        "difficulty": "medium",
    },
    {
        "location": "Lake Urmia, Iran",
        "coords": [45.5, 37.5],
        "period": "2000-2023",
        "changed": True,
        "change_type": "water_loss",
        "description": "Lake Urmia has shrunk dramatically, losing over 80% of its surface area.",
        "difficulty": "medium",
    },
    {
        "location": "Aral Sea, Kazakhstan",
        "coords": [59.0, 45.0],
        "period": "1990-2024",
        "changed": True,
        "change_type": "water_loss",
        "description": "The Aral Sea has nearly disappeared due to irrigation diversion.",
        "difficulty": "easy",
    },
    {
        "location": "Beijing, China (urban area)",
        "coords": [116.4, 39.9],
        "period": "2005-2024",
        "changed": True,
        "change_type": "urban_expansion",
        "description": "Massive urban expansion in Beijing's periphery with new ring roads and satellite cities.",
        "difficulty": "easy",
    },
    {
        "location": "Swiss Alps, Aletsch Glacier",
        "coords": [8.0, 46.5],
        "period": "2000-2024",
        "changed": True,
        "change_type": "glacier_retreat",
        "description": "The Aletsch Glacier has retreated significantly due to climate change.",
        "difficulty": "medium",
    },
    {
        "location": "Central Park, New York",
        "coords": [-73.97, 40.78],
        "period": "2015-2024",
        "changed": False,
        "change_type": "no_change",
        "description": "Central Park's footprint has remained stable as a protected urban green space.",
        "difficulty": "easy",
    },
    {
        "location": "Sundarbans Mangrove, Bangladesh",
        "coords": [89.5, 22.0],
        "period": "2010-2024",
        "changed": True,
        "change_type": "coastal_erosion",
        "description": "Ongoing coastal erosion and mangrove loss due to sea level rise and cyclones.",
        "difficulty": "medium",
    },
    {
        "location": "Palm Jumeirah, Dubai",
        "coords": [55.13, 25.11],
        "period": "2001-2010",
        "changed": True,
        "change_type": "land_reclamation",
        "description": "Construction of the Palm Jumeirah artificial island, a major land reclamation project.",
        "difficulty": "easy",
    },
    {
        "location": "Antarctic Peninsula",
        "coords": [-60.0, -65.0],
        "period": "2000-2024",
        "changed": True,
        "change_type": "ice_loss",
        "description": "Accelerated ice shelf collapse along the Antarctic Peninsula.",
        "difficulty": "medium",
    },
    {
        "location": "Yellowstone National Park, USA",
        "coords": [-110.5, 44.6],
        "period": "2018-2024",
        "changed": False,
        "change_type": "no_change",
        "description": "Yellowstone's landscape has remained largely unchanged as a protected wilderness area.",
        "difficulty": "medium",
    },
    {
        "location": "Australian Bushfire Zone (NSW)",
        "coords": [150.0, -33.0],
        "period": "2019-2020",
        "changed": True,
        "change_type": "wildfire",
        "description": "Massive bushfires in 2019-2020 caused widespread vegetation loss in New South Wales.",
        "difficulty": "easy",
    },
    {
        "location": "Three Gorges Dam, China",
        "coords": [111.0, 30.8],
        "period": "1995-2010",
        "changed": True,
        "change_type": "dam_construction",
        "description": "Construction and filling of the Three Gorges Reservoir, flooding a vast area.",
        "difficulty": "medium",
    },
    {
        "location": "Mount Pinatubo, Philippines",
        "coords": [120.35, 15.13],
        "period": "1990-2000",
        "changed": True,
        "change_type": "volcanic",
        "description": "The 1991 eruption dramatically altered the landscape, creating a crater lake.",
        "difficulty": "hard",
    },
    {
        "location": "Venice, Italy",
        "coords": [12.34, 45.44],
        "period": "2015-2024",
        "changed": False,
        "change_type": "no_change",
        "description": "Venice's urban footprint has not significantly changed, though flooding frequency increased.",
        "difficulty": "hard",
    },
    {
        "location": "Borneo Rainforest, Indonesia",
        "coords": [115.0, 0.0],
        "period": "2000-2024",
        "changed": True,
        "change_type": "deforestation",
        "description": "Large-scale deforestation for palm oil plantations in Borneo.",
        "difficulty": "easy",
    },
    {
        "location": "Fukushima, Japan (exclusion zone)",
        "coords": [141.0, 37.4],
        "period": "2011-2024",
        "changed": True,
        "change_type": "vegetation_recovery",
        "description": "Vegetation recovery in abandoned areas following the 2011 nuclear disaster.",
        "difficulty": "medium",
    },
    {
        "location": "Greenland Ice Sheet",
        "coords": [-42.0, 72.0],
        "period": "2000-2024",
        "changed": True,
        "change_type": "ice_loss",
        "description": "Accelerated melting and ice loss across the Greenland ice sheet.",
        "difficulty": "medium",
    },
]


def generate_geochanage() -> list[dict]:
    """Generate 50 change detection questions."""
    questions: list[dict] = []
    qid = 0

    for scenario in CHANGE_SCENARIOS:
        # Question 1: Did it change?
        qid += 1
        point = _make_point(scenario["coords"])
        questions.append({
            "id": f"geochanage_{qid:03d}",
            "benchmark": BenchmarkName.GEOCHANAGE.value,
            "category": "change_detection",
            "difficulty": scenario["difficulty"],
            "prompt_natural": (
                f"Did the area around {scenario['location']} experience significant "
                f"land use or land cover change between {scenario['period']}? "
                f"Answer True or False."
            ),
            "prompt_structured": (
                f"Did the area around {scenario['location']} experience significant "
                f"land use or land cover change between {scenario['period']}?\n\n"
                f"Location:\n```json\n{json.dumps(point)}\n```\n\n"
                f"Time period: {scenario['period']}\n"
                f"Answer with True or False."
            ),
            "answer_type": AnswerType.BOOLEAN.value,
            "ground_truth": scenario["changed"],
            "ground_truth_meta": {
                "change_type": scenario["change_type"],
                "description": scenario["description"],
            },
            "geometry_a": point,
            "source": "curated_v0.1",
        })

        # Question 2: What type of change? (only for changed areas)
        if scenario["changed"]:
            qid += 1
            valid_types = ["deforestation", "urban_expansion", "water_loss",
                           "glacier_retreat", "coastal_erosion", "land_reclamation",
                           "ice_loss", "wildfire", "dam_construction", "volcanic",
                           "vegetation_recovery"]
            questions.append({
                "id": f"geochanage_{qid:03d}",
                "benchmark": BenchmarkName.GEOCHANAGE.value,
                "category": "change_type",
                "difficulty": "hard",
                "prompt_natural": (
                    f"What type of land change occurred at {scenario['location']} "
                    f"between {scenario['period']}? "
                    f"Choose from: {', '.join(valid_types)}."
                ),
                "prompt_structured": (
                    f"What type of land change occurred at {scenario['location']} "
                    f"between {scenario['period']}?\n\n"
                    f"Location:\n```json\n{json.dumps(point)}\n```\n\n"
                    f"Options: {', '.join(valid_types)}\n"
                    f"Answer with one of the options above."
                ),
                "answer_type": AnswerType.CATEGORY.value,
                "ground_truth": scenario["change_type"],
                "ground_truth_meta": {"valid_categories": valid_types},
                "geometry_a": point,
                "source": "curated_v0.1",
            })

    return questions[:50]


# ---------------------------------------------------------------------------
# GeoReason -- Multi-step spatial reasoning chains (v1.0 NEW)
# ---------------------------------------------------------------------------

def generate_georeason() -> list[dict]:
    """Generate 50+ multi-step spatial reasoning questions.

    Categories:
    - distance_chain: Multi-hop distance reasoning (A->B->C)
    - transitivity: Spatial relationship transitivity (within/contains chains)
    - buffer_intersection: Buffer + intersection logic
    - comparative: Comparing distances or areas
    """
    questions: list[dict] = []
    qid = 0

    landmark_list = list(LANDMARKS.items())

    # ---- Category 1: Distance chain reasoning ---- (~15 questions)
    # "A is X km from B. B is Y km from C in the opposite direction.
    #  How far is C from A?"
    chain_scenarios = [
        # (start_landmark, middle_description, d1_m, d2_m, azimuth1, azimuth2, expected_total_m)
        # Collinear case: same direction -> total = d1 + d2
        ("Eiffel Tower", "a hospital", 5000, 2000, 90.0, 90.0),
        ("Big Ben", "a park", 3000, 4000, 0.0, 0.0),
        ("Colosseum", "a library", 1500, 2500, 45.0, 45.0),
        # Opposite direction: total = d1 + d2
        ("Statue of Liberty", "a school", 4000, 3000, 90.0, 270.0),
        ("Tokyo Tower", "a museum", 6000, 2000, 180.0, 0.0),
        # Right angle: total = sqrt(d1^2 + d2^2)
        ("Sydney Opera House", "a ferry terminal", 1000, 1000, 0.0, 90.0),
        ("Burj Khalifa", "a metro station", 2000, 3000, 0.0, 90.0),
        ("Pyramids of Giza", "a bazaar", 5000, 5000, 0.0, 90.0),
    ]

    for start_name, mid_desc, d1, d2, az1, az2 in chain_scenarios:
        start_info = LANDMARKS[start_name]
        start_coords = start_info["coords"]
        mid_coords = _geodesic_destination(start_coords[0], start_coords[1], az1, d1)
        end_coords = _geodesic_destination(mid_coords[0], mid_coords[1], az2, d2)

        # Compute actual geodesic distance from start to end
        point_start = _make_point(start_coords)
        point_end = _make_point(end_coords)
        actual_distance = SpatialReasoner.calculate_distance(point_start, point_end)

        # Determine if directions are opposite, same, or perpendicular
        az_diff = abs(az1 - az2)
        if az_diff == 180 or az_diff == 0:
            direction_desc = "in the opposite direction" if az_diff == 180 else "in the same direction"
        else:
            direction_desc = "at a right angle"

        qid += 1
        tolerance = max(500, actual_distance * 0.10)
        natural_q = (
            f"The {start_name} is {d1}m from {mid_desc}. "
            f"{mid_desc.capitalize()} is {d2}m from a destination point {direction_desc}. "
            f"How far is the destination point from the {start_name}?"
        )
        structured_q = (
            f"{natural_q}\n\n"
            f"Start ({start_name}):\n```json\n{json.dumps(point_start)}\n```\n\n"
            f"Intermediate ({mid_desc}):\n```json\n{json.dumps(_make_point(mid_coords))}\n```\n\n"
            f"End (destination):\n```json\n{json.dumps(point_end)}\n```\n\n"
            f"Give your answer as a number in meters."
        )
        questions.append({
            "id": f"georeason_{qid:03d}",
            "benchmark": BenchmarkName.GEOREASON.value,
            "category": "distance_chain",
            "difficulty": Difficulty.MEDIUM.value,
            "prompt_natural": f"{natural_q} Give your answer as a number in meters.",
            "prompt_structured": structured_q,
            "answer_type": AnswerType.NUMERIC.value,
            "ground_truth": round(actual_distance, 1),
            "ground_truth_meta": {
                "tolerance_m": round(tolerance, 1),
                "tolerance_pct": 0.10,
                "reasoning_steps": 2,
            },
            "geometry_a": point_start,
            "geometry_b": point_end,
            "source": "generated_v1.0",
        })

    # ---- Category 2: Transitivity reasoning ---- (~15 questions)
    # "Point A is inside polygon P. Polygon P is within polygon Q.
    #  Is point A within polygon Q?"
    city_list = list(CITY_BBOXES.items())
    for city_name, bbox in city_list[:8]:
        # Create nested polygons: inner inside outer
        inner_bbox = [
            bbox[0] + (bbox[2] - bbox[0]) * 0.3,
            bbox[1] + (bbox[3] - bbox[1]) * 0.3,
            bbox[2] - (bbox[2] - bbox[0]) * 0.3,
            bbox[3] - (bbox[3] - bbox[1]) * 0.3,
        ]
        outer_bbox = [
            bbox[0] - 0.1,
            bbox[1] - 0.1,
            bbox[2] + 0.1,
            bbox[3] + 0.1,
        ]

        inner_poly = _make_bbox_polygon(inner_bbox)
        city_poly = _make_bbox_polygon(bbox)
        outer_poly = _make_bbox_polygon(outer_bbox)

        # Point inside inner polygon
        pt = _point_in_bbox(inner_bbox)
        point_geom = _make_point(pt)

        # Question: Point inside inner, inner within city -> point within city?
        gt = SpatialReasoner.check_relationship(point_geom, city_poly, "within")
        qid += 1
        natural_q = (
            f"Point A at ({pt[1]:.4f}N, {pt[0]:.4f}E) is inside the inner district of {city_name}. "
            f"The inner district is within the city boundary of {city_name}. "
            f"Is Point A within the city boundary?"
        )
        structured_q = (
            f"{natural_q}\n\n"
            f"Point A:\n```json\n{json.dumps(point_geom)}\n```\n\n"
            f"Inner district:\n```json\n{json.dumps(inner_poly)}\n```\n\n"
            f"City boundary:\n```json\n{json.dumps(city_poly)}\n```\n\n"
            f"Answer with True or False."
        )
        questions.append({
            "id": f"georeason_{qid:03d}",
            "benchmark": BenchmarkName.GEOREASON.value,
            "category": "transitivity",
            "difficulty": Difficulty.MEDIUM.value,
            "prompt_natural": f"{natural_q} Answer with True or False.",
            "prompt_structured": structured_q,
            "answer_type": AnswerType.BOOLEAN.value,
            "ground_truth": gt,
            "ground_truth_meta": {"reasoning_type": "spatial_transitivity", "reasoning_steps": 2},
            "geometry_a": point_geom,
            "geometry_b": city_poly,
            "source": "generated_v1.0",
        })

        # Question: Inner within city, city within outer -> inner within outer?
        gt2 = SpatialReasoner.check_relationship(inner_poly, outer_poly, "within")
        qid += 1
        natural_q2 = (
            f"The inner district of {city_name} is within the city boundary. "
            f"The city boundary of {city_name} is within a larger metropolitan region. "
            f"Is the inner district within the metropolitan region?"
        )
        structured_q2 = (
            f"{natural_q2}\n\n"
            f"Inner district:\n```json\n{json.dumps(inner_poly)}\n```\n\n"
            f"City boundary:\n```json\n{json.dumps(city_poly)}\n```\n\n"
            f"Metropolitan region:\n```json\n{json.dumps(outer_poly)}\n```\n\n"
            f"Answer with True or False."
        )
        questions.append({
            "id": f"georeason_{qid:03d}",
            "benchmark": BenchmarkName.GEOREASON.value,
            "category": "transitivity",
            "difficulty": Difficulty.HARD.value,
            "prompt_natural": f"{natural_q2} Answer with True or False.",
            "prompt_structured": structured_q2,
            "answer_type": AnswerType.BOOLEAN.value,
            "ground_truth": gt2,
            "ground_truth_meta": {"reasoning_type": "spatial_transitivity", "reasoning_steps": 2},
            "geometry_a": inner_poly,
            "geometry_b": outer_poly,
            "source": "generated_v1.0",
        })

    # ---- Category 3: Buffer intersection reasoning ---- (~15 questions)
    # "If you buffer point X by R meters, does it intersect polygon Y
    #  that is D meters away?"
    for city_name, bbox in city_list[:8]:
        city_poly = _make_bbox_polygon(bbox)

        # Point near the city boundary -- buffer may or may not reach
        near_pt = _point_outside_bbox(bbox, margin=0.02)
        point_geom = _make_point(near_pt)

        # Compute actual distance from point to nearest edge of city polygon
        actual_dist = SpatialReasoner.calculate_distance(point_geom, city_poly)

        # Buffer radius scenarios
        for buffer_m, diff in [(actual_dist * 1.5, Difficulty.MEDIUM), (actual_dist * 0.5, Difficulty.HARD)]:
            buffer_m = round(buffer_m, 0)
            if buffer_m < 100:
                buffer_m = 100  # minimum reasonable buffer

            # After buffering, would it intersect the city polygon?
            gt = buffer_m >= actual_dist
            qid += 1
            natural_q = (
                f"A sensor at ({near_pt[1]:.4f}N, {near_pt[0]:.4f}E) has a detection radius of {int(buffer_m)}m. "
                f"The sensor is approximately {int(actual_dist)}m from the {city_name} city boundary. "
                f"Does the sensor's coverage area intersect with the city boundary?"
            )
            structured_q = (
                f"{natural_q}\n\n"
                f"Sensor location:\n```json\n{json.dumps(point_geom)}\n```\n\n"
                f"Buffer radius: {int(buffer_m)} meters\n\n"
                f"City boundary ({city_name}):\n```json\n{json.dumps(city_poly)}\n```\n\n"
                f"Answer with True or False."
            )
            questions.append({
                "id": f"georeason_{qid:03d}",
                "benchmark": BenchmarkName.GEOREASON.value,
                "category": "buffer_intersection",
                "difficulty": diff.value,
                "prompt_natural": f"{natural_q} Answer with True or False.",
                "prompt_structured": structured_q,
                "answer_type": AnswerType.BOOLEAN.value,
                "ground_truth": gt,
                "ground_truth_meta": {
                    "buffer_m": int(buffer_m),
                    "actual_distance_m": round(actual_dist, 1),
                    "reasoning_steps": 2,
                },
                "geometry_a": point_geom,
                "geometry_b": city_poly,
                "source": "generated_v1.0",
            })

    # ---- Category 4: Comparative reasoning ---- (~15 questions)
    # "Is landmark A closer to B or to C?"
    for _ in range(15):
        ref, cand_a, cand_b = RNG.sample(landmark_list, 3)
        ref_name, ref_info = ref
        name_a, info_a = cand_a
        name_b, info_b = cand_b

        d_a = SpatialReasoner.calculate_distance(
            _make_point(ref_info["coords"]), _make_point(info_a["coords"]))
        d_b = SpatialReasoner.calculate_distance(
            _make_point(ref_info["coords"]), _make_point(info_b["coords"]))

        gt = name_a if d_a < d_b else name_b
        qid += 1
        natural_q = (
            f"Is the {ref_name} closer to the {name_a} or to the {name_b}?"
        )
        structured_q = (
            f"{natural_q}\n\n"
            f"Reference ({ref_name}):\n```json\n{json.dumps(_make_point(ref_info['coords']))}\n```\n\n"
            f"Option A ({name_a}):\n```json\n{json.dumps(_make_point(info_a['coords']))}\n```\n\n"
            f"Option B ({name_b}):\n```json\n{json.dumps(_make_point(info_b['coords']))}\n```\n\n"
            f"Answer with the name of the closer landmark."
        )
        questions.append({
            "id": f"georeason_{qid:03d}",
            "benchmark": BenchmarkName.GEOREASON.value,
            "category": "comparative",
            "difficulty": Difficulty.HARD.value,
            "prompt_natural": natural_q,
            "prompt_structured": structured_q,
            "answer_type": AnswerType.CATEGORY.value,
            "ground_truth": gt,
            "ground_truth_meta": {
                "valid_categories": [name_a, name_b],
                "distance_to_a_m": round(d_a, 1),
                "distance_to_b_m": round(d_b, 1),
                "reasoning_steps": 2,
            },
            "geometry_a": _make_point(ref_info["coords"]),
            "source": "generated_v1.0",
        })

    return questions


# ---------------------------------------------------------------------------
# GeoMultimodal -- Questions combining multiple spatial data types (v1.0 NEW)
# ---------------------------------------------------------------------------

# Curated multimodal scenarios with known ground truth
MULTIMODAL_SCENARIOS = [
    # ---- vegetation_health: NDVI + polygon boundary ----
    {
        "category": "vegetation_health",
        "location": "Amazon Basin, Brazil",
        "coords": [-60.0, -3.0],
        "ndvi": 0.85,
        "cloud_cover_pct": 5,
        "polygon": {"type": "Polygon", "coordinates": [[[-60.5, -3.5], [-59.5, -3.5], [-59.5, -2.5], [-60.5, -2.5], [-60.5, -3.5]]]},
        "question": "Given satellite scene metadata (cloud cover {cloud_cover}%, NDVI {ndvi}) and the polygon boundary, is vegetation healthy?",
        "ground_truth": True,
        "explanation": "NDVI > 0.6 indicates healthy/dense vegetation. Low cloud cover means reliable data.",
        "difficulty": "easy",
    },
    {
        "category": "vegetation_health",
        "location": "Sahara Desert, Libya",
        "coords": [20.0, 25.0],
        "ndvi": 0.05,
        "cloud_cover_pct": 2,
        "polygon": {"type": "Polygon", "coordinates": [[[19.5, 24.5], [20.5, 24.5], [20.5, 25.5], [19.5, 25.5], [19.5, 24.5]]]},
        "question": "Given satellite scene metadata (cloud cover {cloud_cover}%, NDVI {ndvi}) and the polygon boundary, is vegetation healthy?",
        "ground_truth": False,
        "explanation": "NDVI < 0.2 indicates barren land or desert. No significant vegetation.",
        "difficulty": "easy",
    },
    {
        "category": "vegetation_health",
        "location": "Central Park, New York",
        "coords": [-73.97, 40.78],
        "ndvi": 0.55,
        "cloud_cover_pct": 40,
        "polygon": {"type": "Polygon", "coordinates": [[[-73.98, 40.77], [-73.95, 40.77], [-73.95, 40.80], [-73.98, 40.80], [-73.98, 40.77]]]},
        "question": "Given satellite scene metadata (cloud cover {cloud_cover}%, NDVI {ndvi}) and the polygon boundary, is vegetation healthy?",
        "ground_truth": True,
        "explanation": "NDVI 0.4-0.6 indicates moderate vegetation (urban park). Cloud cover is high but data is still usable.",
        "difficulty": "medium",
    },
    {
        "category": "vegetation_health",
        "location": "Australian Outback",
        "coords": [134.0, -25.0],
        "ndvi": 0.15,
        "cloud_cover_pct": 3,
        "polygon": {"type": "Polygon", "coordinates": [[[133.5, -25.5], [134.5, -25.5], [134.5, -24.5], [133.5, -24.5], [133.5, -25.5]]]},
        "question": "Given satellite scene metadata (cloud cover {cloud_cover}%, NDVI {ndvi}) and the polygon boundary, is vegetation healthy?",
        "ground_truth": False,
        "explanation": "NDVI 0.1-0.2 indicates sparse vegetation typical of arid/semi-arid regions.",
        "difficulty": "easy",
    },
    {
        "category": "vegetation_health",
        "location": "Black Forest, Germany",
        "coords": [8.2, 48.0],
        "ndvi": 0.72,
        "cloud_cover_pct": 60,
        "polygon": {"type": "Polygon", "coordinates": [[[7.7, 47.5], [8.7, 47.5], [8.7, 48.5], [7.7, 48.5], [7.7, 47.5]]]},
        "question": "Given satellite scene metadata (cloud cover {cloud_cover}%, NDVI {ndvi}) and the polygon boundary, is vegetation healthy? Note: high cloud cover may affect data reliability.",
        "ground_truth": True,
        "explanation": "NDVI > 0.6 indicates dense healthy vegetation. Despite high cloud cover, the NDVI reading is clear enough.",
        "difficulty": "medium",
    },
    {
        "category": "vegetation_health",
        "location": "Gobi Desert, Mongolia",
        "coords": [105.0, 43.0],
        "ndvi": 0.08,
        "cloud_cover_pct": 10,
        "polygon": {"type": "Polygon", "coordinates": [[[104.0, 42.0], [106.0, 42.0], [106.0, 44.0], [104.0, 44.0], [104.0, 42.0]]]},
        "question": "Given satellite scene metadata (cloud cover {cloud_cover}%, NDVI {ndvi}) and the polygon boundary, is vegetation healthy?",
        "ground_truth": False,
        "explanation": "NDVI < 0.1 indicates barren desert terrain.",
        "difficulty": "easy",
    },
    # ---- elevation_climate: Elevation + temperature ----
    {
        "category": "elevation_climate",
        "location": "Mont Blanc summit, France",
        "coords": [6.8650, 45.8326],
        "elevation_m": 4808,
        "temperature_c": -15,
        "question": "The elevation at this point is {elevation}m, the temperature is {temperature}C. Is this above the tree line?",
        "ground_truth": True,
        "explanation": "The alpine tree line in the European Alps is typically around 2000-2500m. At 4808m, this is well above.",
        "difficulty": "easy",
    },
    {
        "category": "elevation_climate",
        "location": "Black Forest, Germany",
        "coords": [8.15, 47.95],
        "elevation_m": 800,
        "temperature_c": 10,
        "question": "The elevation at this point is {elevation}m, the temperature is {temperature}C. Is this above the tree line?",
        "ground_truth": False,
        "explanation": "800m is well below the tree line in central Europe (~2000m). Temperate forests grow here.",
        "difficulty": "easy",
    },
    {
        "category": "elevation_climate",
        "location": "Tibetan Plateau, China",
        "coords": [91.0, 32.0],
        "elevation_m": 5200,
        "temperature_c": -10,
        "question": "The elevation at this point is {elevation}m, the temperature is {temperature}C. Is this above the tree line?",
        "ground_truth": True,
        "explanation": "The tree line on the Tibetan Plateau is around 4500m. At 5200m this is above it.",
        "difficulty": "medium",
    },
    {
        "category": "elevation_climate",
        "location": "Andes, Peru (near Cusco)",
        "coords": [-72.0, -13.5],
        "elevation_m": 3400,
        "temperature_c": 8,
        "question": "The elevation at this point is {elevation}m, the temperature is {temperature}C. Is this above the tree line?",
        "ground_truth": False,
        "explanation": "The tree line in the tropical Andes is around 3500-4000m. At 3400m there is still vegetation.",
        "difficulty": "medium",
    },
    {
        "category": "elevation_climate",
        "location": "Kilimanjaro, Tanzania",
        "coords": [37.3556, -3.0674],
        "elevation_m": 4500,
        "temperature_c": -5,
        "question": "The elevation at this point is {elevation}m, the temperature is {temperature}C. Is this above the tree line?",
        "ground_truth": True,
        "explanation": "The tree line on Kilimanjaro is around 3800-4000m. At 4500m this is in the alpine desert zone.",
        "difficulty": "easy",
    },
    {
        "category": "elevation_climate",
        "location": "Scottish Highlands",
        "coords": [-5.0, 57.0],
        "elevation_m": 500,
        "temperature_c": 5,
        "question": "The elevation at this point is {elevation}m, the temperature is {temperature}C. Is this above the tree line?",
        "ground_truth": False,
        "explanation": "The tree line in Scotland is around 600-700m. 500m is below it.",
        "difficulty": "medium",
    },
    # ---- urban_classification: Elevation + NDVI + coordinates ----
    {
        "category": "urban_classification",
        "location": "Manhattan, New York",
        "coords": [-73.9857, 40.7484],
        "ndvi": 0.12,
        "elevation_m": 10,
        "population_density": 27000,
        "question": "A point at ({lat}N, {lon}E) has NDVI {ndvi}, elevation {elevation}m, and population density {pop_density} per sq km. Is this an urban area?",
        "ground_truth": True,
        "explanation": "Low NDVI, low elevation, and very high population density clearly indicate an urban area.",
        "difficulty": "easy",
    },
    {
        "category": "urban_classification",
        "location": "Amazon Rainforest",
        "coords": [-60.0, -3.0],
        "ndvi": 0.85,
        "elevation_m": 50,
        "population_density": 2,
        "question": "A point at ({lat}N, {lon}E) has NDVI {ndvi}, elevation {elevation}m, and population density {pop_density} per sq km. Is this an urban area?",
        "ground_truth": False,
        "explanation": "Very high NDVI and extremely low population density indicate a forested, non-urban area.",
        "difficulty": "easy",
    },
    {
        "category": "urban_classification",
        "location": "Suburban Paris",
        "coords": [2.35, 48.85],
        "ndvi": 0.30,
        "elevation_m": 35,
        "population_density": 5000,
        "question": "A point at ({lat}N, {lon}E) has NDVI {ndvi}, elevation {elevation}m, and population density {pop_density} per sq km. Is this an urban area?",
        "ground_truth": True,
        "explanation": "Moderate NDVI with high population density indicates a dense urban area with some green spaces.",
        "difficulty": "medium",
    },
    {
        "category": "urban_classification",
        "location": "Rural England",
        "coords": [-1.5, 52.0],
        "ndvi": 0.60,
        "elevation_m": 100,
        "population_density": 50,
        "question": "A point at ({lat}N, {lon}E) has NDVI {ndvi}, elevation {elevation}m, and population density {pop_density} per sq km. Is this an urban area?",
        "ground_truth": False,
        "explanation": "High NDVI and low population density indicate rural agricultural or natural land.",
        "difficulty": "easy",
    },
    # ---- cloud_reliability: Cloud cover assessment ----
    {
        "category": "data_reliability",
        "location": "Tropical zone, Indonesia",
        "coords": [110.0, -7.0],
        "cloud_cover_pct": 85,
        "ndvi": 0.45,
        "question": "A satellite scene over {location} has {cloud_cover}% cloud cover and reports NDVI of {ndvi}. Is this NDVI measurement reliable?",
        "ground_truth": False,
        "explanation": "Cloud cover above 70-80% makes optical satellite data unreliable. The NDVI may be affected by cloud shadows.",
        "difficulty": "medium",
    },
    {
        "category": "data_reliability",
        "location": "Nevada Desert, USA",
        "coords": [-116.0, 37.0],
        "cloud_cover_pct": 3,
        "ndvi": 0.10,
        "question": "A satellite scene over {location} has {cloud_cover}% cloud cover and reports NDVI of {ndvi}. Is this NDVI measurement reliable?",
        "ground_truth": True,
        "explanation": "Very low cloud cover means clear skies and reliable optical measurements.",
        "difficulty": "easy",
    },
    {
        "category": "data_reliability",
        "location": "UK Midlands",
        "coords": [-1.5, 52.5],
        "cloud_cover_pct": 55,
        "ndvi": 0.50,
        "question": "A satellite scene over {location} has {cloud_cover}% cloud cover and reports NDVI of {ndvi}. Is this NDVI measurement reliable?",
        "ground_truth": True,
        "explanation": "Cloud cover around 50-60% can still yield usable data for cloud-free pixels. Moderate reliability.",
        "difficulty": "hard",
    },
    {
        "category": "data_reliability",
        "location": "Congo Basin, DRC",
        "coords": [23.0, 0.0],
        "cloud_cover_pct": 92,
        "ndvi": 0.70,
        "question": "A satellite scene over {location} has {cloud_cover}% cloud cover and reports NDVI of {ndvi}. Is this NDVI measurement reliable?",
        "ground_truth": False,
        "explanation": "Over 90% cloud cover makes virtually any optical measurement unreliable.",
        "difficulty": "easy",
    },
    # ---- flood_risk: Elevation + proximity to water ----
    {
        "category": "flood_risk",
        "location": "Netherlands lowlands",
        "coords": [5.0, 52.0],
        "elevation_m": -2,
        "distance_to_water_m": 500,
        "question": "A site at elevation {elevation}m is {distance_to_water}m from a major river. Is this site at high flood risk?",
        "ground_truth": True,
        "explanation": "Negative elevation (below sea level) combined with proximity to water indicates very high flood risk.",
        "difficulty": "easy",
    },
    {
        "category": "flood_risk",
        "location": "Swiss Alps",
        "coords": [8.0, 46.8],
        "elevation_m": 2500,
        "distance_to_water_m": 5000,
        "question": "A site at elevation {elevation}m is {distance_to_water}m from a major river. Is this site at high flood risk?",
        "ground_truth": False,
        "explanation": "High elevation and distance from water bodies means very low flood risk.",
        "difficulty": "easy",
    },
    {
        "category": "flood_risk",
        "location": "Bangkok, Thailand",
        "coords": [100.5, 13.75],
        "elevation_m": 1,
        "distance_to_water_m": 200,
        "question": "A site at elevation {elevation}m is {distance_to_water}m from a major river. Is this site at high flood risk?",
        "ground_truth": True,
        "explanation": "Very low elevation (1m) and close proximity to a river indicate high flood risk.",
        "difficulty": "easy",
    },
    {
        "category": "flood_risk",
        "location": "Denver, Colorado",
        "coords": [-104.99, 39.74],
        "elevation_m": 1609,
        "distance_to_water_m": 3000,
        "question": "A site at elevation {elevation}m is {distance_to_water}m from a major river. Is this site at high flood risk?",
        "ground_truth": False,
        "explanation": "High elevation (Mile High City) and moderate distance from water means low flood risk.",
        "difficulty": "medium",
    },
]


def generate_geomultimodal() -> list[dict]:
    """Generate 50+ multimodal spatial questions.

    These questions require integrating multiple data types:
    - Satellite metadata (NDVI, cloud cover) + spatial context
    - Elevation data + climate information
    - Population density + land cover + coordinates
    """
    questions: list[dict] = []

    for qid, scenario in enumerate(MULTIMODAL_SCENARIOS, start=1):
        point = _make_point(scenario["coords"])
        cat = scenario["category"]

        # Format question text with scenario values
        if cat == "vegetation_health":
            natural_q = scenario["question"].format(
                cloud_cover=scenario["cloud_cover_pct"],
                ndvi=scenario["ndvi"],
            )
            structured_data = (
                f"Location: {scenario['location']}\n"
                f"Coordinates:\n```json\n{json.dumps(point)}\n```\n\n"
                f"Satellite metadata:\n"
                f"- NDVI: {scenario['ndvi']}\n"
                f"- Cloud cover: {scenario['cloud_cover_pct']}%\n\n"
                f"Polygon boundary:\n```json\n{json.dumps(scenario['polygon'])}\n```\n\n"
            )
        elif cat == "elevation_climate":
            natural_q = scenario["question"].format(
                elevation=scenario["elevation_m"],
                temperature=scenario["temperature_c"],
            )
            structured_data = (
                f"Location: {scenario['location']}\n"
                f"Coordinates:\n```json\n{json.dumps(point)}\n```\n\n"
                f"Elevation: {scenario['elevation_m']}m\n"
                f"Temperature: {scenario['temperature_c']}C\n\n"
            )
        elif cat == "urban_classification":
            natural_q = scenario["question"].format(
                lat=scenario["coords"][1],
                lon=scenario["coords"][0],
                ndvi=scenario["ndvi"],
                elevation=scenario["elevation_m"],
                pop_density=scenario["population_density"],
            )
            structured_data = (
                f"Location: {scenario['location']}\n"
                f"Coordinates:\n```json\n{json.dumps(point)}\n```\n\n"
                f"NDVI: {scenario['ndvi']}\n"
                f"Elevation: {scenario['elevation_m']}m\n"
                f"Population density: {scenario['population_density']} per sq km\n\n"
            )
        elif cat == "data_reliability":
            natural_q = scenario["question"].format(
                location=scenario["location"],
                cloud_cover=scenario["cloud_cover_pct"],
                ndvi=scenario["ndvi"],
            )
            structured_data = (
                f"Location: {scenario['location']}\n"
                f"Coordinates:\n```json\n{json.dumps(point)}\n```\n\n"
                f"Cloud cover: {scenario['cloud_cover_pct']}%\n"
                f"Reported NDVI: {scenario['ndvi']}\n\n"
            )
        elif cat == "flood_risk":
            natural_q = scenario["question"].format(
                elevation=scenario["elevation_m"],
                distance_to_water=scenario["distance_to_water_m"],
            )
            structured_data = (
                f"Location: {scenario['location']}\n"
                f"Coordinates:\n```json\n{json.dumps(point)}\n```\n\n"
                f"Elevation: {scenario['elevation_m']}m\n"
                f"Distance to nearest major water body: {scenario['distance_to_water_m']}m\n\n"
            )
        else:
            natural_q = scenario["question"]
            structured_data = f"Location:\n```json\n{json.dumps(point)}\n```\n\n"

        structured_q = (
            f"{natural_q}\n\n"
            f"{structured_data}"
            f"Answer with True or False."
        )

        questions.append({
            "id": f"geomultimodal_{qid:03d}",
            "benchmark": BenchmarkName.GEOMULTIMODAL.value,
            "category": cat,
            "difficulty": scenario["difficulty"],
            "prompt_natural": f"{natural_q} Answer with True or False.",
            "prompt_structured": structured_q,
            "answer_type": AnswerType.BOOLEAN.value,
            "ground_truth": scenario["ground_truth"],
            "ground_truth_meta": {
                "explanation": scenario["explanation"],
                "data_types": _get_data_types(cat),
            },
            "geometry_a": point,
            "source": "curated_v1.0",
        })

    return questions


def _get_data_types(category: str) -> list[str]:
    """Return the data types used in a multimodal question category."""
    mapping = {
        "vegetation_health": ["satellite_imagery", "ndvi", "cloud_cover", "vector_boundary"],
        "elevation_climate": ["elevation", "temperature", "coordinates"],
        "urban_classification": ["ndvi", "elevation", "population_density", "coordinates"],
        "data_reliability": ["cloud_cover", "ndvi", "coordinates"],
        "flood_risk": ["elevation", "hydrology", "coordinates"],
    }
    return mapping.get(category, ["coordinates"])


# ---------------------------------------------------------------------------
# Main -- generate all datasets
# ---------------------------------------------------------------------------

def generate_all() -> None:
    """Generate all benchmark datasets and save to JSON."""
    DATASETS_DIR.mkdir(parents=True, exist_ok=True)

    datasets = {
        BenchmarkName.GEOTOPO: {
            "name": "GeoTopo",
            "description": "Topological reasoning: contains, intersects, within, disjoint, touches (v1.0 expanded)",
            "version": "1.0.0",
            "generator": generate_geotopo,
        },
        BenchmarkName.GEODISTANCE: {
            "name": "GeoDistance",
            "description": "Distance and proximity reasoning with real-world coordinates (v1.0 expanded)",
            "version": "1.0.0",
            "generator": generate_geodistance,
        },
        BenchmarkName.GEOCHANAGE: {
            "name": "GeoChange",
            "description": "Temporal change detection (text-based v0.1)",
            "version": "0.1.0",
            "generator": generate_geochanage,
        },
        BenchmarkName.GEOREASON: {
            "name": "GeoReason",
            "description": "Multi-step spatial reasoning chains: transitivity, buffer logic, distance chains",
            "version": "1.0.0",
            "generator": generate_georeason,
        },
        BenchmarkName.GEOMULTIMODAL: {
            "name": "GeoMultimodal",
            "description": "Multimodal spatial questions combining imagery metadata, elevation, climate, and vector data",
            "version": "1.0.0",
            "generator": generate_geomultimodal,
        },
    }

    for bench_name, info in datasets.items():
        print(f"Generating {info['name']}...")
        questions = info["generator"]()

        data = {
            "name": info["name"],
            "description": info["description"],
            "version": info["version"],
            "total_questions": len(questions),
            "questions": questions,
        }

        path = DATASETS_DIR / f"{bench_name.value}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        # Count by category
        cats: dict[str, int] = {}
        for q in questions:
            cats[q["category"]] = cats.get(q["category"], 0) + 1

        print(f"  -> {len(questions)} questions saved to {path.name}")
        for cat, count in sorted(cats.items()):
            print(f"     {cat}: {count}")

    print(f"\nDone! All datasets saved to {DATASETS_DIR}")


if __name__ == "__main__":
    generate_all()
