# Changelog

All notable changes to GeoSpark (`geospark-ai` on PyPI).

## [Unreleased]

### Fixed: the agents (Spatial Report, Site Selector, Coordinator, GeoAgent)
Tested live with the Agents page's own examples, most answers were empty or wrong even though every
call returned HTTP 200:
- **Nearby places failed under load.** All agents depended on the public Overpass servers, which
  rate-limit by IP (connection refused or 504 after a few queries, 20-30 s each when they answer).
  A shared lookup (`geospark/agents/amenities.py`) now asks OpenStreetMap once per request with a
  20 s limit, skips it for 5 minutes after a failure, and falls back to Overture Maps places (read
  by GeoSpark itself, no rate limit) with strict category mapping and a confidence filter. The
  answer names its source, and a caveat explains the fallback.
- **No fallback for health care.** Overture's "hospitals" near the Eiffel Tower included private
  practices, a bar and a hospital in Cameroon, so hospitals, clinics, doctors and dentists are
  never taken from Overture: if OpenStreetMap is down they are reported as not retrieved.
- **The Site Selector invented a site.** With no data it ranked "Zurich center" (score 0) and the
  model explained it was near a hospital and a school. It now says what could not be retrieved and
  never ranks on part of the criteria; the model only summarises real candidates, from the facts.
- **GeoAgent turned failed lookups into "none found"**, and looked up hospitals for any "analyze"
  request. Failures are now stated in fixed wording (and with nothing found, the model isn't
  asked), and an area analysis covers everyday services.
- **The Coordinator misread requests.** "...for a cafe in Melbourne CBD near schools" searched for a
  place called "Melbourne CBD near schools"; facility, area, near and avoid are now parsed from
  the sentence. "Analyze <place>" now goes to the Spatial Report, with the place name only.
- **Spatial Report counts** were taken from the 50 closest places (mostly restaurants); all
  services are counted now, and the nearest ten of each type are listed.
- **The Agents page** now shows the Site Selector's summary (it never did) and, for every agent,
  what could not be retrieved and any caveats.

