<!-- mcp-name: io.github.Maz2580/geospark -->
<p align="center">
  <h1 align="center">GeoSpark</h1>
  <p align="center"><strong>Verifiable spatial reasoning for large language models.</strong></p>
  <p align="center"><em>Distances, topology, coordinate reference systems and heights computed by a geometry engine and official geodetic models, not estimated by a language model. Open source, self-hostable, and usable by any model that can call a tool.</em></p>
</p>

<p align="center">
  <a href="https://github.com/Maz2580/geospark/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/Maz2580/geospark/ci.yml?branch=main&label=tests" alt="Tests"></a>
  <a href="https://pypi.org/project/geospark-ai/"><img src="https://img.shields.io/pypi/v/geospark-ai?color=blue" alt="PyPI"></a>
  <a href="https://pypi.org/project/geospark-ai/"><img src="https://img.shields.io/pypi/pyversions/geospark-ai" alt="Python"></a>
  <a href="https://github.com/Maz2580/geospark/pkgs/container/geospark"><img src="https://img.shields.io/badge/docker-ghcr.io-2496ED?logo=docker&logoColor=white" alt="Docker"></a>
  <a href="https://github.com/Maz2580/geospark/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-green" alt="License"></a>
</p>

---

GeoSpark provides language models with tools that **compute** spatial answers rather than estimate
them: geodesic distances, exact topology, official datum and height conversions, geocoding,
elevation, routing, open map data and live environmental data. Each result carries its sources,
licences, units and caveats, and a result that cannot be computed reliably is reported as such
rather than approximated. GeoSpark also checks users' own datasets (vector files, LiDAR point
clouds and elevation models) for the silent coordinate and height errors that most often corrupt
spatial analyses.

