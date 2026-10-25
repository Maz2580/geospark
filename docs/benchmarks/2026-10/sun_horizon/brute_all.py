import json, sys, pandas as pd, pvlib, numpy as np
cases = json.load(open(sys.argv[1]))["days"]
out = []
for c in cases:
    noon = pd.Timestamp(c["local_noon_utc"])
    t = pd.date_range(noon - pd.Timedelta(hours=18), noon + pd.Timedelta(hours=18), freq="1s")
    e = pvlib.solarposition.spa_python(t, c["lat"], c["lon"], altitude=0, pressure=101325, temperature=12)["elevation"].to_numpy()
    idx = np.where(np.diff(np.sign(e + 0.8333)) != 0)[0]
    out.append([{"kind": "sunrise" if e[i + 1] > e[i] else "sunset", "t": t[i].isoformat()} for i in idx])
json.dump(out, open(sys.argv[2], "w"))
