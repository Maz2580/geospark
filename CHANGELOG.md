# Changelog

All notable changes to GeoSpark (`geospark-ai` on PyPI).

## [Unreleased]

## [0.10.0] - 2026-10-24: official datums, checked data, safer small models

GeoSpark now does datum and height conversions that need a national grid (AUSGeoid2020,
OSTN15/OSGM15, NZGeoid2016, GEOID18, NADCON), which frontier models could not do without the grid
files, and they agree with the national agencies' own calculators and test points. `geospark layer check` finds why two datasets
disagree (a GDA94/GDA2020 mix-up, a wrong zone, ellipsoidal against AHD heights), validated on 2,000
published survey marks. And Ask now catches what small local models get wrong without saying so:
numbers no tool returned, empty answers and contradictory comparisons.

### Added
- **Official datum and height conversions** (`geospark.geodesy`; `POST /api/v1/transform`,
  `POST /api/v1/height`; MCP and Ask tools `transform_coordinates` and `convert_height`). Coordinates
  convert with PROJ's most accurate operation that covers the point (GDA94 to GDA2020, MGA zones,
  British National Grid via OSTN15, NAD27 to NAD83 via NADCON, ITRF at an epoch, any EPSG pair), and
  heights between the ellipsoid and AHD, ODN, NZVD2016, NAVD88 or EGM2008 with the official geoid
  model. Grids download once into `$GEOSPARK_DATA_DIR/proj` (`/mnt/geospark/data/proj` in
  production); PROJ's ballpark fallbacks are refused; every result gives the operation, grid, stated
  accuracy and provenance (PROJ and EPSG dataset versions).
  - Why: on 32 datum and height questions (Australia, UK, NZ, US), GPT-6.1 and Claude Opus 5.5 applied
    datum parameters, plate motion and map projections to the millimetre, but anything needing a
    national grid failed: GPT-6.1 declined ("I cannot access the AUSGeoid2020 grid") and Opus 5.5
    estimated, 0.2-5.3 m off. PROJ falls back silently when a grid is missing (AHD becomes the
    ellipsoidal height, 4.7 m off in Melbourne; British National Grid moves about 124 m).
    With the tools attached, 63 of the two models' 64 answers were survey-grade and the last within 6 cm.
- GeoSpark sets `PROJ_USER_WRITABLE_DIRECTORY` to `$GEOSPARK_DATA_DIR/proj` when it is imported, so
  grid files never land in the user's system folders.
- **`geospark layer check`** (Python `geospark.io.check`, local MCP tool `check_dataset`): checks a
  file's coordinates before analysis (CRS declared and consistent with the numbers, swapped axes, points
  outside the CRS's zone, Australian data labelled WGS 84, height reference unstated) and, with
  `--against`, diagnoses why two layers disagree: GDA94 data labelled GDA2020 (matched to the official
  shift at that place), the wrong MGA zone, feet, swapped axes, a plate-motion epoch (with the number of
  years), or ellipsoidal against AHD heights. Unknown offsets are reported as unexplained; nearest-
  neighbour pairing warns when features are closer together than the offset. Exit code 2 on a problem.
- **Fairness checks for the October 2026 re-check** (`docs/benchmarks/2026-10/fairness.md`): the
  datum and height gap holds with the providers' own code execution at high effort (sandboxes have PROJ
  but no internet) and across three repeated runs; it does not hold for frontier models writing a
  script run with internet access (Opus 5.5 8/8, GPT-6.1 7/8 with a safe failure), while smaller local
  models wrote silently wrong scripts (gpt-oss 20B returned the ellipsoidal height as AHD; Qwen 3.5 4B
  1/8). The eight scripting tasks, their independently computed answers and the runner are in
  `docs/benchmarks/2026-10/codegen/`. README claims are scoped to what was tested.
- Real-data validation (`docs/benchmarks/2026-10/agency_checks.md`): on 2,000 of Victoria's published
  survey marks, `layer check` named GDA94 numbers labelled GDA2020, a wrong zone and ellipsoidal against
  AHD heights, and passed correctly labelled data (6 mm). GeoSpark's GDA94 to GDA2020 matches
  Victoria's surveyed marks within 7 mm (416 marks); AUSGeoid2020 matches spirit-levelled AHD to 6 mm
  median (99 marks).
