<!-- mcp-name: io.github.maz2580/geospark -->
<p align="center">
  <h1 align="center">GeoSpark</h1>
  <p align="center"><strong>Verifiable spatial reasoning for any LLM.</strong></p>
  <p align="center"><em>Distances, topology and CRS computed by a geometry engine, not guessed by a language model. Open source, runs anywhere, works with any model that can call a tool.</em></p>
</p>

<p align="center">
  <a href="https://github.com/Maz2580/geospark/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/Maz2580/geospark/ci.yml?branch=main&label=tests" alt="Tests"></a>
  <a href="https://pypi.org/project/geospark-ai/"><img src="https://img.shields.io/pypi/v/geospark-ai?color=blue" alt="PyPI"></a>
  <a href="https://pypi.org/project/geospark-ai/"><img src="https://img.shields.io/pypi/pyversions/geospark-ai" alt="Python"></a>
  <a href="https://github.com/Maz2580/geospark/pkgs/container/geospark"><img src="https://img.shields.io/badge/docker-ghcr.io-2496ED?logo=docker&logoColor=white" alt="Docker"></a>
  <a href="https://github.com/Maz2580/geospark/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-green" alt="License"></a>
</p>

---

Ask an LLM *"How far is the Eiffel Tower from the Louvre?"* or *"Is this point inside that polygon?"*
and the answer depends on which model you picked. Across 9 models we benchmarked, small open-weight
models (3.8B–9B) got numeric distance questions wrong about 95% of the time. Frontier APIs ranged
from 25% (Gemini 2.5 Pro) to 95% (GPT-5.4) correct.

GeoSpark gives the model tools that **compute** the answer: geodesic distances on the WGS84
ellipsoid, exact topology, CRS transformations, geocoding, elevation and live environmental data.
With them, every model that made valid tool calls answered 76–96% of the same questions correctly.
A 7B model on your own CPU then performs like a paid frontier API, and every answer comes with a
deterministic trace you can check.

## Try it