### Added
- `server.json` for the official MCP Registry, listing the hosted endpoint as
  `io.github.Maz2580/geospark` (validated against the registry's 2025-12-11 schema).
- The README's `mcp-name` tag now matches that name exactly; the registry compares it
  case-sensitively, so the earlier lowercase tag would not have verified the PyPI package.
- **The hosted MCP server is live** at `https://geospark.terrascout.app/mcp`: add it to Claude (or
  any MCP client) as a custom connector, with no install. README and `deploy/DEPLOY.md` show how
  to connect and how to turn it on for your own deployment.

### Changed
- The MCP server's `calculate_distance` takes place names (`place_a`, `place_b`) and geocodes them
  on the server, as `/ask` already does, so a model never has to type coordinates for a named
  place. The places and their Nominatim provenance come back with the distance. Because it may
  call the geocoder, the tool is now annotated `openWorldHint: true`.

## [0.8.0] - 2026-10-23: more data, more analysis

GeoSpark now reaches beyond geocoding and geometry. It reads Overture Maps with no key, computes
reachable areas and travel times on its own routing engine, analyses your own files without ever
guessing their CRS, and records any analysis so it can be replayed and explained later. The website
is redesigned around the proof behind every answer, and Ask no longer lets a model supply
coordinates from memory.


### Added
- **Website redesign ("Proof Engine")**: a dark, instrument-like look across every page.
  - A new mark (a spark inside an open globe ring), animated as liquid metal with WebGL. Adapted
    from Liquid Logo by Alan Ang (MIT); falls back to the plain SVG without WebGL, honours reduced
    motion, and pauses when off screen.
  - Home: a globe showing real geodesic distances with their sources, the proof chain, and a live
    walking isochrone from Federation Square.
  - Playground: new **Reachable area** (isochrones, walk/bike/drive, up to 4 contours) and **Open
    map data** (Overture places, buildings, roads, boundaries) tabs, deep links (`#reach`,
    `#overture`, `?ask=`), and one result map.
  - A **Proof** panel on every result: status, sources with licence and method, caveats, units,
    **Download GeoJSON** and **Copy citation**. Failures show a plain-language refusal.
  - OSM tiles are darkened in CSS (the tile source and attribution are unchanged).
  - One spacing scale and justified, hyphenated body text on every page; every page opens with the
    same label, title and introduction.
  - A themed **API reference** at `/docs`: base URL, authentication and a copyable request, then the
    interactive reference with endpoints grouped by topic (Spatial, Ask, Routing, Open map data, …)
    and real Melbourne examples instead of placeholder values. `/redoc` and `/openapi.json` are unchanged.
- **`/api/v1/ask` returns the checkable part of the answer**: `status`, `provenance`, `units`,
  `warnings`, `quality` and the places the tools found (`features`). A failed tool call makes the
  status `partial` and is listed as a caveat.
- **Overture Maps with no API key** (`geospark-ai[overture]`):
  - Themes: places (with categories), buildings (height, floors, geodesic footprint area),
    transportation segments (geodesic length), and the administrative divisions containing a point.
  - Queried in place on S3 with DuckDB, reading only the files whose STAC bbox covers the area.
  - Results are nearest first in geodesic metres and capped at 2 km. Answers are cached for 24 h.
  - Provenance names the Overture release and the actual licences of the returned records.
  - Available from Python, the CLI (`geospark overture`), REST (`POST /api/v1/overture/{theme}`,
    GeoJSON with `?format=geojson`) and the MCP tool `overture_features`.
  - DuckDB is capped per query (4 threads, 512 MB) so it can't starve a shared host. The Docker image
    pre-installs DuckDB's extensions.
  - One DuckDB query at a time (`GEOSPARK_OVERTURE_CONCURRENCY`), so concurrent requests can't
    exceed a small container's memory.
- **Reproducible runs** (`geospark.runs`, CLI `geospark record …` / `geospark replay FILE`):
  - A run record has the environment versions plus every data request (Nominatim, Overpass,
    Overture, Valhalla, data channels, Copernicus/Open Elevation) and every engine computation,
    fingerprinted with SHA-256 over canonical JSON (timings and retrieval times ignored), plus
    the result's fingerprint.
  - Replay reruns the analysis and answers **reproduced**, **data changed** (naming the source
    and request) or **code changed** (naming the library versions).
  - Recording follows work into GeoSpark's thread pools and async helpers.
- **Bring your own data** (`geospark-ai[io]`):
  - Formats: GeoJSON, GeoPackage, Shapefile (also zipped), GeoParquet, CSV with lon/lat,
    FlatGeobuf, KML, GML, File Geodatabase.
  - The CRS is never guessed: declared CRSs are reprojected and reported, files without one are
    refused until `crs=` is given, GeoParquet follows its spec default, and CSV lon/lat is accepted
    with a warning.
  - Invalid geometries are refused, or repaired with `repair=True`.
  - Analysis, all geodesic: `count_within` (exact point-in-polygon with density), `nearest` (exact
    at any latitude; checked against brute force at 70°N) and `intersect` (overlap pieces with
    both sides' attributes and area).
  - Provenance includes each file's SHA-256.
  - Available from Python, the CLI (`geospark layer info|count-within|nearest|intersect`) and
    local-only MCP tools (`layer_*`, never on the hosted endpoint).
- **Real isochrones and travel-time matrices** (Valhalla over OpenStreetMap) for walking, cycling and
  driving:
  - Reachable-area polygons per contour (up to 4, 1–60 min), validated and repaired, with geodesic
    area.
  - Origin × destination matrices (up to 5×5) with travel time and network distance, flagging
    unreachable pairs.
  - Available from Python, the CLI (`geospark isochrone`), REST (`/api/v1/isochrone`,
    `/api/v1/travel-time`), the engine's `isochrone` operation (no longer "not implemented") and the
    MCP tools `isochrone` and `travel_time_matrix`.
  - Uses `GEOSPARK_VALHALLA_URL`. Without it, GeoSpark falls back to the public FOSSGIS instance,
    gently (≥ 1 s apart, cached), but a production deployment refuses that fallback and says
    how to configure a server.

### Fixed: Ask could answer from coordinates the model made up
- Reported by a tester: "How far is Adelaide Oval from Glenelg beach?" gave 12.25, 14.44 and 15.76 km
  on three runs (correct: 10.63 km), each with status `ok`. The 7B model skipped geocoding and passed
  coordinates from memory to `calculate_distance`, which computed exactly, but between wrong points.
- `calculate_distance` now takes place names (`place_a`, `place_b`) and geocodes them on the server.
  The places, their provenance (Nominatim, ODbL) and any ambiguity warning come back with the
  distance. With the same model the question now gives 10.63 km on every run.
- Backstop: if a tool is given coordinates that no geocode call in the same answer produced and that
  are not in the question, the answer's status is `partial`, with a caveat saying why.
- The homepage now quotes the README's benchmark figures (1–95% for models alone, 76–96% with
  GeoSpark's tools for models that made valid tool calls) instead of "0%" and "100%".
- The status page, `/api/v1/tools` and `geospark tools` say what each tool does today: change
  detection is listed as planned (not available), and NDVI and spectral indices as partial (they
  find satellite scenes but don't compute index values yet).

### Fixed: website
- After a deploy, returning visitors could get the new pages with the old cached stylesheet and
  scripts (Cloudflare caches `/assets` for 4 hours), so pages looked broken. Asset links now carry a
  content hash (`/assets/styles.css?v=…`) and the pages are sent with `Cache-Control: no-cache`.

### Tests
- 1,068 tests that run offline; coverage 81%. New tests cover provenance on `/ask`, invented
  coordinates, place-name distances, the API reference, honest tool statuses and versioned assets.

## [0.7.0] - 2026-10-22: verifiable answers

Every answer now shows its work: where the data came from and under what licence, how a value was
computed, its units, how good it is, and whether it's an answer at all. GeoSpark refuses rather
than guesses, exports QGIS-ready GeoJSON, and its MCP server is rebuilt on SDK 2.x with 12 tools.

### Added
- **Provenance on every answer.** Results carry `provenance` records (source, licence,
  attribution, retrieval time, method, dataset version) for OpenStreetMap, Copernicus GLO-30, Open
  Elevation, Open-Meteo, OpenAQ, NASA FIRMS, OSRM, STAC, and for computed answers the engine's
  method and the exact pyproj/PROJ/Shapely/GEOS versions. This covers REST responses, MCP tool
  replies, data channels and location reports.
- **Units**: `spatial_context.units`, e.g. `{"distance_m": "metre"}`.
- **Quality flags and warnings**: geocoder match importance and an ambiguity warning when
  near-equal candidates are far apart (e.g. "Springfield" in Illinois, Massachusetts, Missouri); DEM vertical accuracy (GLO-30 4 m, SRTM 16 m LE90) and the
  vertical datum; a warning when topology is computed on very large geometries.
- **`status`** on every result: `ok`, `partial` or `cannot_answer`.

- **QGIS-ready GeoJSON**: `SpatialResult.to_geojson()` and `LocationReport.to_geojson()` give
  RFC 7946 FeatureCollections (WGS84, bbox, flat attribute columns, per-feature `attribution`,
  provenance/units/warnings in a `geospark` member). REST supports `?format=geojson` or
  `Accept: application/geo+json` on geocode, query, elevation and agent/report; the CLI has
  `--geojson FILE`. Verified by reading the files with GDAL, the reader QGIS uses.
- Satellite scenes report a cloud-cover range and warn when every scene is mostly cloud.

- **MCP server rebuilt on MCP SDK 2.x** (protocol 2026-07-28, still negotiating 2025 handshakes):
  - **12 tools** instead of 6. New: `route`, `get_weather`, `get_air_quality`,
    `get_active_fires`, `location_report`, `select_site`.
  - Typed inputs with documented **output schemas** and **structured content** (GeoJSON for
    places and shapes).
  - Read-only / open-world tool annotations, and server instructions for the model.
  - `isError` replies with the reason when an answer can't be given reliably.
  - The always-ignored required `explanation` argument is gone; clients that still send it keep
    working.
  - Heavy tools share the API's concurrency cap.
- **Optional hosted MCP endpoint**: Streamable HTTP at `/mcp` (stateless, JSON responses, public
  and read-only, rate-limited), enabled with `GEOSPARK_MCP_HTTP=true`. Off by default.

### Changed
- `mcp` extra is now `mcp>=2.3,<3`. `pip install geospark-ai[mcp]` alone runs the MCP server
  (no web framework needed), and CI checks that.
- **GeoSpark refuses rather than guesses.** Invalid geometry (for example a self-intersecting
  polygon, whose area used to come back as about 0), out-of-range coordinates, and likely
  [lat, lon] swaps are rejected with an explanation, everywhere: engine, REST and MCP.

## [0.6.0] - 2026-10-22: the trustworthy release

The focus of this release is that what GeoSpark says it does, it does: it installs cleanly,
it's safe to host publicly, and its answers are geometrically correct.

### Fixed: install and packaging
- `pip install geospark-ai[mcp]` then `geospark-mcp` crashed on start, because mcp 2.x removed the
  decorator API. `mcp` is now pinned `<2`, and CI runs a real stdio handshake.
- `pip install geospark-ai[all]` installed the unrelated `geospark` package plus PySpark instead
  of this project's extras.
- Install hints now say `geospark-ai[...]`, and the Nominatim User-Agent carries the real version and
  repository URL.

### Security (hosted API stays open, with guard rails)
- In production, the admin token (`GEOSPARK_ADMIN_TOKEN`) is required to start and protects the
  admin, audit, usage and flow-storage routes.
- LLM gateway chat/generate/embeddings need the admin token or a revocable partner key
  (`GEOSPARK_GATEWAY_KEYS`). Health no longer reveals the internal Ollama URL.
- Model allowlist: public callers could make `/ask` fall back to *any* OpenRouter model on the
  server's key. Now only the local model and free models are allowed.
- SSRF: `/flows/build` no longer fetches a caller-supplied URL.
- Path traversal in context URIs is fixed.
- Memory and Context demos get private, size-capped, auto-expiring sandboxes per visitor.
- Rate limits key on the real client IP (spoof-resistant), with an expensive tier and an LLM
  concurrency cap. Request bodies are capped and inputs bounded. The audit log stores hashed IPs.

### Fixed: correctness
- Weather, air-quality and fire data were silently missing from agent reports (an async bug).
- Polygon and line buffers were circles around the centroid; they now buffer the real shape.
- Agent search boxes shrank east-west away from the equator (3.2 of 4 km in Melbourne). They're
  geodesic now.
- Mixed-CRS distance and topology queries transform both geometries. Added a geodesic `length`.
- Unbuilt operations (slope, viewshed, isochrone, band math, change detection) return a clear
  "not implemented yet" error instead of an empty success.
- Elevation results report the dataset that answered (Copernicus GLO-30) and its attribution.
- Malformed GeoJSON returns 400 and upstream outages return errors, not 500s. MCP tool calls
  report `status: error` when they fail, and a geocoding outage no longer looks like "no results".
- Air quality parses the OpenAQ **v3** responses it requests (it used v2 field names, so stations had
  no readings), and passes through each station's licence.
- `geospark ask` no longer crashes after answering. The CLI accepts negative (southern/western)
  coordinates. The bench's OpenRouter adapter works.
- The GeoAgent fallback parser (used when the LLM is unavailable) keeps "Eiffel Tower" as one place
  and reads radii ("2km") and amenity types.
- The API no longer freezes while slow requests run: blocking handlers use the thread pool.

### Added
- Geocoding follows the Nominatim usage policy (shared ≤ 1 request/s and a 24 h cache), and
  `GEOSPARK_NOMINATIM_URL` points it at a self-hosted server.
- `GEOSPARK_DATA_DIR`: one root for all persistent state. The Docker image writes to the mounted
  `/app/data`, so audit logs, usage counters and sandboxes survive redeploys.
- Data attribution in NOTICE and the README; a datasets README for GeoSpark Bench.
- `SECURITY.md` and a security section in `deploy/DEPLOY.md`.

### Tests
- 955 tests that run offline and never touch `~/.geospark`; coverage 63% → 79% (CI floor 70%).
  The core modules are type-checked in CI.
- The benchmark generator ran again (it had a typo). All 535 questions regenerate identically, and a
  test keeps it that way.

### Unreleased commits now included (April-October 2026)
- The Flows UI page; Copernicus GLO-30 elevation with Open Elevation fallback; Overpass retries and
  mirror racing; parallel report lookups; location-report fixes for amenity lookup, weather and invented
  claims.

## [0.5.1] - 2026-04-22
- Previous release. See the git history for details.
