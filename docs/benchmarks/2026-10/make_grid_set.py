"""Questions whose official answer needs a national grid file, outside Australia (OSTN15, OSGM15,
NZGeoid2016, GEOID18, NADCON). Computed with PROJ's most accurate operation; ballpark refused."""
from __future__ import annotations

import json
import math
from pathlib import Path

from pyproj.transformer import TransformerGroup

OUT = Path(__file__).parent / "grid_questions.json"
FMT = "End your reply with one line of JSON only, exactly in this form: "


def best(src, dst):
    t = TransformerGroup(src, dst, always_xy=True).transformers[0]
    if "ballpark" in t.description.lower() or t.accuracy is None or t.accuracy < 0:
        raise SystemExit(f"no accurate operation {src}->{dst}: {t.description}")
    return t


qs = []


def add(qid, group, prompt, answer, kind, t, fmt):
    qs.append({"id": qid, "group": group, "prompt": f"{prompt}\n\n{FMT}{fmt}", "answer": answer, "kind": kind,
               "method": t.description, "official_accuracy_m": t.accuracy})


t = best("EPSG:4258", "EPSG:27700")
for i, (name, lon, lat) in enumerate([("London (Trafalgar Square)", -0.1281, 51.5080), ("Edinburgh", -3.1883, 55.9533),
                                      ("Penzance", -5.5371, 50.1188)], 1):
    e, n = t.transform(lon, lat)
    add(f"grid_UK{i}", "UK: ETRS89 to British National Grid (OSTN15)",
        f"A GNSS survey in {name} gives ETRS89 latitude {lat}, longitude {lon}. What are the point's OSGB36 / "
        "British National Grid coordinates (easting and northing), as Ordnance Survey's official transformation gives them?",
        {"E": round(e, 3), "N": round(n, 3)}, "en", t, '{"E": <metres>, "N": <metres>}')

t = best("EPSG:4937", "EPSG:7405")
for i, (name, lon, lat, h) in enumerate([("London (Trafalgar Square)", -0.1281, 51.5080, 70.0), ("Edinburgh", -3.1883, 55.9533, 120.0)], 1):
    *_, H = t.transform(lon, lat, h)
    add(f"grid_UKH{i}", "UK: ellipsoidal height to ODN (OSGM15)",
        f"A GNSS receiver in {name} (ETRS89 latitude {lat}, longitude {lon}) reports an ellipsoidal height of {h:.2f} m. "
        "What is the height in Ordnance Datum Newlyn (ODN)?", {"H": round(H, 3)}, "height", t, '{"H": <metres>}')

t = best("EPSG:4959", "EPSG:7839")
for i, (name, lon, lat, h) in enumerate([("Auckland", 174.7633, -36.8485, 100.0), ("Wellington", 174.7762, -41.2865, 60.0)], 1):
    out = t.transform(lon, lat, h)
    add(f"grid_NZ{i}", "NZ: ellipsoidal height to NZVD2016",
        f"A GNSS receiver in {name} (NZGD2000 latitude {lat}, longitude {lon}) reports an ellipsoidal height of {h:.2f} m. "
        "What is the height in the New Zealand Vertical Datum 2016 (NZVD2016)?", {"H": round(out[2], 3)}, "height", t,
        '{"H": <metres>}')

t = best("EPSG:6319", "EPSG:6318+5703")
for i, (name, lon, lat, h) in enumerate([("San Francisco", -122.4194, 37.7749, 100.0), ("Denver", -104.9903, 39.7392, 1580.0)], 1):
    *_, H = t.transform(lon, lat, h)
    add(f"grid_US{i}", "US: ellipsoidal height to NAVD88 (GEOID18)",
        f"A GNSS receiver in {name} (NAD83(2011) latitude {lat}, longitude {lon}) reports an ellipsoidal height of "
        f"{h:.2f} m. What is the NAVD88 orthometric height in metres?", {"H": round(H, 3)}, "height", t, '{"H": <metres>}')

group = TransformerGroup("EPSG:4267", "EPSG:4269", always_xy=True).transformers
for i, (name, lon, lat) in enumerate([("San Francisco", -122.4194, 37.7749), ("New York (Manhattan)", -74.0060, 40.7128)], 1):
    # the most accurate operation that covers this point (some are regional grids)
    ok = [(op.accuracy, op, op.transform(lon, lat)) for op in group
          if op.accuracy and op.accuracy > 0 and "ballpark" not in op.description.lower()]
    ok = [x for x in ok if math.isfinite(x[2][0]) and math.isfinite(x[2][1])]
    if not ok:
        raise SystemExit(f"NAD27->NAD83 failed for {name}")
    _, t, (lo, la) = min(ok, key=lambda x: x[0])
    add(f"grid_NAD{i}", "US: NAD27 to NAD83 (NADCON)",
        f"An old map of {name} gives NAD27 latitude {lat}, longitude {lon}. What are the NAD83 latitude and "
        "longitude of that point, as the official NADCON transformation gives them?", {"lat": round(la, 8), "lon": round(lo, 8)},
        "latlon", t, '{"lat": <degrees>, "lon": <degrees>}')

OUT.write_text(json.dumps(qs, indent=1, ensure_ascii=False))
for q in qs:
    print(q["id"], q["answer"], q["official_accuracy_m"], q["method"][:60])
