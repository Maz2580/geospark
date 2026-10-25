"""NREL SPA reference values (pvlib) for the sun cases written by make_cases.py."""
import json, sys
import pandas as pd, pvlib
cases = json.load(open(sys.argv[1]))
out = []
for c in cases["positions"]:
    t = pd.DatetimeIndex([pd.Timestamp(c["utc"])])
    sp = pvlib.solarposition.spa_python(t, c["lat"], c["lon"], altitude=0, pressure=101325, temperature=12)
    out.append({"apparent_elevation": float(sp["apparent_elevation"].iloc[0]), "azimuth": float(sp["azimuth"].iloc[0])})
rs = []
for c in cases["days"]:
    t = pd.DatetimeIndex([pd.Timestamp(c["local_noon_utc"])])
    r = pvlib.solarposition.sun_rise_set_transit_spa(t, c["lat"], c["lon"])
    rs.append({k: (None if pd.isna(r[k].iloc[0]) else pd.Timestamp(r[k].iloc[0]).isoformat()) for k in ("sunrise", "sunset", "transit")})
json.dump({"positions": out, "days": rs}, open(sys.argv[2], "w"))
