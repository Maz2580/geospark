# Changelog

All notable changes to GeoSpark (`geospark-ai` on PyPI).

## [Unreleased] - 0.8.0: more data, more analysis

### Added
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
