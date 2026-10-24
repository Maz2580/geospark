"""Datum and height-reference questions for Australia, with official answers.

Every answer is computed by PROJ's most accurate available operation (the EPSG/ICSM transformations
and Geoscience Australia's AUSGeoid2020 grid), and the operation and its stated accuracy are
recorded with the question. If a required grid is missing the script stops instead of falling back
to PROJ's "ballpark" operation (which treats AHD heights as ellipsoidal heights).

Run with PROJ_NETWORK=ON and PROJ_USER_WRITABLE_DIRECTORY set to a scratch folder.
"""
from __future__ import annotations

import json
from pathlib import Path

from pyproj.transformer import TransformerGroup

OUT = Path(__file__).parent / "datum_questions.json"
ANSWER_FORMAT = ("End your reply with one line of JSON only, exactly in this form: ")


def best(src: str, dst: str):
    group = TransformerGroup(src, dst, always_xy=True)
    t = group.transformers[0]
    if "ballpark" in t.description.lower():
        raise SystemExit(f"No accurate operation for {src} -> {dst}: {t.description}")
    if t.accuracy is None or t.accuracy < 0:  # a pure map projection (same datum) is exact
        if any(w in t.description for w in (" to GDA", " to AHD", "ITRF")):
            raise SystemExit(f"Datum change without a stated accuracy: {t.description}")
        t.__dict__["_exact"] = True
    return t


PLACES = {  # (lon, lat) on GDA2020, rounded; names are for the question text only
    "Federation Square, Melbourne": (144.9691, -37.8177),
    "the University of Melbourne (Parkville)": (144.9612, -37.7975),
    "Geelong": (144.3600, -38.1499),
    "Ballarat": (143.8503, -37.5622),
    "Hobart": (147.3272, -42.8821),
    "the Sydney Opera House": (151.2153, -33.8568),
    "Perth": (115.8605, -31.9505),
}
ZONE = {"Federation Square, Melbourne": 55, "the University of Melbourne (Parkville)": 55, "Geelong": 55,
        "Ballarat": 55, "Hobart": 55, "the Sydney Opera House": 56, "Perth": 50}

questions: list[dict] = []


def add(qid, group, prompt, answer, kind, method, accuracy, fmt):
    questions.append({"id": qid, "group": group, "prompt": f"{prompt}\n\n{ANSWER_FORMAT}{fmt}",
                      "answer": answer, "kind": kind, "method": method, "official_accuracy_m": accuracy})


# A. Same projected point, GDA94 MGA -> GDA2020 MGA (the ~1.5-1.8 m datum shift)
for i, (name, (lon, lat)) in enumerate(PLACES.items(), 1):
    z = ZONE[name]
    to94 = best("EPSG:7844", f"EPSG:283{z}")  # make the GDA94 MGA input from the GDA2020 point
    e94, n94 = to94.transform(lon, lat)
    t = best(f"EPSG:283{z}", f"EPSG:78{z}")
    e20, n20 = t.transform(e94, n94)
    add(f"datum_A{i}", "A: GDA94 to GDA2020 (MGA)",
        f"A survey point near {name} has GDA94 / MGA zone {z} coordinates E = {e94:.3f} m, N = {n94:.3f} m. "
        f"What are its GDA2020 / MGA zone {z} coordinates?",
        {"E": round(e20, 3), "N": round(n20, 3)}, "en", t.description, t.accuracy, '{"E": <metres>, "N": <metres>}')

# B. Ellipsoidal height (GNSS, drone) -> AHD, and one reverse
heights = [("Federation Square, Melbourne", 40.0), ("Mount Dandenong (summit area)", 640.0),
           ("Geelong", 30.0), ("the Sydney Opera House", 60.0), ("Perth", 40.0)]
extra = {"Mount Dandenong (summit area)": (145.3667, -37.8333)}
t = best("EPSG:7843", "EPSG:9463")
for i, (name, h) in enumerate(heights, 1):
    lon, lat = PLACES.get(name) or extra[name]
    _, _, ahd = t.transform(lon, lat, h)
    add(f"datum_B{i}", "B: ellipsoidal height to AHD",
        f"A drone's GNSS gives a GDA2020 ellipsoidal height of {h:.2f} m at latitude {lat}, longitude {lon} ({name}). "
        "What is the height of that point in the Australian Height Datum (AHD)?",
        {"AHD": round(ahd, 3)}, "height", t.description, t.accuracy, '{"AHD": <metres>}')