- **README: "Re-check with current models (October 2026)"**, next to the original GeoSpark Bench v2
  results: a GeoSpark Bench sample on Claude Opus 5.5, GPT-6.1 and open models on a local workstation,
  and the new datum and height test. Questions, answer generators, harness (keys from the environment
  only) and a scored summary are in `docs/benchmarks/2026-10`.

#### Small-model safety (`docs/benchmarks/2026-10/small_models.md`)
Tested with four open models on a local workstation through Ask's own tool loop; each change below
fixes a failure seen there:
- Every quantity an answer states must trace back to a tool result (allowing unit changes, rounding, and
  sums or differences of results); otherwise the answer is `partial` and the number is named.
- An answer that returns no text after its tool calls is `cannot_answer`, not `ok`.
- "X is closer/farther" claims are checked against the measured distances, and an answer that names two
  different places as closer is flagged.
- `transform_coordinates` accepts a single `[x, y]` point and explains the expected shape, instead of a
  Python error that led a 4B model to invent EPSG codes.
- `calculate_distance` reads two places together: "Gold Coast" with Brisbane is Queensland, not Ghana
  (which it was, 16,549 km away, with no warning, on a server without a preferred country). An
  operator's `GEOSPARK_GEOCODE_PREFER_COUNTRY` is never overridden.
After the changes, 120 answers over three runs had one silent error (the Ghana geocode, then fixed).

### Fixed
- `layer check` named only one direction of a GDA94/GDA2020 mix-up. GDA2020 numbers labelled GDA94
  are now named the right way round too; the finding code is `gda94_gda2020_mixed`, with the
  mislabelled layer and what it holds.
- **GeoSpark's own layer analyses put GDA94 files 1.55 m off** (found while building the checker).
  PROJ's default step from GDA94, and from GDA2020, to WGS 84 is a null transformation, so a correctly
  labelled GDA94 file and a GDA2020 file of the same survey marks loaded 1.55 m apart in Melbourne, and
  count-within, nearest and intersect inherited the error. Australian data now goes to GDA2020 with the
  official transformation first; the same marks load to within 0.005 m.
- The benchmark notes said Opus 5.5 ran without extended thinking; Opus 5.5 always thinks (adaptive,
  default effort "medium"), and that is how it ran.
- **NZVD2016 heights were refused** ("could not be downloaded"): NZGeoid2016's area of use crosses
  the antimeridian (160.6 E to 171.2 W), and the coverage check that picks which grid to download
  assumed west < east.
- **Height conversions failed on the live API** ("outside its AUSGeoid2020 model") while working in
  a script: PROJ's on-demand grid download only works on the thread that enabled it, and the API
  answers on worker threads. GeoSpark now downloads the whole official grid file itself (only the one
  the most accurate covering operation needs), tells PROJ to rescan, and keeps PROJ's own networking
  off. A grid that can't be read or downloaded is now named in the error instead of being reported as
  "outside the model".

#### Checked against the national agencies
- GeoSpark's datum and height answers were compared with Geoscience Australia's calculators, Ordnance
  Survey's OSTN15/OSGM15 test points, LINZ's NZVD2016 examples and NGS's GEOID18 and NADCON 5
  services (`docs/benchmarks/2026-10/agency_checks.md`): agreement within 0.1 mm to 8 mm, except
  NAD27 to NAD83 (0.27 m from NADCON 5, disclosed).
- OSGM15 heights on Scilly, the Isle of Man, the Outer Hebrides, Orkney and Shetland were labelled
  "ODN"; Ordnance Survey's datum flags show they are local datums (St Marys, Douglas02, Stornoway15,
  Newlyn (Orkney), Lerwick). They are now labelled so (checked against all 40 OS test points), and ODN
  results note that heights more than 2 km offshore are in "Newlyn Offshore".