**Contents:** [Motivation and evaluation history](#motivation-and-evaluation-history) ·
[Capabilities](#capabilities) · [Access and installation](#access-and-installation) ·
[Usage](#usage) · [Command-line interface](#command-line-interface) · [Evaluation](#evaluation) ·
[Validation against authoritative sources](#validation-against-authoritative-sources) ·
[Limitations](#limitations) · [Self-hosting](#self-hosting) · [Release history](#release-history) ·
[Data attribution](#data-attribution) · [Development](#development) · [Citation](#citation)

## Motivation and evaluation history

GeoSpark is evaluated against the models in current use, and its scope follows the gaps that those
evaluations reveal.

- **GeoSpark Bench v2.** Across nine models of the time, small open-weight models (3.8B–9B
  parameters) answered numeric distance questions incorrectly about 95% of the time, and frontier
  APIs ranged from 25% to 95% correct. With GeoSpark's tools, every model that issued valid tool
  calls answered 76–96% correctly; a 7B model running on a CPU improved from 5% to 76%.
- **Re-evaluation with current models (October 2026).** Claude Opus 5.5 and GPT-6.1 now answer the
  same distance and topology questions correctly without tools, and with GeoSpark's tools a 4B open
  model on a workstation matches them. Distances between given points are no longer the limiting
  problem.
- **Identification of the next gap.** Both frontier models apply datum parameters, plate motion and
  map projections to the millimetre, but fail on conversions that require a national grid file:
  ellipsoidal (GNSS) heights to AHD, ODN, NZVD2016 or NAVD88, and British National Grid through
  OSTN15. Answering directly, including within the providers' own code sandboxes (which have no
  internet access), GPT-6.1 declined and Opus 5.5 estimated, with errors of up to 9.9 m. GeoSpark
  now performs these conversions with the official grids. When asked instead to write a script
  executed with internet access, both frontier models produced correct results; smaller local
  models did not.
- **Independent verification.** Agreement with PROJ demonstrates only that a model used the tool
  correctly. GeoSpark's own results were therefore compared with the published calculators and test
  data of Geoscience Australia, Ordnance Survey, LINZ and the US National Geodetic Survey, agreeing
  within millimetres with one disclosed exception. The same audit corrected statements in the
  project's documentation and fixed the edge cases it exposed.
- **Small-model safety.** Four open models on a local workstation were run through GeoSpark's
  question-answering loop to measure how often an incorrect answer is still reported as `ok`. Each
  failure mode found (unsupported numbers, empty answers, contradictory comparisons, an ambiguous
  place name resolved to the wrong country) is now detected; after the changes, 120 answers over
  three runs contained one silent error, which has since been fixed.

All questions, answer-generation scripts, harnesses and scored results are included in the
repository and can be re-run ([evaluation](#evaluation),
[October 2026 materials](https://github.com/Maz2580/geospark/tree/main/docs/benchmarks/2026-10)).

**Current state of the project**

- **A public website, REST API and hosted MCP server** at
  [geospark.terrascout.app](https://geospark.terrascout.app), offering question answering,
  reachable-area (isochrone) mapping, open map data exploration, and datum and height conversion.
- **Verifiable results:** sources and licences, units, caveats (an ambiguous place name, a DEM's
  accuracy, a local height datum) and a status of `ok`, `partial` or `cannot_answer`. An answer
  that relies on coordinates typed by the model, converts to a different system than the question
  specifies, or states quantities that no tool returned is marked `partial`.
- **Dataset checks** for vector files, LiDAR point clouds and elevation models: declared and actual
  coordinate reference systems, datum mix-ups, wrong zones, units, and height references.
- **Self-hostable on a single server** with a local model at no API cost: routing (Valhalla), an
  OpenStreetMap replica (Overpass) and the official geodetic grids, all under one data directory.
- **Open:** Apache-2.0 licence, about 1,250 offline tests, and re-runnable benchmarks.

## Capabilities

| | |
|---|---|
| **Spatial engine** | Geodesic distance, area and length (pyproj on WGS 84); topology predicates (contains, within, intersects, touches, crosses, overlaps, disjoint) via Shapely; shape-preserving buffers; union, intersection, difference, centroid and convex hull; CRS transformation of every input geometry |
| **Places and terrain** | Geocoding and reverse geocoding (OpenStreetMap Nominatim, within its usage policy: at most one request per second, cached); elevation from Copernicus GLO-30 with an Open Elevation fallback and vertical-datum awareness (NAVD88, EGM96, WGS 84); routing (OSRM); isochrones on foot, by bicycle or by car, and travel-time matrices (Valhalla) |
| **Official datums and heights** | Coordinate conversions with the published transformations and grids as implemented in PROJ (GDA94 to GDA2020, MGA zones, British National Grid via OSTN15, NAD27 to NAD83 via NADCON, ITRF at an epoch) and heights between the ellipsoid and AHD, ODN, NZVD2016 or NAVD88 with the official geoid models. Grids are downloaded once; PROJ's silent ballpark fallbacks are refused; every result states the operation used and its accuracy |
| **Sun and terrain** | Sun position and shadows (NOAA solar position, refraction included), sunrise and sunset, and hours of direct sun allowing for the terrain horizon; terrain horizon profiles and line of sight on the Copernicus DEM with Earth curvature and refraction, including first Fresnel zone clearance for radio links |
| **Dataset checks** | Vector files (GeoJSON, GeoPackage, Shapefile, GeoParquet, CSV and others), LiDAR (LAS, LAZ, COPC) and elevation models (GeoTIFF, COG): CRS consistency, axis order, zone, datum, units and height reference, and diagnosis of the offset between two datasets or between a surface and survey marks |
| **Live data** | Overture Maps places, buildings, roads and administrative areas (no key, via DuckDB); weather and forecasts (Open-Meteo, no key); air quality (OpenAQ v3, free key); active fires (NASA FIRMS, free key); satellite scene search (STAC) |
| **Agents** | `GeoAgent` (multi-step analysis from a plain-language goal), `SpatialReport` (a location dossier: amenities, accessibility, elevation, weather), `SiteSelector` (multi-criteria site ranking), and a coordinator that routes a goal to the appropriate agent |
| **Interfaces** | Python library, command-line interface (`geospark …`), REST API (59 documented operations, reference at `/docs`), MCP server (`geospark-mcp`), web interface |
| **Memory and workflows** | Spatial memory with facts, episodes and contradiction detection; a tiered context store; Flows (directed acyclic workflows, constructible from a natural-language goal) |
| **GeoSpark Bench** | 535 reproducible questions across topology, distance, multi-step reasoning, change and multimodal tasks, with computed ground truth |

## Access and installation

**Website.** [geospark.terrascout.app](https://geospark.terrascout.app) provides question
answering, reachable-area mapping and Overture Maps exploration around any location. Every result
shows its sources, caveats and units, and can be downloaded as GeoJSON.

**Hosted REST API** (open, no key required; [API reference](https://geospark.terrascout.app/docs)):

```bash
curl -X POST https://geospark.terrascout.app/api/v1/distance \
  -H "Content-Type: application/json" \
  -d '{"lat_a": 48.8584, "lon_a": 2.2945, "lat_b": 48.8606, "lon_b": 2.3376}'
# {"distance_m": 3172.01, "distance_km": 3.172, "note": "Geodesic distance on WGS84 ellipsoid"}
```

**Hosted MCP server.** In Claude or any MCP client, add a custom connector with the following URL
(in Claude: Settings → Connectors → Add custom connector):

```
https://geospark.terrascout.app/mcp
```

The hosted server is open, requires no key, offers 21 tools and applies the same rate limits as the
hosted API. It does not read files; tools for local files are available only from a locally run
server.

**Local MCP server** (Claude Desktop or any MCP client):

```bash
pip install "geospark-ai[mcp]"
```

Register the server in the MCP client's configuration. For Claude Desktop, the file is
`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS and
`%APPDATA%\Claude\claude_desktop_config.json` on Windows:

```json
{ "mcpServers": { "geospark": { "command": "geospark-mcp" } } }
```

The local server provides 25 read-only tools:

- **Computation:** `calculate_distance` (between place names, geocoded by the server, or
  coordinates), `check_spatial_relationship`, `spatial_operation` (buffer, area, length, centroid,
  convex hull), `transform_coordinates` and `convert_height`.
- **Places and data:** `geocode`, `reverse_geocode`, `get_elevation`, `route`, `get_weather`,
  `get_air_quality`, `get_active_fires` and `overture_features`.
- **Sun and terrain:** `sun_position`, `sun_times`, `terrain_horizon` and `line_of_sight`.
- **Analysis:** `isochrone`, `travel_time_matrix`, `location_report` and `select_site`.
- **Local files (local server only):** `check_dataset`, `layer_info`, `layer_count_within` and
  `layer_nearest`.

Results are returned as structured content with output schemas, usually GeoJSON, and carry
provenance (source, licence, attribution), units and warnings. When a result cannot be computed
reliably (invalid geometry, an unknown place, an unavailable data source), the tool returns an
error stating the reason, so that the model can report it instead of estimating. The server uses
MCP SDK 2.x (protocol 2026-07-28) and remains compatible with clients on earlier protocol versions.

**Python library:**

```bash
pip install geospark-ai                  # core
pip install "geospark-ai[api,mcp]"       # REST server and MCP server
pip install "geospark-ai[all]"           # all optional components
```

**Docker:**

```bash
docker run -p 8000:8000 ghcr.io/maz2580/geospark:latest
# then open http://localhost:8000
```

This image runs in development mode, in which operator routes are open; it is intended for local
use. A public deployment requires `-e GEOSPARK_ENV=production -e GEOSPARK_ADMIN_TOKEN=<secret>`
(see [Self-hosting](#self-hosting)).

## Usage

### Geometry

```python
from geospark.engine.spatial_reasoner import SpatialReasoner

park = {"type": "Polygon", "coordinates": [[[2.29, 48.85], [2.30, 48.85], [2.30, 48.86], [2.29, 48.86], [2.29, 48.85]]]}
point = {"type": "Point", "coordinates": [2.295, 48.855]}  # GeoJSON order: [lon, lat]

SpatialReasoner.check_relationship(park, point, "contains")  # True

SpatialReasoner.calculate_distance(
    {"type": "Point", "coordinates": [2.2945, 48.8584]},  # Eiffel Tower
    {"type": "Point", "coordinates": [2.3376, 48.8606]},  # Louvre
)  # 3172.01 (metres, geodesic)
```

### Queries through the engine

```python
from geospark import Engine
from geospark.protocol import SpatialOperation, SpatialQuery

engine = Engine(tools=["geocoder", "terrain"])

place = engine.execute(SpatialQuery(operation=SpatialOperation.GEOCODE,
                                    metadata={"query": "Federation Square, Melbourne"}))
print(place.features[0].geometry)  # {'type': 'Point', 'coordinates': [144.969..., -37.817...]}

# Inputs in another CRS are transformed to WGS 84 first, including the second geometry
buffered = engine.execute(SpatialQuery(operation=SpatialOperation.BUFFER,
                                       geometry={"type": "Point", "coordinates": [2.2945, 48.8584]},
                                       radius_m=100))
print(buffered.features[0].properties["area_sq_m"])  # ≈ 31,365
```

### Verifiable results

```python
result = engine.execute(SpatialQuery(operation=SpatialOperation.GEOCODE, metadata={"query": "Springfield"}))
result.status        # "ok" | "partial" | "cannot_answer"
result.warnings      # ["Ambiguous place name: 'Springfield, …, Illinois…'; '…Massachusetts…' …"]
result.provenance    # source, licence (ODbL-1.0), attribution, retrieved_at, method
result.spatial_context.units  # {"distance_m": "metre", ...}

import json
json.dump(result.to_geojson(), open("springfield.geojson", "w"))  # RFC 7946; opens directly in QGIS
```

Invalid input is refused rather than approximated: a self-intersecting polygon, out-of-range
coordinates or a probable [latitude, longitude] swap returns `cannot_answer` with the reason. From
the API, GeoJSON output is requested with `?format=geojson` (or `Accept: application/geo+json`);
from the CLI, with `--geojson out.geojson` on `geocode`, `elevation`, `query` or `report`. A
location report exported this way becomes a map layer containing the place and every nearby
amenity, with distances.

### Open map data: Overture Maps

```python
from geospark.tools.overture.client import query   # pip install "geospark-ai[overture]"

query("divisions", 48.8606, 2.3376)   # France › Île-de-France › Paris › Paris 1er Arrondissement
query("places", -37.8180, 144.9691, radius_m=200, category="cafe")  # nearest first, geodesic metres
query("buildings", -37.8180, 144.9691, radius_m=150)  # footprints, height, geodesic footprint area
query("transportation", -37.8180, 144.9691, radius_m=150)  # road and path segments, geodesic length
```

[Overture Maps](https://overturemaps.org) GeoParquet is queried directly on S3 with DuckDB, using
the release's STAC index to read only the files that cover the requested area; no download or key
is required. Results report the Overture release and the licence of the returned records. The same
data is available from the CLI (`geospark overture places -37.818 144.969 --category cafe`), the
REST API (`POST /api/v1/overture/{theme}`) and the MCP tool `overture_features`.

### Datum and height conversions

```python
from geospark import geodesy

# A drone's GNSS height at Federation Square, in the Australian Height Datum (AUSGeoid2020)
geodesy.convert_height(-37.8177, 144.9691, 40.0, "ellipsoidal", "AHD")
# {'height_m': 35.2574, 'separation_m': 4.7426, 'geoid_model': 'AUSGeoid2020', 'accuracy_m': 0.15, ...}

# GDA94 / MGA zone 55 to GDA2020 / MGA zone 55 (a 1.55 m shift), with the EPSG operation used
geodesy.transform("EPSG:28355", "EPSG:7855", [[321242.045, 5812466.767]]).as_dict()
```

PROJ falls back silently when a grid is missing: AHD becomes the ellipsoidal height (4.7 m in
error in Melbourne) and British National Grid coordinates move by about 124 m. GeoSpark downloads
the required grid or refuses the conversion. The conversions are also available as
`POST /api/v1/transform`, `POST /api/v1/height` and the MCP tools `transform_coordinates` and
`convert_height`. Grids are cached in `$GEOSPARK_DATA_DIR/proj`; `GEOSPARK_PROJ_NETWORK=false`
disables downloads. Agreement with the national agencies' own results is reported under
[Validation against authoritative sources](#validation-against-authoritative-sources).

### Sun, shadows and terrain visibility

```python
from geospark import sun, visibility

sun.shadow(-37.818, 144.969, "2026-06-21T12:00:00", object_height_m=10, tz="Australia/Melbourne")
# {'elevation_deg': 28.5587, 'azimuth_deg': 5.7072, 'shadow_length_m': 18.373, 'shadow_direction_deg': 185.7072, ...}

sun.sunlight_hours(-36.7297, 146.9608, "2026-06-21", tz="Australia/Melbourne")   # Bright, Victoria, midwinter
# {'flat_horizon_hours': 9.63, 'terrain_hours': 8.83, 'first_direct_sun': '2026-06-21T08:02+10:00', ...}

visibility.horizon(-36.7297, 146.9608, step_deg=5)            # skyline angle and obstruction distance per azimuth
visibility.line_of_sight(-37.8333, 145.35, -37.70, 145.10, height_a_m=100, height_b_m=10, frequency_mhz=900)
```

The Sun's position follows NOAA's solar calculator (after Meeus) and agrees with NREL's Solar
Position Algorithm to 0.014° in elevation (Sun above 5°); sunrise and sunset agree with NREL-based crossings to
within 5 s. Horizons are traced across the Copernicus GLO-30 DEM with Earth curvature and standard
refraction (k = 0.13) and agree with the European Commission's PVGIS horizon profiles to a mean of
0.2–0.9° at six of eight test sites (details under
[Validation against authoritative sources](#validation-against-authoritative-sources)). A line of
sight reports whether two points are intervisible, the minimum clearance and its location, and,
with `frequency_mhz`, the first Fresnel zone clearance. The same functions are available as
`POST /api/v1/sun`, `/api/v1/sun/times`, `/api/v1/sun/hours`, `/api/v1/horizon` and
`/api/v1/line-of-sight`, the CLI commands `geospark sun`, `geospark horizon` and `geospark los`, and
the MCP tools listed above. The approach to terrain rays follows
[geo-sleuth](https://github.com/Oldcircle/geo-sleuth) (MIT); the implementation is GeoSpark's own.

### Users' own data

```bash
pip install "geospark-ai[io]"
geospark layer info suburbs.gpkg                            # features, fields, CRS, geodesic area
geospark layer count-within crashes.csv suburbs.gpkg --geojson counts.geojson
geospark layer nearest schools.shp hospitals.geojson
geospark layer intersect parcels.gpkg flood_zones.geojson
```

Supported formats are GeoJSON, GeoPackage, Shapefile (or a .zip), GeoParquet, CSV with
longitude/latitude columns, FlatGeobuf, KML, GML and File Geodatabase. **The CRS is taken from the
file, never assumed silently:**

- a projected file (e.g. MGA zone 55) is reprojected, and its original CRS is reported;
- a Shapefile without a `.prj` file is refused until a CRS is given (`--crs EPSG:28355`);
- a CSV cannot declare a CRS: longitude/latitude columns are read as WGS 84 and the result states
  this (`--crs` overrides it for GDA94 or another datum); x/y columns are refused until a CRS is
  given;
- invalid geometries are refused unless `--repair` is passed.

Results include each file's SHA-256 digest, so that an analysis can be reproduced against exactly
the same data. In Python, `geospark.io.layers` provides `load_layer`, `count_within`, `nearest` and
`intersect`; the local MCP server provides the same operations as `layer_*` tools.

### Dataset checks

```bash
geospark layer check pipes.csv --crs EPSG:7855                          # CRS, datum and height caveats
geospark layer check pipes.csv --crs EPSG:7855 --against parcels.csv --against-crs EPSG:7855
# problem: pipes.csv sits 1.55 m from parcels.csv, matching the official GDA94 to GDA2020 shift here.
#          pipes.csv holds GDA94 coordinates but is treated as the same datum as parcels.csv.
```

A single file is checked for errors that produce no failure, only wrong numbers: no declared CRS,
projected values labelled as degrees (or the reverse), swapped latitude and longitude, points
outside the CRS's area of use, Australian data labelled WGS 84, and heights that do not state
whether they are ellipsoidal or AHD. With `--against`, the systematic offset to a reference layer
is measured and a cause is named only when the measured numbers match it: GDA94 data labelled
GDA2020 (compared with the official shift at that location), the wrong MGA zone, feet instead of
metres, swapped axes, a plate-motion epoch, or ellipsoidal against AHD heights. Any other offset is
reported as unexplained.

On 2,000 published Victorian survey marks, the check identified GDA94 coordinates labelled GDA2020
(1.55 m, scatter 3 cm), a wrong zone, and ellipsoidal against AHD heights, and reported no problem
when the same marks were labelled correctly (residual 6 mm). The command exits with code 2 when it
finds a problem, for use in data pipelines. The Python interface is
`geospark.io.check.check_layer` and `compare_layers`; the MCP tool is `check_dataset`.

**LiDAR point clouds and elevation models** (LAS, LAZ, COPC, GeoTIFF and COG, local or by URL) are
checked in the same way with the `pointcloud` extra, which reads them with
[terrio](https://github.com/opengeos/terrio) (pure Rust, without GDAL or PDAL):

```bash
pip install "geospark-ai[pointcloud]"
geospark layer check tile.laz                                   # CRS, vertical CRS, height units, ground class
geospark layer check tile.laz --against marks.csv --against-crs EPSG:7855
# problem: Heights differ by +4.74 m, the AUSGeoid2020 separation here (4.74 m): tile.laz has
#          ellipsoidal (GNSS) heights and the other AHD heights.
```

Against survey marks with heights, the surface height at each mark (the median of ground-classified
points within 1 m, or the DEM cell) is compared with the mark's height. Ellipsoidal heights labelled
as AHD, ODN, NZVD2016 or NAVD88, heights in feet, and an undeclared vertical CRS are identified.
terrio is used only for reading: datum and height conversions remain in GeoSpark's own geodesy
module, because terrio, like PROJ, keeps a height unchanged when a geoid grid is missing.

### Reproducible analyses

```bash
geospark record report "Federation Square, Melbourne" --out fedsq.json
geospark replay fedsq.json
# REPRODUCED: Same result as recorded.
# ... or DATA CHANGED: openstreetmap-overpass returned different data for the same request (step 6 ...)
# ... or CODE CHANGED: versions changed: {'shapely': ('2.0.0', '2.2.0')}
```

A run record contains:

- the environment: GeoSpark, Python, pyproj/PROJ and Shapely/GEOS versions;
- every data request (Nominatim, Overpass, Overture, Valhalla, weather, elevation) and every engine
  computation, each with a fingerprint of its input and output;
- a fingerprint of the final result.

`geospark replay` re-runs the analysis and reports whether it reproduced; if not, it identifies the
source that returned different data, or the code or library version that changed. The Python
interface is `geospark.runs.record_run(...)` and `replay(...)`.

### Natural-language questions

```python
result = engine.ask("How far is the Eiffel Tower from Big Ben?")
print(result.spatial_context.summary)
print(result.sources)  # the model, then each tool it called
```

`ask` uses a local [Ollama](https://ollama.com) model by default and falls back to free OpenRouter
models when `OPENROUTER_API_KEY` is set. Each answer is checked against the tool results: every
stated quantity must be traceable to a tool result (allowing unit changes, rounding, and sums or
differences of results), an empty answer is `cannot_answer`, and comparative claims ("X is closer")
are checked against the measured distances.

### Agents

```python
from geospark.agents import AgentCoordinator, GeoAgent, SiteSelector, SpatialReport

GeoAgent().run("Find all hospitals within 2km of the Eiffel Tower").findings["nearby"]

report = SpatialReport().analyze("Federation Square, Melbourne", radius_m=1000)
print(report.weather, report.accessibility, report.data_gaps)

best = SiteSelector().find(within="Zurich", near=["hospital", "school"], facility_type="pharmacy").best

AgentCoordinator().run("Find the best location for a cafe in Melbourne CBD near schools")
```

Agents use a language model to interpret the goal. Without one, a rule-based parser handles
requests such as those above, including multi-word place names, radii such as "2km", and amenity
types.

### Memory, context and flows

```python
from geospark.memory import SpatialIntelligence

intel = SpatialIntelligence()
intel.remember_fact("Eiffel Tower is at 48.8584 N, 2.2945 E", source="user")
intel.remember_episode("PM2.5 was 120 in Delhi", importance=0.8, source="tool:air_quality")
intel.recall("Where is the Eiffel Tower?", limit=5)  # semantic with Ollama embeddings, keyword match without
intel.find_contradictions()
```

```python
from geospark.flows import ChatFlowSession, FlowRunner, make_ollama_chat_fn

session = ChatFlowSession(llm_fn=make_ollama_chat_fn("qwen2.5:7b"))
result = session.run("Geocode Valencia, Spain then check its elevation")
if result.flow:
    FlowRunner().run(result.flow)  # a validated DAG, built one tool call at a time
```

## Command-line interface

```bash
geospark distance -37.8136 144.9631 -33.8688 151.2093   # Melbourne to Sydney: 713.86 km
geospark check contains '<geojson A>' '<geojson B>'
geospark geocode "Tokyo Tower, Japan"
geospark elevation -37.8177 144.9691
geospark isochrone -37.8180 144.9691 --minutes 5,10,15 --mode walk
geospark ask "Is Tokyo closer to Seoul or Beijing?"

geospark agent "Find all parks within 2km of Big Ben"
geospark report "Federation Square, Melbourne"
geospark site-select --within "Paris" --near "school,hospital" --facility pharmacy
geospark multi-agent "Analyze Federation Square" --stream

geospark data weather "Melbourne, Australia"
geospark data air-quality "Delhi"        # requires OPENAQ_API_KEY
geospark data fires "Amazon Rainforest"  # requires FIRMS_MAP_KEY

geospark layer check tile.laz --against marks.csv --against-crs EPSG:7855
geospark flow list
geospark flow build "Geocode Valencia then check its elevation" --run
geospark info                            # versions and optional components
```

## Evaluation

### GeoSpark Bench v2

GeoSpark Bench v2 evaluated nine models under three protocols: the bare question, step-by-step
reasoning (chain of thought), and the question with GeoSpark's MCP tools attached. The models were
five open-weight models of at most 9B parameters (Qwen 2.5 7B, Llama 3.1 8B, Gemma 2 9B, Mistral
7B, Phi-3.5 3.8B), gpt-oss 20B, and three frontier APIs (GPT-5.4, Claude Sonnet 4.5, Gemini 2.5
Pro). Intervals are Wilson 95% intervals, and the per-call cost ledger (about US$41) is included in
the repository. The full analysis is in a manuscript under peer review.

**Numeric distance** (`distance_absolute`, n = 80 per model; correct = within 10% of the
`pyproj.Geod.inv()` geodesic):

| Model | Tier | Bare LLM | Step-by-step | With GeoSpark tools |
|---|---|:---:|:---:|:---:|
| Qwen 2.5 7B | open ≤9B | 5.0% | 20.0% | **76.2%** |
| Llama 3.1 8B | open ≤9B | 5.0% | 21.2% | 7.5% ᵃ |
| Gemma 2 9B | open ≤9B | 37.5% ᵇ | 6.2% | — |
| Mistral 7B | open ≤9B | 2.5% | 2.5% | 0.0% ᵃ |
| Phi-3.5 3.8B | open ≤9B | 1.2% | 6.2% | — |
| gpt-oss 20B | open mid | **93.8%** | 93.8% | 91.2% |
| GPT-5.4 | frontier | 95.0% | 90.0% | 95.0% |
| Claude Sonnet 4.5 | frontier | 73.8% | 92.5% | **96.2%** |
| Gemini 2.5 Pro | frontier | 25.0% | 55.0% | 85.0% |

ᵃ The tools were available but not used correctly: Llama confused kilometres and metres in the
returned coordinates, and Mistral answered in plain text. ᵇ Gemma's correct answers are
well-known long-distance pairs, indicating recall of training data rather than computation.
— denotes not evaluated with tools.

**Findings**

- **Tools act as a leveller.** Bare-model accuracy ranges from 1% to 95%; with tools, every model
  that issues valid tool calls reaches 76–96%. Qwen gained 71 percentage points; GPT-5.4 gained
  none, having already reached 95%.
- **Aggregate scores conceal bias.** Qwen's 56% on topology results from a tendency to answer
  "yes": it scores 93% on `intersects` (where the data skews true) and 3% on `disjoint`. GPT-5.4
  scores 0% on `touches`. With GeoSpark, every predicate is answered correctly, because the engine
  computes it.
- **Step-by-step prompting is not a general remedy.** It improves some models and degrades others.
- **Knowledge questions do not require tools.** Questions such as "Did the Amazon lose forest
  between 2015 and 2023?" are answered well at every model scale without them.

The benchmark is re-run with `python -m geospark.bench run`, and the datasets regenerate
identically with `python -m geospark.bench.generate_datasets`. Provenance is documented in the
[datasets README](https://github.com/Maz2580/geospark/blob/main/geospark/bench/datasets/README.md)
and every table in the
[benchmark report](https://github.com/Maz2580/geospark/blob/main/docs/BENCHMARK_REPORT.md).

### Re-evaluation with current models (October 2026)

A sample of GeoSpark Bench was re-run on current frontier models and on open models served from a
local workstation, together with a new test of datum and height conversions. The questions, the
scripts that compute the reference answers, the harness and the scored results are in
[docs/benchmarks/2026-10](https://github.com/Maz2580/geospark/tree/main/docs/benchmarks/2026-10).

**GeoSpark Bench sample** (20 numeric-distance questions and 18 topology questions, three per
predicate, coordinates given; distance correct within 10% of the `pyproj` geodesic, topology exact):

| Model | Deployment | Without tools: distance / topology | With GeoSpark tools |
|---|---|:---:|:---:|
| Claude Opus 5.5 | API | 100% / 100% | 100% / 100% |
| GPT-6.1 | API | 95% ¹ / 100% | 100% / 100% |
| gpt-oss 20B | local workstation | 95% / 100% | 100% / 100% |
| Qwen 3.5 4B | local workstation | 90% / 100% | 100% / 100% |
| Qwen 3.5 9B | local workstation | — ² | 100% / 94% |
| Phi-4-mini 3.8B | local workstation | 15% / 50% | 20% / 50% ³ |

¹ One reply exhausted its length limit while reasoning and gave no number. ² Most replies timed
out on a heavily loaded workstation, so the run does not constitute a fair score. ³ The model never
called the tools. Gemma 4 12B timed out in the same way and is omitted.

Current frontier models answer these questions correctly without tools, and with tools a 4B model
on a workstation matches them.

**Datum and height conversions** (32 questions in Australia, the United Kingdom, New Zealand and
the United States; reference answers computed with PROJ's most accurate EPSG operations and the
national grids, and checked against the agencies' own services where available: GDA94 to GDA2020,
MGA zones, ITRF2014 to GDA2020 at an epoch, ellipsoidal heights to AHD, ODN, NZVD2016 and NAVD88,
OSTN15, NAD27 to NAD83). Survey-grade denotes agreement within 5 cm, or within the geoid model's
stated accuracy for heights:

| Model | Without tools: survey-grade | within 0.5 m | wrong | declined | With GeoSpark's geodesy tools |
|---|:---:|:---:|:---:|:---:|:---:|
| Claude Opus 5.5 | 15 | 7 | 8 (up to 5.3 m off) | 2 ⁴ | **31 survey-grade, 1 within 6 cm** |
| GPT-6.1 | 13 | 2 | 1 (1.65 m off) | 16 | **32 survey-grade** |

⁴ Two British National Grid answers exceeded an 8,000-token reply limit while computing by hand.

Because GeoSpark's tools also use PROJ, the with-tools column shows that the models used the tools
correctly; the correctness of PROJ's answers is established separately (see
[Validation against authoritative sources](#validation-against-authoritative-sources)). For the two
NAD27 questions, the reference is itself accurate only to about 0.27 m (NGS's stated uncertainty),
so "survey-grade" there denotes agreement with PROJ's NADCON rather than centimetre-level truth.

Both models apply datum parameters, plate motion and map projections to the millimetre. Answering
directly, neither can read the national grids on which heights and some datum conversions depend:
GPT-6.1 declines ("I cannot access the AUSGeoid2020 grid") and Opus 5.5 estimates from memory.
GeoSpark's [`transform_coordinates` and `convert_height`](#datum-and-height-conversions) close this
gap.

**Fairness checks** ([details](https://github.com/Maz2580/geospark/blob/main/docs/benchmarks/2026-10/fairness.md)).
The gap persists with the providers' own code execution at high effort (their sandboxes include
PROJ but no internet access; GPT-6.1 declined all 17 grid questions, and Opus 5.5 estimated with
errors of up to 9.9 m) and across three repeated runs. It does **not** persist when these frontier
models write a script that is executed with internet access: Opus 5.5 completed all eight everyday
GIS scripting tasks correctly, AHD included, and GPT-6.1 completed seven and failed safely on the
eighth. The silently incorrect scripts came from the smaller local models: gpt-oss 20B reported the
ellipsoidal height unchanged as "AHD", and Qwen 3.5 4B completed one of eight tasks. Web browsing
was not tested. The API cost of the October 2026 re-evaluation was US$8.46.

**Small local models with GeoSpark's tools**
([details](https://github.com/Maz2580/geospark/blob/main/docs/benchmarks/2026-10/small_models.md)).
Qwen 3.5 4B and 9B, gpt-oss 20B and Gemma 4 12B answered ten questions each through GeoSpark's
full tool set and answer checks. The measure of interest is the number of incorrect answers still
reported as `ok`. Before the changes, 4 of 30 answers returned no text and were reported as `ok`;
other failures included quantities absent from every tool result, a comparison contradicting the
measured distances, and "Gold Coast" resolved to Ghana. After the changes, 120 answers over three
runs contained one silent error (the Ghana case, since fixed); the remaining non-clean results were
correctly reported as `partial` or `cannot_answer`.

## Validation against authoritative sources

GeoSpark's geodetic results were compared with the agencies' published calculators and test data,
not only with PROJ
([details](https://github.com/Maz2580/geospark/blob/main/docs/benchmarks/2026-10/agency_checks.md)):

| Reference | Comparison | Agreement |
|---|---|---|
| Geoscience Australia calculators | GDA94 to GDA2020 and ATRF2014 to GDA2020, eight points | within 0.1 mm |
| Geoscience Australia AUSGeoid2020 | ellipsoidal to AHD heights, three cities | within 2 mm |
| Ordnance Survey OSTN15/OSGM15 test points | 40 points | grid within 8 mm, heights within 2 mm |
| LINZ NZVD2016 examples | published example points | within their 1 cm rounding |
| NGS GEOID18 service | ellipsoidal to NAVD88 | 1 mm |
| Victorian surveyed marks | GDA94 to GDA2020, 416 marks | within 7 mm |
| Victorian spirit-levelled marks | AUSGeoid2020 against levelled AHD, 99 marks | 6 mm median |
| NREL Solar Position Algorithm (pvlib) | apparent Sun elevation, 903 random cases above 5° | 0.014° maximum |
| NREL SPA, crossings sampled each second | sunrise and sunset, 899 events | 4.7 s maximum, 1.1 s median |
| PVGIS 5.3 horizon profiles | terrain horizon at 8 mountain and valley sites | 0.2–0.9° mean at 6 sites; 1.5° (urban) and 3.1° (sheer valley) at 2 |

The accuracy reported with each geodetic result is the accuracy EPSG states for the operation, not
a measurement. The sun and horizon comparisons are reported in full in
[docs/benchmarks/2026-10/sun_horizon.md](https://github.com/Maz2580/geospark/blob/main/docs/benchmarks/2026-10/sun_horizon.md).

## Limitations

- **NAD27 to NAD83** uses the original NADCON grids, about 0.27 m from NGS's current NADCON 5 in
  San Francisco (within NADCON 5's stated uncertainty).
- **AHD** is refused outside mainland Australia and Tasmania. OSGM15 heights on the Isles of
  Scilly, the Isle of Man, the Outer Hebrides, Orkney and Shetland are labelled with their local
  datum, not ODN.
- **LiDAR and DEM checks** have been tested on synthetic tiles and elevation models containing each
  error, and on reading the header of a public 10.6-million-point COPC file by URL (horizontal and
  vertical CRS in about 2 s). They have not yet been validated on a real delivery with known errors.
- **Terrain horizons and lines of sight** use a ~30 m surface model, which includes canopy and large
  buildings coarsely and nothing narrower than a cell; in sheer-walled valleys the horizon can differ
  from other DEMs by several degrees. Line of sight has been tested on synthetic terrain only.
- **Planned, not yet implemented:** slope, full viewshed maps, raster band mathematics and change
  detection.
  These operations are defined in the protocol but currently return an explicit "not implemented"
  error rather than a result.
- **Evaluation scope:** the October 2026 re-evaluation used samples (38 GeoSpark Bench questions,
  32 datum and height questions, eight scripting tasks, ten small-model questions); results on
  other question types and prompts may differ.

## Self-hosting

```bash
git clone https://github.com/Maz2580/geospark && cd geospark
cp .env.example .env     # set GEOSPARK_ENV=production and GEOSPARK_ADMIN_TOKEN
docker compose -f docker-compose.prod.yml up -d
```

The hosted API is designed to remain **open** without a key, with the following safeguards:

- An admin token protects operator routes (audit, usage, flow storage). The LLM gateway requires
  it or a revocable partner key.
- Public callers can select only the local model or free models, so paid API credit cannot be
  consumed by third parties.
- Each visitor receives a private, size-capped, automatically expiring sandbox for the memory and
  context demonstrations.
- Rate limits use the real client IP address, and language-model work has a concurrency limit.
- Inputs are bounded, and the audit log stores hashed IP addresses.

All state is stored under `GEOSPARK_DATA_DIR`. To lift Nominatim's public limits,
`GEOSPARK_NOMINATIM_URL` can point to a self-hosted server. Details are in
[deploy/DEPLOY.md](https://github.com/Maz2580/geospark/blob/main/deploy/DEPLOY.md#security) and
[`.env.example`](https://github.com/Maz2580/geospark/blob/main/.env.example).

## Release history

- **Unreleased:** sun position, sunrise, shadows and terrain-aware hours of sun; terrain horizons
  and lines of sight with Fresnel clearance; LiDAR and DEM dataset checks (`pointcloud` extra);
  compound-CRS area checks; national geoid selection for height comparisons.
- **0.10.0:** official datum and height conversions with national grids; `geospark layer check`
  for vector datasets; answer checks for small models; validation against national agencies.
- **0.9.0:** testing of every agent, tool and flow template on the live site; place-name inputs
  for question-answering tools; a self-hosted OpenStreetMap server; the hosted MCP server, listed
  in the official MCP Registry.
- **0.8.0:** Overture Maps buildings, places and roads through DuckDB; isochrones and travel-time
  matrices; users' own GeoJSON, GeoPackage and GeoParquet; reproducible run records; a redesigned
  website with a Proof panel on every result.
- **0.7.0:** verifiable answers: source, licence, timestamp, CRS and units on every result;
  `cannot_answer` instead of an estimate; data-quality flags; QGIS-ready GeoJSON; the MCP server
  updated to the 2026 specification.
- **Planned:** external benchmarks (GPSBench, GeoBenchX), a QGIS bridge, validation of the LiDAR
  checks on real deliveries, and further MCP tools.

Full release notes are in [CHANGELOG.md](https://github.com/Maz2580/geospark/blob/main/CHANGELOG.md).

## Data attribution

GeoSpark computes geometry locally but retrieves data from public services. Results derived from
them remain subject to the providers' licences and should credit them when published:

- **OpenStreetMap** (geocoding, amenities, map tiles): © OpenStreetMap contributors, [ODbL](https://www.openstreetmap.org/copyright)
- **Copernicus DEM GLO-30** (elevation): © DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018, provided under COPERNICUS by the European Union and ESA
- **Open-Meteo** (weather): [CC BY 4.0](https://open-meteo.com/)
- **OpenAQ** (air quality) and **NASA FIRMS** (active fires): subject to each provider's terms;
  air-quality results include each station's licence.

Elevation results include an `attribution` field for direct citation. The full list is in
[NOTICE](https://github.com/Maz2580/geospark/blob/main/NOTICE).

## Development

```bash
git clone https://github.com/Maz2580/geospark && cd geospark
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,api,mcp]"
pytest                       # about 1,250 tests; offline, never writing to ~/.geospark
ruff check geospark tests
```

Contributions are welcome; see
[CONTRIBUTING.md](https://github.com/Maz2580/geospark/blob/main/CONTRIBUTING.md). Security issues
should be reported privately as described in
[SECURITY.md](https://github.com/Maz2580/geospark/blob/main/SECURITY.md). The architecture is
described in [docs/ARCHITECTURE.md](https://github.com/Maz2580/geospark/blob/main/docs/ARCHITECTURE.md).

## Citation

Work that uses GeoSpark or GeoSpark Bench should cite it. GitHub's **"Cite this repository"**
button provides the reference from
[CITATION.cff](https://github.com/Maz2580/geospark/blob/main/CITATION.cff).

## Author

**Mazdak Ghasemi Tootkaboni** ([University of Melbourne](https://www.unimelb.edu.au/))
· ORCID [0000-0001-8084-5270](https://orcid.org/0000-0001-8084-5270) · GitHub [@Maz2580](https://github.com/Maz2580)

## License

[Apache 2.0](https://github.com/Maz2580/geospark/blob/main/LICENSE). Copyright 2024-2026 Mazdak Ghasemi Tootkaboni.
