"""The sun cases (seeded): 2,000 random positions 2000-2050 and 300 random days in 2026."""
import json, random, sys
from datetime import datetime, timedelta, timezone

random.seed(20261025)
pos = []
for _ in range(2000):
    t = datetime(2000, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=random.uniform(0, 50 * 365.25 * 86400))
    pos.append({"lat": round(random.uniform(-80, 80), 4), "lon": round(random.uniform(-180, 180), 4), "utc": t.isoformat()})
days = []
for _ in range(300):
    lat, lon = round(random.uniform(-60, 60), 4), round(random.uniform(-180, 180), 4)
    d = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=random.randrange(365))
    days.append({"lat": lat, "lon": lon, "utc_date": d.date().isoformat(),
                 "local_noon_utc": (d + timedelta(hours=12 - lon / 15)).isoformat()})
json.dump({"positions": pos, "days": days}, open(sys.argv[1], "w"))