#### Found by auditing our own claims
- **Datum and height conversions, edge cases tested on the live site:**
  - AHD was given for Christmas Island, the Cocos Islands and at sea, because the AUSGeoid2020 grid has
    values there; AHD is the datum of mainland Australia and Tasmania, so those are now refused, and every
    AHD result says the model is valid onshore.
  - Asked for GDA2020 / MGA zone 55, Ask's model converted to a Lambert projection (an EPSG code it
    picked) and called the result MGA zone 55, with status "ok". Tools now take CRS names ("GDA2020 /
    MGA zone 55") as well as codes, and an answer whose conversion targets a different zone or datum
    than the question names is marked partial, with the system actually used in the warning.
  - Coordinates given as [latitude, longitude] are named as such; an epoch that has no effect (a static
    datum) is reported; a point outside the target CRS's area of use is flagged; a refusal no longer
    lists grids that don't cover the point (NAD27 in Hawaii listed nine).
- **Claims on the website and in the README:**
  - "Topology … correct on the ellipsoid" was wrong: topology is exact on the coordinates (straight
    edges in longitude/latitude); distances, areas and buffers are geodesic.
  - "The CRS is never guessed": a CSV's latitude/longitude columns are read as WGS 84 (with a caveat),
    which is now said plainly.
  - The 1-95% / 76-96% benchmark figures are dated (GeoSpark Bench v2) and followed by the October 2026
    re-check; "never a guess from memory" now says what is true (coordinates a model types are flagged).
  - The geodesy section says how the answers were checked: against Geoscience Australia's calculators
    API (within 0.1 mm) and NGS's GEOID18 service (1 mm); NAD27 to NAD83 uses the original NADCON, about
    0.27 m from NGS's NADCON 5 in San Francisco. Results matching PROJ when the tools use PROJ is stated
    as what it is: the model used the tool correctly.

## [0.9.0] - 2026-10-24: tested from the outside

Every agent, every Ask tool and every flow template was tested on the live site the way a visitor
would use them, with Melbourne questions first (most visitors are from the University of Melbourne),
and what failed is fixed. Ask's tools now take place names, so the model never supplies
coordinates; nearby places come from a self-hosted OpenStreetMap server with the right tags; and the
hosted MCP server is live and listed in the official MCP Registry.

### Added
- **Self-hosted Overpass support** (`GEOSPARK_OVERPASS_URL`). Queries whose area lies inside the
  server's coverage go to it first (10 s limit), with the public servers as fallback; everything
  else goes to the public servers. Coverage is the extract's real boundary, not its rectangle
  (`geospark/knowledge/coverage/australia.poly` from Geofabrik by default, or
  `GEOSPARK_OVERPASS_POLY`), because a local Overpass answers a point outside its data with
  0 elements, just like an empty place. The agents' 5-minute skip after a public failure no longer
  blocks the local server. Plan and measurements: `deploy/OVERPASS_SELFHOST_PLAN.md`.
- **Ask: `find_nearby_places` and `get_weather`**, and place names for `get_elevation` and
  `check_spatial_relationship` (details under Fixed).
- `server.json` for the official MCP Registry, listing the hosted endpoint as
  `io.github.Maz2580/geospark` (validated against the registry's 2025-12-11 schema).
- The README's `mcp-name` tag now matches that name exactly; the registry compares it
  case-sensitively, so the earlier lowercase tag would not have verified the PyPI package.
- **The hosted MCP server is live** at `https://geospark.terrascout.app/mcp`: add it to Claude (or
  any MCP client) as a custom connector, with no install. README and `deploy/DEPLOY.md` show how
  to connect and how to turn it on for your own deployment.
- **`deploy/docker-compose.override.example.yml`**: the production stack (API, Ollama, Valhalla,
  Overpass) as one tested file for anyone hosting GeoSpark, with the measured limits and settings.
  `DEPLOY.md` gains "The full stack" (how to bring it up one service at a time) and a current
  architecture diagram; `.env.example` adds `GEOSPARK_VALHALLA_URL`, `GEOSPARK_NOMINATIM_URL` and the
  Ollama settings, which were missing.
- `GEOSPARK_GEOCODE_PREFER_COUNTRY`: an operator's users' country wins a close geocoding call, with a
  caveat naming the other match. `GEOSPARK_OLLAMA_WARMUP` (on by default when `OLLAMA_BASE_URL` is set).

### Changed
- The MCP server's `calculate_distance` takes place names (`place_a`, `place_b`) and geocodes them
  on the server, as `/ask` already does, so a model never has to type coordinates for a named
  place. The places and their Nominatim provenance come back with the distance. Because it may
  call the geocoder, the tool is now annotated `openWorldHint: true`.

### Fixed: found by testing the live site
- **The first questions after a deploy timed out** (120 s) while the local model read /ask's tool list
  on the CPU; the server now has the model read it once at startup, in the background
  (`GEOSPARK_OLLAMA_WARMUP=false` turns this off). The OpenRouter fallback then failed with a 404:
  OpenRouter had retired every free model GeoSpark named. The fallback now uses the auto-router
  (`openrouter/free`), the named models are current, and when both fail the visitor reads why in words.
- **Testing the live site as an outside user** found and fixed:
  - **Flows**: every template failed at its first step (the runner never passed `address` to the
    geocoder or the geocoded point to later steps) and the run still reported "completed". Parameters
    and `{step.key}` references now reach the tools, a step whose input failed is skipped with the
    reason, and a run with a failed step is "failed". The NDVI template now stops honestly: NDVI values
    are not computed yet. The Flows page shows each step's result, and its Delete button no longer runs
    the flow first. An unknown template is a 404, not a 500.
  - **Ask** gave Mount Kosciuszko's height as 1,249 m (the model typed coordinates from memory) and
    said the Eiffel Tower is not in Paris (it compared two points). `get_elevation` now takes a place
    name, and `check_spatial_relationship` takes place names and uses the outer place's boundary; a
    point given as the container is refused. Ask gains `find_nearby_places` ("how many hospitals within
    1 km of ...", which it had answered with a buffer's area) and `get_weather` (it said it couldn't).
    A tool call that failed and was then retried correctly no longer marks the answer partial.
  - **Supermarkets, parks, hotels, playgrounds and bus stops always counted as zero**: only `amenity=*`
    was queried in OpenStreetMap, and they are `shop=`, `leisure=`, `tourism=` and `highway=`. The
    Overture fallback had the same problem with its own names (supermarkets are `grocery_store`, police
    `police_station`, universities `college_university`).
  - "Mount Wellington, Hobart" found nothing (the peak's address doesn't name Hobart), and GeoAgent
    then used a Mount Wellington in New York and searched for hospitals nobody asked about. The geocoder
    now searches for the name inside the named area (with a caveat), GeoAgent keeps comma-joined places
    together, answers elevation questions, and shows geocoding caveats such as an ambiguous name.
  - **Melbourne questions** (most visitors are from the University of Melbourne): "University of
    Melbourne" geocoded to a future campus under construction at Fishermans Bend, 4.6 km from Parkville,
    so every distance from the university was wrong; "Parkville" was Maryland and "Brunswick"
    Braunschweig. The geocoder now ranks construction sites and bus stops below real places, and an
    operator can set `GEOSPARK_GEOCODE_PREFER_COUNTRY` (e.g. `au`) so a close call resolves to their
    users' country, always with a caveat naming the other match. Boundaries use the same ranking.
- **Second live test of all four agents (22 questions)** found and fixed:
  - "Is the Louvre inside Paris?" answered **No**: GeoAgent compared two geocoded points, and a point
    can't contain anything. It now fetches the container's boundary from OpenStreetMap (Nominatim,
    simplified) and refuses to answer when there is none. The relationship comes from the wording
    ("inside"/"in" means within, "contains" means contains), so "Is A inside B" is no longer checked
    backwards.
  - "Where should **I** open a pharmacy in Zurich near hospitals and schools?" went to GeoAgent, whose
    model listed "hospitals" and "schools" as places (geocoded to New York and the West Bank) and
    searched the type "hospital,school"; the answer claimed no hospitals or schools near Zurich. Such
    questions now go to the Site Selector, and GeoAgent keeps place names and place types apart.
  - Missing API keys (air quality, fires) were answered "try again in a few minutes"; they now say the
    server needs the free key.
  - Model replies in the agents are length-capped (`num_predict`); a JSON-mode reply could pad with
    blank space until the 60 s timeout (seen live: 35 s, 43 s and 60 s calls among 2-7 s ones).
  - The Site Selector kept candidates anywhere within the radius: "cafe in Melbourne CBD" picked a
    school 5 km away in Brunswick. Candidates now stay inside the area's OpenStreetMap boundary
    (with a caveat), and a candidate's own campus (anything within 50 m, e.g. one school mapped as
    several buildings) no longer counts as "a nearby school".
  - The Spatial Report says air quality needs an OpenAQ API key instead of "could not be retrieved".
  - "Is Federation Square in Melbourne?" failed with "Unknown relationship: null": the model returned the
    string "null", and then "contains" (the reverse). The question's wording ("in", "inside", "within",
    "contains") now always decides the relationship, like a stated distance.
  - The Agents page's default examples are Australian, where the self-hosted Overpass answers in
    under a second; places elsewhere still use the public servers.
- GeoAgent uses a distance written in the question ("within 2km", "500 m") even when the model's
  reading of the question leaves it out; live, one run searched the model's default 3 km instead of 2 km.

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
