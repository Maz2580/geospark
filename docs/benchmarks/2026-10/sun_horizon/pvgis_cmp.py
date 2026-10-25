import json, sys, time, statistics
import httpx
import numpy as np
from geospark import visibility as v
SITES = [("Bright, Victoria", -36.7297, 146.9608), ("Marysville, Victoria", -37.5098, 145.7480),
         ("Hobart, Tasmania", -42.8821, 147.3272), ("Queenstown, New Zealand", -45.0312, 168.6626),
         ("Lauterbrunnen, Switzerland", 46.5935, 7.9091), ("Innsbruck, Austria", 47.2692, 11.4041),
         ("Chamonix, France", 45.9237, 6.8694), ("Cape Town, South Africa", -33.9249, 18.4241)]
out = []
for name, lat, lon in SITES:
    r = httpx.get("https://re.jrc.ec.europa.eu/api/v5_3/printhorizon", params={"lat": lat, "lon": lon, "outputformat": "json"}, timeout=60).json()
    prof = r["outputs"]["horizon_profile"]
    ref = {round((p["A"] + 180) % 360, 1): p["H_hor"] for p in prof}  # PVGIS: 0 = south, -90 = east
    t = time.time()
    h = v.horizon(lat, lon, observer_height_m=0.0, max_distance_m=30_000, step_deg=7.5)
    secs = time.time() - t
    ours = dict(zip(h["azimuths_deg"], h["horizon_elevation_deg"]))
    d = [ours[a] - ref[a] for a in ours if a in ref]
    out.append({"site": name, "lat": lat, "lon": lon, "pvgis_elevation_m": r["inputs"]["location"]["elevation"],
                "geospark_ground_m": h["ground_elevation_m"], "n": len(d), "mean_diff_deg": round(statistics.mean(d), 2),
                "mean_abs_diff_deg": round(statistics.mean(abs(x) for x in d), 2), "max_abs_diff_deg": round(max(abs(x) for x in d), 2),
                "corr": round(float(np.corrcoef([ours[a] for a in ours if a in ref], [ref[a] for a in ours if a in ref])[0, 1]), 3),
                "pvgis_max_deg": max(ref.values()), "geospark_max_deg": h["highest"]["elevation_deg"], "seconds": round(secs, 1),
                "pvgis": ref, "geospark": {str(k): ours[k] for k in ours}})
    print(json.dumps({k: out[-1][k] for k in out[-1] if k not in ("pvgis", "geospark")}), flush=True)
json.dump(out, open(sys.argv[1], "w"), indent=1)
