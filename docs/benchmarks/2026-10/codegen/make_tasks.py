"""8 everyday GIS scripting tasks, with inputs and independently computed answers."""
import csv, json, math, os, sys
from pathlib import Path
from pyproj import Geod
from shapely.geometry import Polygon, LineString, Point, mapping
from geospark import geodesy

OUT = Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)
G = Geod(ellps="WGS84")
tasks = []

def fc(features):  # GeoJSON FeatureCollection, lon/lat (RFC 7946)
    return {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": p, "geometry": mapping(g)} for g, p in features]}

def add(tid, files, prompt, answer, key, tol, unit):
    d = OUT / tid; d.mkdir(exist_ok=True)
    for name, content in files.items():
        (d / name).write_text(content)
    tasks.append({"id": tid, "prompt": prompt, "answer": answer, "key": key, "tol": tol, "unit": unit})

# T1 area of a Melbourne CBD-sized block (lon/lat GeoJSON)
cbd = Polygon([(144.9510, -37.8220), (144.9740, -37.8160), (144.9800, -37.8080), (144.9580, -37.8090), (144.9510, -37.8220)])
area = abs(G.geometry_area_perimeter(cbd)[0])
add("t1_area", {"precinct.geojson": json.dumps(fc([(cbd, {"name": "precinct"})]))},
    "precinct.geojson contains one polygon (a precinct in Melbourne). Write a Python script that prints its area in square metres.",
    area, "area_m2", 0.01, "m²")

# T2 500 m buffer around a point, area of the buffer
add("t2_buffer", {"site.geojson": json.dumps(fc([(Point(144.9631, -37.8136), {"name": "site"})]))},
    "site.geojson contains one point in Melbourne. Write a Python script that creates a 500 metre buffer around it and prints the buffer's area in square metres.",
    math.pi * 500 ** 2, "area_m2", 0.01, "m²")

# T3 distance between two points
a, b = (144.9631, -37.8136), (144.3600, -38.1499)
add("t3_distance", {"places.geojson": json.dumps(fc([(Point(*a), {"name": "Melbourne"}), (Point(*b), {"name": "Geelong"})]))},
    "places.geojson contains two points, Melbourne and Geelong. Write a Python script that prints the distance between them in metres.",
    G.inv(*a, *b)[2], "distance_m", 0.005, "m")

# T4 length of a road
road = LineString([(144.9631, -37.8136), (144.9700, -37.8000), (144.9850, -37.7900), (145.0000, -37.7850)])
add("t4_length", {"road.geojson": json.dumps(fc([(road, {"name": "road"})]))},
    "road.geojson contains one road as a LineString. Write a Python script that prints its length in metres.",
    G.geometry_length(road), "length_m", 0.005, "m")

# T5 area of a parcel delivered in Web Mercator
from pyproj import Transformer
to3857 = Transformer.from_crs(4326, 3857, always_xy=True)
parcel = Polygon([(145.0000, -37.8000), (145.0100, -37.8000), (145.0100, -37.8080), (145.0000, -37.8080), (145.0000, -37.8000)])
merc = Polygon([to3857.transform(x, y) for x, y in parcel.exterior.coords])
gj = fc([(merc, {"name": "parcel"})]); gj["crs"] = {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::3857"}}
add("t5_mercator_area", {"parcel.geojson": json.dumps(gj)},
    "parcel.geojson contains one land parcel near Melbourne; its coordinates are in EPSG:3857 (Web Mercator). Write a Python script that prints the parcel's true area on the ground in square metres.",
    abs(G.geometry_area_perimeter(parcel)[0]), "area_m2", 0.01, "m²")

# T6 count points within 1 km
centre = (144.9631, -37.8136)
pts = []
for i, (az, dist) in enumerate([(0, 600), (45, 950), (90, 990), (135, 1010), (180, 1050), (225, 700), (270, 1200), (315, 980), (20, 1500), (200, 400)]):
    lon, lat, _ = G.fwd(*centre, az, dist)
    pts.append((Point(lon, lat), {"id": i + 1}))
add("t6_within", {"centre.geojson": json.dumps(fc([(Point(*centre), {"name": "centre"})])), "shops.geojson": json.dumps(fc(pts))},
    "centre.geojson has one point and shops.geojson has shop locations, all in Melbourne. Write a Python script that prints how many shops are within 1 km of the centre.",
    sum(1 for g, _ in pts if G.inv(*centre, g.x, g.y)[2] <= 1000), "count", 0, "shops")

# T7 MGA94 zone 55 survey points to GDA2020 latitude/longitude
mga = [(321242.045, 5812466.767), (320498.0, 5814694.0), (268668.0, 5774259.0)]
truth = geodesy.transform("EPSG:28355", "EPSG:7844", [list(p) for p in mga]).coordinates
rows = "id,easting,northing\n" + "".join(f"{i+1},{e},{n}\n" for i, (e, n) in enumerate(mga))
add("t7_gda2020", {"survey.csv": rows},
    "survey.csv has survey points with easting and northing in GDA94 / MGA zone 55 (Victoria, Australia). Write a Python script that prints, for the first point, its GDA2020 latitude and longitude in decimal degrees.",
    {"lat": truth[0][1], "lon": truth[0][0]}, "latlon", 0.05, "m")

# T8 drone ellipsoidal heights to AHD
h = 40.0
ahd = geodesy.convert_height(-37.8177, 144.9691, h, "ellipsoidal", "AHD")["height_m"]
add("t8_ahd", {"drone.csv": "id,latitude,longitude,ellipsoidal_height\n1,-37.8177,144.9691,40.0\n"},
    "drone.csv has a drone survey point in Melbourne: GDA2020 latitude, longitude and ellipsoidal height (metres) from GNSS. Write a Python script that prints its height in the Australian Height Datum (AHD).",
    ahd, "height_m", 0.15, "m")

(OUT / "tasks.json").write_text(json.dumps(tasks, indent=1))
for t in tasks: print(t["id"], t["answer"])
