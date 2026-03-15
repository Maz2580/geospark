"""
Generate benchmark datasets for GeoSpark Bench v0.1.

Run with:
    .venv/Scripts/python.exe -m geospark.bench.generate_datasets

Generates:
- geotopo.json    (100 topological reasoning questions)
- geodistance.json (100 distance/proximity questions)
- geochanage.json  (50 change detection questions)
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
# Real-world reference data
# ---------------------------------------------------------------------------

LANDMARKS = {
    "Eiffel Tower": {"coords": [2.2945, 48.8584], "city": "Paris", "country": "France"},
    "Louvre Museum": {"coords": [2.3376, 48.8606], "city": "Paris", "country": "France"},
    "Arc de Triomphe": {"coords": [2.2950, 48.8738], "city": "Paris", "country": "France"},
    "Notre-Dame": {"coords": [2.3500, 48.8530], "city": "Paris", "country": "France"},
    "Big Ben": {"coords": [-0.1246, 51.5007], "city": "London", "country": "UK"},
    "Tower of London": {"coords": [-0.0761, 51.5081], "city": "London", "country": "UK"},
    "Buckingham Palace": {"coords": [-0.1419, 51.5014], "city": "London", "country": "UK"},
    "Statue of Liberty": {"coords": [-74.0445, 40.6892], "city": "New York", "country": "USA"},
    "Empire State Building": {"coords": [-73.9857, 40.7484], "city": "New York", "country": "USA"},
    "Central Park": {"coords": [-73.9654, 40.7829], "city": "New York", "country": "USA"},
    "Times Square": {"coords": [-73.9855, 40.7580], "city": "New York", "country": "USA"},
    "Colosseum": {"coords": [12.4922, 41.8902], "city": "Rome", "country": "Italy"},
    "Vatican City": {"coords": [12.4534, 41.9029], "city": "Rome", "country": "Italy"},
    "Sydney Opera House": {"coords": [151.2153, -33.8568], "city": "Sydney", "country": "Australia"},
    "Tokyo Tower": {"coords": [139.7454, 35.6586], "city": "Tokyo", "country": "Japan"},
    "Burj Khalifa": {"coords": [55.2744, 25.1972], "city": "Dubai", "country": "UAE"},
    "Taj Mahal": {"coords": [78.0421, 27.1751], "city": "Agra", "country": "India"},
    "Great Wall (Badaling)": {"coords": [116.0046, 40.3588], "city": "Beijing", "country": "China"},
    "Christ the Redeemer": {"coords": [-43.2105, -22.9519], "city": "Rio", "country": "Brazil"},
    "Machu Picchu": {"coords": [-72.5450, -13.1631], "city": "Cusco", "country": "Peru"},
    "Pyramids of Giza": {"coords": [31.1342, 29.9792], "city": "Cairo", "country": "Egypt"},
    "Table Mountain": {"coords": [18.4041, -33.9628], "city": "Cape Town", "country": "South Africa"},
    "Golden Gate Bridge": {"coords": [-122.4783, 37.8199], "city": "San Francisco", "country": "USA"},
    "CN Tower": {"coords": [-79.3871, 43.6426], "city": "Toronto", "country": "Canada"},
    "Space Needle": {"coords": [-122.3493, 47.6205], "city": "Seattle", "country": "USA"},
}

# City bounding boxes (approximate, for polygon-based questions)
CITY_BBOXES = {
    "Paris": [2.22, 48.82, 2.42, 48.90],
    "London": [-0.30, 51.40, 0.10, 51.60],
    "New York": [-74.05, 40.65, -73.90, 40.85],
    "Rome": [12.40, 41.85, 12.55, 41.95],
    "Tokyo": [139.65, 35.60, 139.85, 35.75],
    "Sydney": [151.15, -33.90, 151.30, -33.80],
    "Dubai": [55.20, 25.15, 55.35, 25.30],
    "Cairo": [31.10, 29.95, 31.35, 30.10],
    "Cape Town": [18.35, -34.00, 18.55, -33.90],
}

# Polygon with a hole (Dr. Chen's suggestion — classic gotcha)
PARIS_WITH_HOLE = {
    "type": "Polygon",
    "coordinates": [
        # Outer ring (Paris bbox)
        [[2.22, 48.82], [2.42, 48.82], [2.42, 48.90], [2.22, 48.90], [2.22, 48.82]],
        # Hole (small area around Ile de la Cite)
        [[2.34, 48.855], [2.36, 48.855], [2.36, 48.860], [2.34, 48.860], [2.34, 48.855]],
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


# ---------------------------------------------------------------------------
# GeoTopo — Topological reasoning questions
# ---------------------------------------------------------------------------

def generate_geotopo() -> list[dict]:
    """Generate 100 topological reasoning questions."""
    questions = []
    qid = 0

    # Category 1: Point-in-polygon (contains) — 20 questions
    for city_name, bbox in list(CITY_BBOXES.items())[:5]:
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

    # Category 2: Polygon-polygon intersection — 20 questions
    city_list = list(CITY_BBOXES.items())
    for i in range(10):
        c1_name, c1_bbox = city_list[i % len(city_list)]
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

    # Category 3: Disjoint — 15 questions
    pairs = [(city_list[i], city_list[j])
             for i in range(len(city_list)) for j in range(i+1, len(city_list))]
    for (c1_name, c1_bbox), (c2_name, c2_bbox) in pairs[:15]:
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

    # Category 4: Within — 15 questions
    for city_name, bbox in list(CITY_BBOXES.items())[:5]:
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

        # Point within
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

    # Category 5: Polygon with hole (Dr. Chen's gotcha) — 10 questions
    hole_polygon = PARIS_WITH_HOLE
    for _i in range(5):
        # Point inside the hole (should NOT be contained)
        hole_pt = [round(RNG.uniform(2.34, 2.36), 6), round(RNG.uniform(48.855, 48.860), 6)]
        point = _make_point(hole_pt)
        gt = SpatialReasoner.check_relationship(hole_polygon, point, "contains")
        qid += 1
        questions.append(_topo_question(
            qid, "contains_with_hole", Difficulty.HARD,
            f"Paris has a defined boundary with an exclusion zone (hole). Does this boundary contain the point at ({hole_pt[1]:.4f}N, {hole_pt[0]:.4f}E)?",
            hole_polygon, point, gt,
            "Paris boundary (with exclusion zone)", "the point",
        ))

        # Point outside the hole but inside Paris (should be contained)
        safe_pt = _point_in_bbox([2.25, 48.83, 2.33, 48.85])
        point2 = _make_point(safe_pt)
        gt2 = SpatialReasoner.check_relationship(hole_polygon, point2, "contains")
        qid += 1
        questions.append(_topo_question(
            qid, "contains_with_hole", Difficulty.HARD,
            f"Paris has a defined boundary with an exclusion zone. Does this boundary contain the point at ({safe_pt[1]:.4f}N, {safe_pt[0]:.4f}E)?",
            hole_polygon, point2, gt2,
            "Paris boundary (with exclusion zone)", "the point",
        ))

    # Pad to exactly 100 with touches questions
    while len(questions) < 100:
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

    return questions[:100]


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
        "source": "generated_v0.1",
    }


# ---------------------------------------------------------------------------
# GeoDistance — Distance and proximity questions
# ---------------------------------------------------------------------------

def generate_geodistance() -> list[dict]:
    """Generate 100 distance/proximity questions."""
    questions = []
    qid = 0
    landmark_list = list(LANDMARKS.items())

    # Category 1: Absolute distance — 40 questions
    pairs = [(landmark_list[i], landmark_list[j])
             for i in range(len(landmark_list)) for j in range(i+1, len(landmark_list))]
    RNG.shuffle(pairs)

    for (name_a, info_a), (name_b, info_b) in pairs[:40]:
        point_a = _make_point(info_a["coords"])
        point_b = _make_point(info_b["coords"])
        distance_m = SpatialReasoner.calculate_distance(point_a, point_b)
        distance_km = distance_m / 1000

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

    # Category 2: Proximity threshold (within X km?) — 35 questions
    for (name_a, info_a), (name_b, info_b) in pairs[40:75]:
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
            "source": "generated_v0.1",
        })

    # Category 3: Nearest neighbor — 15 questions
    cities_with_landmarks = {}
    for name, info in LANDMARKS.items():
        cities_with_landmarks.setdefault(info["city"], []).append((name, info))

    for _city, lms in list(cities_with_landmarks.items())[:5]:
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
                "source": "generated_v0.1",
            })

    # Pad to 100 with additional proximity questions
    while len(questions) < 100:
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
            "source": "generated_v0.1",
        })

    return questions[:100]


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
        "source": "generated_v0.1",
    }


# ---------------------------------------------------------------------------
# GeoChange — Change detection questions (text-based v0.1)
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
    questions = []
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
# Main — generate all datasets
# ---------------------------------------------------------------------------

def generate_all():
    """Generate all benchmark datasets and save to JSON."""
    DATASETS_DIR.mkdir(parents=True, exist_ok=True)

    datasets = {
        BenchmarkName.GEOTOPO: {
            "name": "GeoTopo",
            "description": "Topological reasoning: contains, intersects, within, disjoint, touches",
            "version": "0.1.0",
            "generator": generate_geotopo,
        },
        BenchmarkName.GEODISTANCE: {
            "name": "GeoDistance",
            "description": "Distance and proximity reasoning with real-world coordinates",
            "version": "0.1.0",
            "generator": generate_geodistance,
        },
        BenchmarkName.GEOCHANAGE: {
            "name": "GeoChange",
            "description": "Temporal change detection (text-based v0.1)",
            "version": "0.1.0",
            "generator": generate_geochanage,
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
        cats = {}
        for q in questions:
            cats[q["category"]] = cats.get(q["category"], 0) + 1

        print(f"  -> {len(questions)} questions saved to {path.name}")
        for cat, count in sorted(cats.items()):
            print(f"     {cat}: {count}")

    print(f"\nDone! All datasets saved to {DATASETS_DIR}")


if __name__ == "__main__":
    generate_all()