**No install: the hosted API** (open, no key needed; [interactive docs](https://geospark.terrascout.app/docs))

```bash
curl -X POST https://geospark.terrascout.app/api/v1/distance \
  -H "Content-Type: application/json" \
  -d '{"lat_a": 48.8584, "lon_a": 2.2945, "lat_b": 48.8606, "lon_b": 2.3376}'
# {"distance_m": 3172.01, "distance_km": 3.172, "note": "Geodesic distance on WGS84 ellipsoid"}
```

**In Claude Desktop or any MCP client**

```bash
pip install "geospark-ai[mcp]"
```

Add GeoSpark to your MCP client's config. For Claude Desktop that's
`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS, or
`%APPDATA%\Claude\claude_desktop_config.json` on Windows:

```json
{ "mcpServers": { "geospark": { "command": "geospark-mcp" } } }
```

That gives the model fifteen read-only tools. **Computation:** `calculate_distance`,
`check_spatial_relationship` and `spatial_operation` (buffer, area, length, centroid, convex hull).
**Places and data:** `geocode`, `reverse_geocode`, `get_elevation`, `route`, `get_weather`,
`get_air_quality`, `get_active_fires` and `overture_features`. **Analysis:** `isochrone`, `travel_time_matrix`, `location_report` and `select_site`.

Results come back as structured content with output schemas, usually GeoJSON. They carry
provenance (source, licence, attribution), units and warnings. When GeoSpark can't answer reliably
(invalid geometry, unknown place, a data source down), the tool returns an error that says why, so
the model can tell the user instead of estimating. The server uses MCP SDK 2.x (protocol
2026-07-28) and still works with clients on older protocol versions.

**As a Python library**

```bash
pip install geospark-ai              # core
pip install "geospark-ai[api,mcp]"   # + REST server and MCP server
pip install "geospark-ai[all]"       # everything
```

**Run your own server with Docker**

```bash
docker run -p 8000:8000 ghcr.io/maz2580/geospark:latest
# then open http://localhost:8000
```

That runs in development mode, where operator routes are open: fine on your own machine. For a
public server, add `-e GEOSPARK_ENV=production -e GEOSPARK_ADMIN_TOKEN=<secret>` (see
[Self-hosting](#self-hosting)).

## What it does

| | |
|---|---|
| **Spatial engine** | Geodesic distance, area and length (pyproj on WGS84); topology checks (contains, within, intersects, touches, crosses, overlaps, disjoint) via Shapely; shape-preserving buffers; union, intersection, difference, centroid, convex hull; CRS transformation of every input geometry |
| **Places and terrain** | Geocoding and reverse geocoding (OpenStreetMap Nominatim, following its usage policy: ≤ 1 request/s and cached); elevation from Copernicus GLO-30 with Open Elevation fallback and vertical-datum awareness (NAVD88 / EGM96 / WGS84); routing (OSRM); **isochrones** (where can I reach in N minutes on foot, by bike or by car) and travel-time matrices (Valhalla) |
| **Live data** | Overture Maps places, buildings, roads and admin areas (no key, via DuckDB); weather and forecasts (Open-Meteo, no key); air quality (OpenAQ v3, free key); active fires (NASA FIRMS, free key); satellite scene search (STAC) |
| **Agents** | `GeoAgent` (multi-step analysis from a plain-English goal), `SpatialReport` (a location dossier: amenities, accessibility, elevation, weather), `SiteSelector` (multi-criteria site ranking), and a coordinator that routes a goal to the right one |
| **Interfaces** | Python library, CLI (`geospark …`), REST API (49 documented operations), MCP server (`geospark-mcp`), web playground |
| **Memory and workflows** | Spatial memory with facts, episodes and contradiction detection; a tiered context store; Flows (DAG workflows, buildable from a natural-language goal) |
| **GeoSpark Bench** | 535 reproducible questions across topology, distance, multi-step reasoning, change and multimodal tasks, with computed ground truth |

**Planned, not built yet:** slope, viewshed, raster band math and change detection. These
operations exist in the protocol, but today they return a clear "not implemented yet" error rather
than an answer. See the [roadmap](#roadmap).

## Quick start

### Ground-truth geometry

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

# Inputs in another CRS are transformed to WGS84 first, including the second geometry
buffered = engine.execute(SpatialQuery(operation=SpatialOperation.BUFFER,
                                       geometry={"type": "Point", "coordinates": [2.2945, 48.8584]},
                                       radius_m=100))
print(buffered.features[0].properties["area_sq_m"])  # ≈ 31,365
```

### Every answer is checkable, and opens in QGIS

```python
result = engine.execute(SpatialQuery(operation=SpatialOperation.GEOCODE, metadata={"query": "Springfield"}))
result.status        # "ok" | "partial" | "cannot_answer"
result.warnings      # ["Ambiguous place name: 'Springfield, …, Illinois…'; '…Massachusetts…' …"]
result.provenance    # source, licence (ODbL-1.0), attribution, retrieved_at, method
result.spatial_context.units  # {"distance_m": "metre", ...}

import json
json.dump(result.to_geojson(), open("springfield.geojson", "w"))  # RFC 7946, drag into QGIS
```

GeoSpark refuses rather than guesses. A self-intersecting polygon, out-of-range coordinates or a
likely [lat, lon] swap gets `cannot_answer` with the reason, not a confident wrong number. From
the API, add `?format=geojson` (or `Accept: application/geo+json`). From the CLI, add
`--geojson out.geojson` to `geocode`, `elevation`, `query` or `report`. A location report becomes a
map layer: the place plus every nearby amenity, with distances.

### Open map data with no API key: Overture Maps

```python
from geospark.tools.overture.client import query   # pip install "geospark-ai[overture]"

query("divisions", 48.8606, 2.3376)   # the Louvre is in: France › Île-de-France › Paris › Paris 1er Arrondissement
query("places", -37.8180, 144.9691, radius_m=200, category="cafe")  # nearest first, geodesic metres
query("buildings", -37.8180, 144.9691, radius_m=150)  # footprints, height, geodesic footprint area
query("transportation", -37.8180, 144.9691, radius_m=150)  # road/path segments, geodesic length
```

GeoSpark queries [Overture Maps](https://overturemaps.org) GeoParquet directly on S3 with DuckDB. It
uses the release's STAC index to read only the files covering your area, so there's no download and
no key. Results report the Overture release and the licence of the records returned. The same data is
available from the CLI (`geospark overture places -37.818 144.969 --category cafe`), the REST API
(`POST /api/v1/overture/{theme}`) and the MCP tool `overture_features`.

### Your own data

```bash
pip install "geospark-ai[io]"
geospark layer info suburbs.gpkg                            # features, fields, CRS, geodesic area
geospark layer count-within crashes.csv suburbs.gpkg --geojson counts.geojson
geospark layer nearest schools.shp hospitals.geojson
geospark layer intersect parcels.gpkg flood_zones.geojson
```

Formats: GeoJSON, GeoPackage, Shapefile (or a .zip), GeoParquet, CSV with longitude/latitude
columns, FlatGeobuf, KML, GML, File Geodatabase. **The CRS is never guessed**:
- a projected file (e.g. MGA zone 55) is reprojected, and its original CRS is reported;
- a Shapefile without `.prj` is refused until you pass `--crs EPSG:28355`;
- invalid shapes are refused until you pass `--repair`.

Results carry each file's SHA-256, so an analysis can be reproduced against exactly that data. In
Python, use `geospark.io.layers` (`load_layer`, `count_within`, `nearest`, `intersect`). The local
MCP server (`geospark-mcp`) offers the same as `layer_*` tools; the hosted `/mcp` endpoint never reads
files.

### Reproducible analyses

```bash
geospark record report "Federation Square, Melbourne" --out fedsq.json
geospark replay fedsq.json
# REPRODUCED: Same result as recorded.
# ... or DATA CHANGED: openstreetmap-overpass returned different data for the same request (step 6 ...)
# ... or CODE CHANGED: versions changed: {'shapely': ('2.0.0', '2.2.0')}
```

A run record lists:
- the environment: GeoSpark, Python, pyproj/PROJ and Shapely/GEOS versions
- every data request (Nominatim, Overpass, Overture, Valhalla, weather, elevation) and every engine
  computation, each with a fingerprint of its input and output
- a fingerprint of the final result

`geospark replay` reruns the analysis and says whether it reproduced. If not, it says which source
returned different data, or that the code or a library version changed. In Python, use
`geospark.runs.record_run(...)` and `replay(...)`.

### Natural-language questions

```python
result = engine.ask("How far is the Eiffel Tower from Big Ben?")
print(result.spatial_context.summary)
print(result.sources)  # the model, then each tool it called
```

`ask` uses a local [Ollama](https://ollama.com) model first and falls back to free OpenRouter models
if `OPENROUTER_API_KEY` is set.

### Agents

```python
from geospark.agents import AgentCoordinator, GeoAgent, SiteSelector, SpatialReport

GeoAgent().run("Find all hospitals within 2km of the Eiffel Tower").findings["nearby"]

report = SpatialReport().analyze("Federation Square, Melbourne", radius_m=1000)
print(report.weather, report.accessibility, report.data_gaps)

best = SiteSelector().find(within="Zurich", near=["hospital", "school"], facility_type="pharmacy").best

AgentCoordinator().run("Find the best location for a cafe in Melbourne CBD near schools")
```

Agents use an LLM to read the goal. Without one, a rule-based parser still handles requests like
the one above: multi-word place names, radii such as "2km", and amenity types.

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

## Command line

```bash
geospark distance -37.8136 144.9631 -33.8688 151.2093   # Melbourne → Sydney: 713.86 km
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
geospark data air-quality "Delhi"        # needs OPENAQ_API_KEY
geospark data fires "Amazon Rainforest"  # needs FIRMS_MAP_KEY

geospark flow list
geospark flow build "Geocode Valencia then check its elevation" --run
geospark info                            # versions and optional extras
```

## Benchmark results

GeoSpark Bench v2 ran 9 models under three protocols: the bare question, step-by-step reasoning
(CoT), and the question with GeoSpark's MCP tools attached. The models were five open-weight ≤9B
(Qwen 2.5 7B, Llama 3.1 8B, Gemma 2 9B, Mistral 7B, Phi-3.5 3.8B), gpt-oss 20B, and three
frontier APIs (GPT-5.4, Claude Sonnet 4.5, Gemini 2.5 Pro). Intervals are Wilson 95%, and the
per-call cost ledger (~$41) is checked in. The full analysis is in a manuscript currently under peer
review.

**Numeric distance** (`distance_absolute`, n = 80 per model; correct = within 10% of the
`pyproj.Geod.inv()` geodesic):

| Model | Tier | Bare LLM | Step-by-step | + GeoSpark tools |
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

ᵃ The tools were available but not used properly: Llama mixed up km and m in the coordinates it got
back, and Mistral answered in plain text. ᵇ Gemma's correct answers are well-known long-distance
pairs, which is recall of training data, not computation. — means not evaluated with tools.

**What we learned**

- **Tools are a leveller.** The bare-LLM range spans 1–95%. With tools, every model that makes valid
  tool calls lands between 76% and 96%. Qwen gained 71 points; GPT-5.4 gained nothing, because it
  was already at 95%.
- **Aggregate scores hide bias.** Qwen's 56% on topology comes from saying "yes": it scores 93% on
  `intersects` (where the data skews true) and 3% on `disjoint`. GPT-5.4 scores 0% on `touches`.
  With GeoSpark, every predicate is 100%, because the engine computes it.
- **Step-by-step prompting is not a universal fix.** It helps some models and hurts others.
- **Knowledge questions don't need tools.** "Did the Amazon lose forest between 2015 and 2023?"
  is answered well at every scale without them.

Re-run it yourself with `python -m geospark.bench run`. The datasets regenerate identically from
`python -m geospark.bench.generate_datasets`; see the
[datasets README](https://github.com/Maz2580/geospark/blob/main/geospark/bench/datasets/README.md)
for provenance, and the
[benchmark report](https://github.com/Maz2580/geospark/blob/main/docs/BENCHMARK_REPORT.md) for
every table.

## Self-hosting

```bash
git clone https://github.com/Maz2580/geospark && cd geospark
cp .env.example .env     # set GEOSPARK_ENV=production and GEOSPARK_ADMIN_TOKEN
docker compose -f docker-compose.prod.yml up -d
```

The hosted API is designed to stay **open** without a key, with guard rails:

- An admin token protects operator routes (audit, usage, flow storage). The LLM gateway needs it or
  a revocable partner key.
- Public callers can only choose the local model or free models, so nobody can spend your paid
  API credit.
- Each visitor gets a private, size-capped, auto-expiring sandbox for the memory and context demos.
- Rate limits use the real client IP, and LLM work has a concurrency cap.
- Inputs are bounded, and the audit log stores hashed IPs.

All state lives under `GEOSPARK_DATA_DIR`. To lift Nominatim's public limits, point
`GEOSPARK_NOMINATIM_URL` at your own server. Details are in
[deploy/DEPLOY.md](https://github.com/Maz2580/geospark/blob/main/deploy/DEPLOY.md#security) and
[`.env.example`](https://github.com/Maz2580/geospark/blob/main/.env.example).

## Roadmap

- **v0.7: verifiable answers.**
  - Every result carries its source, licence, timestamp, CRS and units.
  - A "cannot answer" response instead of a guess.
  - Data-quality flags, such as geocoder confidence and DEM accuracy.
  - GeoJSON FeatureCollections that load straight into QGIS.
  - The MCP server updated to the 2026 spec, with structured GeoJSON output and a hosted HTTP
    endpoint.
- **v0.8: more data, more analysis.**
  - Overture Maps buildings, places and roads through DuckDB, with no key.
  - Real isochrones and travel-time matrices.
  - Bring your own GeoJSON, GeoPackage or GeoParquet.
  - Reproducible run manifests.
- **Ongoing:** external benchmarks (GPSBench, GeoBenchX), a QGIS bridge, and more MCP tools.

## Data attribution

GeoSpark computes geometry locally, but it fetches data from public services. Results built on them
keep the providers' licences, so please credit them when you publish:

- **OpenStreetMap** (geocoding, amenities, map tiles): © OpenStreetMap contributors, [ODbL](https://www.openstreetmap.org/copyright)
- **Copernicus DEM GLO-30** (elevation): © DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018, provided under COPERNICUS by the European Union and ESA
- **Open-Meteo** (weather): [CC BY 4.0](https://open-meteo.com/)
- **OpenAQ** (air quality) and **NASA FIRMS** (active fires): see each provider's terms. Air-quality
  results include each station's licence.

Elevation results include an `attribution` field you can copy directly. The full list is in
[NOTICE](https://github.com/Maz2580/geospark/blob/main/NOTICE).

## Development

```bash
git clone https://github.com/Maz2580/geospark && cd geospark
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,api,mcp]"
pytest                       # 1003 tests; offline, never touch ~/.geospark
ruff check geospark tests
```

Contributions are welcome. See
[CONTRIBUTING.md](https://github.com/Maz2580/geospark/blob/main/CONTRIBUTING.md), and report
security issues privately as described in
[SECURITY.md](https://github.com/Maz2580/geospark/blob/main/SECURITY.md). The architecture overview
is in [docs/ARCHITECTURE.md](https://github.com/Maz2580/geospark/blob/main/docs/ARCHITECTURE.md),
and release notes are in [CHANGELOG.md](https://github.com/Maz2580/geospark/blob/main/CHANGELOG.md).

## Citing

If GeoSpark or GeoSpark Bench helps your research, please cite it. GitHub's **"Cite this
repository"** button uses [CITATION.cff](https://github.com/Maz2580/geospark/blob/main/CITATION.cff).

## Author

Created by **Mazdak Ghasemi Tootkaboni** ([University of Melbourne](https://www.unimelb.edu.au/))
· ORCID [0000-0001-8084-5270](https://orcid.org/0000-0001-8084-5270) · GitHub [@Maz2580](https://github.com/Maz2580)

## License

[Apache 2.0](https://github.com/Maz2580/geospark/blob/main/LICENSE). Copyright 2024-2026 Mazdak Ghasemi Tootkaboni.