lon, lat = PLACES["Hobart"]
inv = best("EPSG:9463", "EPSG:7843")
_, _, ell = inv.transform(lon, lat, 25.0)
add("datum_B6", "B: ellipsoidal height to AHD",
    f"A design level in Hobart (latitude {lat}, longitude {lon}) is 25.00 m AHD. A GNSS rover set to GDA2020 "
    "ellipsoidal heights will be used to stake it out. What ellipsoidal height should the rover read?",
    {"ellipsoidal": round(ell, 3)}, "height_ell", inv.description, inv.accuracy, '{"ellipsoidal": <metres>}')

# C. Diagnose why two layers disagree
fs_lon, fs_lat = PLACES["Federation Square, Melbourne"]
e20, n20 = best("EPSG:7844", "EPSG:7855").transform(fs_lon, fs_lat)
e94, n94 = best("EPSG:7844", "EPSG:28355").transform(fs_lon, fs_lat)
e54, n54 = best("EPSG:7844", "EPSG:7854").transform(fs_lon, fs_lat)
_, _, ahd40 = t.transform(fs_lon, fs_lat, 40.0)
choices = ("Choose one: (a) same datum, the difference is ordinary survey noise; (b) one layer is GDA94 and "
           "the other GDA2020; (c) the coordinates were projected in the wrong MGA zone; (d) one layer has "
           "ellipsoidal heights and the other AHD heights.")
cases = [
    ("C1", f"E = {e94:.3f}, N = {n94:.3f}", "b"),
    ("C2", f"E = {e20 + 0.021:.3f}, N = {n20 - 0.017:.3f}", "a"),
    ("C3", f"E = {e54:.3f}, N = {n54:.3f}", "c"),
]
for cid, other, ans in cases:
    add(f"datum_{cid}", "C: diagnose a mismatch",
        f"Layer 1 (labelled GDA2020 / MGA zone 55) has a survey mark at Federation Square at E = {e20:.3f}, "
        f"N = {n20:.3f}. Layer 2, also labelled GDA2020 / MGA zone 55, has the same mark at {other}. "
        f"What is the most likely cause of the difference? {choices}",
        {"cause": ans}, "choice", "constructed from the official operations above", None, '{"cause": "<a|b|c|d>"}')
add("datum_C4", "C: diagnose a mismatch",
    f"Two surveys of the same mark at Federation Square agree horizontally, but survey 1 reports a height of "
    f"40.000 m and survey 2 reports {ahd40:.3f} m. Both say 'GDA2020'. What is the most likely cause? {choices}",
    {"cause": "d"}, "choice", "constructed from AUSGeoid2020", None, '{"cause": "<a|b|c|d>"}')

# D. Plate motion: ITRF2014 at the survey epoch -> GDA2020 (fixed at 2020.0)
itrf = best("EPSG:7912", "EPSG:7843")
for i, name in enumerate(["Federation Square, Melbourne", "Perth"], 1):
    lon, lat = PLACES[name]
    glon, glat, _, _ = itrf.transform(lon, lat, 50.0, 2026.8)
    add(f"datum_D{i}", "D: plate motion (ITRF2014 to GDA2020)",
        f"A GNSS receiver at {name} reports ITRF2014 coordinates at epoch 2026.8: latitude {lat:.7f}, "
        f"longitude {lon:.7f}, ellipsoidal height 50.000 m. What are the point's GDA2020 latitude and longitude?",
        {"lat": round(glat, 9), "lon": round(glon, 9)}, "latlon", itrf.description, itrf.accuracy,
        '{"lat": <degrees>, "lon": <degrees>}')

# E. Choose the right MGA zone
for i, (name, lon, lat, z) in enumerate([("Mildura", 142.1611, -34.1855, 54), ("Albury", 146.9135, -36.0737, 55)], 1):
    e, n = best("EPSG:7844", f"EPSG:78{z}").transform(lon, lat)
    add(f"datum_E{i}", "E: choose the MGA zone",
        f"Give the GDA2020 / MGA coordinates of {name} (GDA2020 latitude {lat}, longitude {lon}), in the MGA zone "
        "that contains it.", {"zone": z, "E": round(e, 3), "N": round(n, 3)}, "zone_en",
        f"GDA2020 / MGA zone {z} (EPSG:78{z})", 0.0, '{"zone": <number>, "E": <metres>, "N": <metres>}')

OUT.write_text(json.dumps(questions, indent=1, ensure_ascii=False))
print(f"{len(questions)} questions -> {OUT}")
for q in questions:
    print(q["id"], q["group"][:30], q["answer"], q["official_accuracy_m"])
