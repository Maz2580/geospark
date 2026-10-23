# Self-hosting Overpass next to GeoSpark (Australia)

**Goal:** an Overpass API container beside `geospark-api` and `geospark-valhalla`, so the agents' nearby-place
lookups (hospitals, schools, pharmacies, ...) inside Australia stop depending on the public Overpass servers.

**Why:** the public servers rate-limit by IP. On 2026-10-23 the first query from the server took ~70 s and
the next was refused. PR #27 added an Overture Maps fallback, but Overture's health-care records are
unreliable, so hospitals, clinics, doctors and dentists come back as "not retrieved" whenever Overpass is
down. During this test (same day), `overpass-api.de` refused every connection from the maintainer's Mac,
and `maps.mail.ru` took 23 s for one 2 km query.

Status: **plan only.** Nothing has been changed on the server. Every step below needs the maintainer's
approval, one at a time.

## Rules (from the maintainer, and DEPLOY.md "Running on a shared server")
- **Other apps are not affected.** UrbanMind, TerraScout, GeoLibre, Umami and their tunnels keep running
  untouched. Only the new `overpass` service is started: `up -d --no-deps overpass`.
- **Everything under `/mnt`, including container data.** The database is a bind mount at
  `/mnt/geospark/overpass`, with no anonymous or named volumes and no paths elsewhere on the host. Docker
  `data-root` is `/mnt/docker-data` and containerd root is `/mnt/containerd-data` (checked with `docker info`
  before starting). Compose runs with `BUILDX_CONFIG=/mnt/geospark/.buildx`.
- **Same conventions as the other GeoSpark containers.** Defined in `/mnt/geospark/docker-compose.override.yml`,
  `geospark-net` only, no published port, `restart: unless-stopped`, memory and CPU limits from the
  measurement below, json-file logs `max-size: 10m`, `max-file: 3`.
- Backups before every edit. Never `docker system/volume/image prune`, never restart the daemon.

## Design
| | |
|---|---|
| Image | `wiktorn/overpass-api:v0.7.62.11`, pinned (newest tag, published 2026-08-01; amd64 + arm64). The maintained Docker packaging of Overpass. |
| Data folder | `/mnt/geospark/overpass` → `/db`. **All** of the service's persistent state lives there: the database (`db/`), the diff queue (`diffs/`), `changes.log`, `replicate_id`, `cookie.jar`, `init_done`. Gitignored. |
| Other writes | nginx logs go to stdout (json-file, capped). Small runtime files (fcgiwrap socket, pid files, `supervisord.log`, nginx temp dirs, the rendered `/etc/nginx/nginx.conf`) are in the container layer, which lives in `/mnt/docker-data`. Checked with `docker diff`; see "Found while testing". |
| Network | `geospark-net` only, no published port. GeoSpark reaches it at `http://geospark-overpass/api/interpreter` (port 80 inside the network). |
| Region | Australia, from Geofabrik's extract (`australia-latest.osm.pbf`, 970 MB on 2026-10-22) |
| Updates | Geofabrik's daily diffs (`australia-updates/`), applied by the container's own loop, checked hourly (`OVERPASS_UPDATE_SLEEP=3600`). No rebuilds. |
| Areas | Off (`OVERPASS_USE_AREAS=false`). GeoSpark's point lookups use bounding boxes. Areas cost extra build time and a CPU loop that keeps running. The one area query (`load_city`, by name) stays on the public servers. |
| Metadata | Off (`OVERPASS_META=no`): GeoSpark never asks for authors, versions or history. Smaller and faster. |
| Restart | `unless-stopped`. The database survives restarts and GeoSpark redeploys, and `init_done` stops it from rebuilding. |

### User id: why not `user: "1000:1000"`
The image can't start as a non-root user. Its entrypoint runs `supervisord`, which switches each program to
its own user (`user=overpass`, `user=nginx`). That needs root, and so do nginx listening on port 80 and the
entrypoint writing `/etc/nginx/nginx.conf`. Overriding all of that would mean maintaining our own image.

**The result matches the rule anyway:** the image's `overpass` user is **uid/gid 1000** (`id overpass` →
`uid=1000(overpass) gid=1000(overpass)`). The dispatcher, the updater and the database all run as that
user. The one-off build runs as root, but the entrypoint then `chown`s everything in `/db` to `overpass`,
so on the server every file in `/mnt/geospark/overpass` ends up owned by `ubuntu:ubuntu`. After the build,
only supervisord and the nginx master process run as root, inside the container, and they write nothing to
the bind mount.

To check after step 4: `find /mnt/geospark/overpass ! -uid 1000 | head` should print nothing. (This
couldn't be checked on the Mac, where Docker Desktop shows every bind-mounted file as the Mac user. If a
build fails partway, root-owned files can be left behind: `sudo chown -R 1000:1000 /mnt/geospark/overpass`
or delete the folder and start again.)

## Measured on 2026-10-23 (Mac test, Docker Desktop, 10 CPUs / 7.7 GB VM)
Image `wiktorn/overpass-api:v0.7.62.11`, Geofabrik Australia extract of 2026-10-22 (970 MB `.pbf`), metadata
and areas off, settings as in the service block below. The data lived on the Mac's internal disk (bind
mount, like the server).

| | |
|---|---|
| Download | 3.0 min (970 MB) |
| Convert `.pbf` → `.osm.bz2` (`OVERPASS_PLANET_PREPROCESS`) | 46 min, **single-threaded** (bzip2 at 100 % of one core). The image's import only reads bzip2 XML. |
| Import (`update_database`) | 17 min |
| Catch up with diffs since the extract | 3.5 min (mostly scanning the file for its newest timestamp; no newer diff existed yet) |
| **Total, start to "ready to receive requests"** | **68.8 min**, one-off |
| Restart with an existing database | ready in ~1 s (no rebuild; `init_done` present) |
| Peak memory (build) | **5.3 GB** (`docker stats`, during the import); the cgroup peak including page cache was 7.1 GB, capped by the 7.7 GB VM. Cache is reclaimed under a limit. |
| Peak disk (build) | 10.3 GB (`.pbf` + `.bz2` + the growing database) |
| **Disk when done** | **8.5 GB** in `/db` (the `.pbf` and `.bz2` are deleted) |
| **Memory while serving** | **37–80 MB** (cgroup peak 160 MB including page cache, after 60 queries) |
| CPU while idle | ~0.1 % (the update loop sleeps an hour between checks) |

**Queries** (the GeoSpark amenity query: `[out:json][timeout:25];nwr["amenity"~"^(hospital|school|pharmacy|restaurant|bank|police)$"](<bbox>);out center;`, bbox from `overpass_bbox(lat, lon, radius)`):

| Point | Radius | Time | Elements |
|---|---|---|---|
| Federation Square, Melbourne | 2 km | **0.26–0.42 s** | **1,018** (13 hospitals, 21 schools, 46 pharmacies, 872 restaurants, 54 banks, 12 police) |
| Same query on `maps.mail.ru` (public) | 2 km | 23 s | 1,018, identical counts per type |
| Same query on `overpass-api.de` (public) | 2 km | connection refused from the Mac | – |
| Melbourne CBD | 10 km | 1.17 s | 3,246 |
| Sydney Town Hall | 2 km | 0.29 s | 875 |
| Hobart | 2 km | 0.21 s | 170 |
| Darwin | 2 km | 0.22 s | 42 |
| Simpson Desert (empty, inside Australia) | 2 km | 0.16 s | 0 |
| **Zurich (outside the extract)** | 2 km | 0.16 s | **0, HTTP 200, no remark** |
| 12 Federation Square queries at once | 2 km | all 12 OK, 0.44–1.35 s (served 4 at a time) | 1,018 each |
| 40 queries back to back | 2 km | 40/40 OK, 0.35 s average, no rate limit | |

Data freshness: `osm3s.timestamp_osm_base` was `2026-10-22T20:15:47Z` locally (daily diffs) against `2026-10-23T04:52:50Z` on mail.ru (minutely), about 9 hours apart. That makes no difference for amenities, as the identical counts show.

**Found while testing:**
1. **Duplicate-query guard.** The image defaults to `OVERPASS_ALLOW_DUPLICATE_QUERIES=no`. The dispatcher then
   refused 7 of 8 identical parallel queries, then all 8 of a batch of *different* queries sent right
   after. In practice it allows about one query at a time per client, and every GeoSpark request comes
   from the one `geospark-api` container. **Set it to `yes`.** After that, all 12 parallel queries
   succeeded.
2. **Errors come back as HTTP 200 with an HTML page**, not JSON. That includes the duplicate-query refusal
   (`Error: runtime error: ... Dispatcher_Client::request_read_and_idx::duplicate_query`). GeoSpark's
   `_post` already treats a non-JSON body as a failure (`ValueError` → `RuntimeError`), so this falls
   through correctly. Keep it that way, and never treat "no elements" as success without valid JSON.
3. **Outside coverage looks exactly like "nothing there"**: Zurich and the Simpson Desert both answer
   200 with 0 elements. See "How GeoSpark would use it".
4. After catching up, the update loop logs `ERROR: Error while downloading diffs.` followed by
   `Update finished with status code: 3`. That only means there is no newer diff yet (Geofabrik publishes
   once a day), not a failure.
5. Writes outside `/db` (`docker diff`) are all small runtime state in the container layer:
   `/nginx/fcgiwrap.socket`, `/run/nginx.pid`, `/supervisord.pid`, `/supervisord.log`, nginx temp dirs
   under `/var/cache/nginx`, and the rendered `/etc/nginx/nginx.conf`. On the server the container layer is
   in `/mnt/docker-data`. `supervisord.log` rotates at supervisord's default (50 MB × 10).

**Settings for the server:** memory limit **8 GB** (build peak 5.3 GB plus headroom; serving needs <100 MB),
`cpus: 2` (the build is single-threaded; serving runs up to 4 FastCGI workers, each well under a second),
`OVERPASS_ALLOW_DUPLICATE_QUERIES=yes`. `/mnt` needs ~11 GB free during the build and 8.5 GB after. The
server has 64 cores, 251 GB RAM and ~800 GB free on `/mnt`, so the other apps aren't affected.

## Exact server change (for approval, one step at a time)

0. **Preflight** (read-only):
   ```bash
   docker info -f '{{.DockerRootDir}}'          # must print /mnt/docker-data
   grep -n root /etc/containerd/config.toml     # root = "/mnt/containerd-data"
   df -h /mnt                                    # needs ~11 GB free
   free -g; uptime                               # note load and memory before
   ```
1. **Backups and markers:**
   ```bash
   cd /mnt/geospark
   cp docker-compose.override.yml docker-compose.override.yml.bak-$(date +%F)-overpass
   cp .env .env.bak-$(date +%F)-overpass
   docker ps --format '{{.Names}} {{.ID}}' | sort > /mnt/geospark/.containers-before
   sudo touch /mnt/geospark/.change-start
   ```
2. **Data folder**, as ubuntu: `mkdir -p /mnt/geospark/overpass` (owned `ubuntu:ubuntu`, uid 1000, the
   same uid as the container's `overpass` user).
3. **Add the service** to `/mnt/geospark/docker-compose.override.yml`, under `services:`:
   ```yaml
     overpass:
       image: wiktorn/overpass-api:v0.7.62.11
       container_name: geospark-overpass
       # No `user:` - supervisord must start as root; the database runs as the image's
       # `overpass` user, which is uid/gid 1000 (ubuntu), and owns everything in /db.
       volumes:
         - /mnt/geospark/overpass:/db
       environment:
         - OVERPASS_MODE=init
         - OVERPASS_META=no
         - OVERPASS_PLANET_URL=https://download.geofabrik.de/australia-oceania/australia-latest.osm.pbf
         - OVERPASS_DIFF_URL=https://download.geofabrik.de/australia-oceania/australia-updates/
         - OVERPASS_PLANET_PREPROCESS=mv /db/planet.osm.bz2 /db/planet.osm.pbf && osmium cat -o /db/planet.osm.bz2 /db/planet.osm.pbf && rm /db/planet.osm.pbf
         - OVERPASS_USE_AREAS=false
         - OVERPASS_STOP_AFTER_INIT=false
         - OVERPASS_UPDATE_SLEEP=3600
         - OVERPASS_ALLOW_DUPLICATE_QUERIES=yes   # the default "no" refused parallel queries in testing
         - OVERPASS_MAX_TIMEOUT=60s
         - OVERPASS_FASTCGI_PROCESSES=4
       restart: unless-stopped
       networks:
         - geospark-net
       deploy:
         resources:
           limits:
             memory: 8G
             cpus: "2"
       logging:
         driver: json-file
         options:
           max-size: "10m"
           max-file: "3"
   ```
   No `ports:`, so only containers on `geospark-net` can reach it. Then check the file parses:
   `docker compose -f docker-compose.prod.yml -f docker-compose.override.yml config --services`.
4. **Start only this service**, then watch the build:
   ```bash
   sudo env BUILDX_CONFIG=/mnt/geospark/.buildx docker compose -f docker-compose.prod.yml \
     -f docker-compose.override.yml up -d --no-deps --no-build overpass
   docker logs -f geospark-overpass        # download, conversion, import, "ready to receive requests"
   docker stats --no-stream geospark-overpass; uptime
   ```
   Expect about 60–120 min, depending on the server's single-core speed (measured: 69 min on the Mac;
   the conversion is single-threaded). It's a one-off. Later restarts skip it because `/db/init_done` exists.
5. **Verify from inside the network** (no public port; the `geospark-api` container has Python):
   ```bash
   docker exec geospark-api python -c "import httpx; q='[out:json][timeout:25];nwr[\"amenity\"~\"^(hospital|school|pharmacy|restaurant|bank|police)\$\"](-37.836,144.946,-37.800,144.992);out center;'; r=httpx.post('http://geospark-overpass/api/interpreter', data={'data': q}, timeout=60); print(r.status_code, len(r.json()['elements']), r.json()['osm3s']['timestamp_osm_base'])"
   ```
   Expect `200`, about 1,000 elements, and a timestamp from the last day or two.
6. **Check nothing else changed:**
   ```bash
   docker ps --format '{{.Names}} {{.ID}}' | sort | diff /mnt/geospark/.containers-before -
   # only a new "geospark-overpass" line is expected
   sudo find / -xdev \( -path /proc -o -path /sys -o -path /run -o -path /tmp -o -path /var/log \) -prune \
     -o -newer /mnt/geospark/.change-start -type f -print | grep -v '^/mnt/' | head -50
   # expected: only OS files (logs, timers, fail2ban, landscape, VS Code server), nothing from Docker or Overpass
   find /mnt/geospark/overpass ! -uid 1000 | head   # expected: empty
   du -sh /mnt/geospark/overpass
   ```
7. **Point GeoSpark at it**, only after the code change below is merged and deployed: add
   `GEOSPARK_OVERPASS_URL=http://geospark-overpass/api/interpreter` to `/mnt/geospark/.env`, then recreate
   `geospark` only:
   ```bash
   sudo env BUILDX_CONFIG=/mnt/geospark/.buildx docker compose -f docker-compose.prod.yml \
     -f docker-compose.override.yml up -d --no-deps --no-build geospark
   ```
   Then ask the live agent "hospitals near Federation Square" twice in a row: both should answer from
   OpenStreetMap within a second or two.
8. **Repo housekeeping** (a PR): add `overpass/` to `.gitignore` so `git status` on the server stays clean,
   and add a short "Optional: self-hosted Overpass" section to DEPLOY.md, like the Valhalla one.

**Rollback:** `docker stop geospark-overpass && docker rm geospark-overpass`, restore
`docker-compose.override.yml` and `.env` from the backups, recreate `geospark` only, and
`rm -rf /mnt/geospark/overpass` once the maintainer agrees. GeoSpark keeps working without it (public
mirrors, then Overture).

## How GeoSpark uses it (implemented: `GEOSPARK_OVERPASS_URL`)
In `geospark/knowledge/loaders.py`, `OverpassLoader`:

- New setting **`GEOSPARK_OVERPASS_URL`** (unset by default, so nothing changes for anyone else).
- **Coverage polygon:** Geofabrik publishes the extract's exact boundary,
  <https://download.geofabrik.de/australia-oceania/australia.poly>. It's a single 22-point polygon, small
  enough to ship in the code (with a `GEOSPARK_OVERPASS_POLY` path to override it for another region). A
  bounding rectangle is **not** enough: the extract's bounds (lon 68.1–169.0, lat −57.1 to −8.8) also contain
  Timor, southern Papua New Guinea, New Caledonia and part of New Zealand's South Island. Checked with
  shapely: Federation Square, Hobart, Thursday Island, Saibai Island (Torres Strait), Norfolk Island and
  Christmas Island are inside; Zurich, Port Moresby, Daru (PNG), Dili, Kupang, Nouméa and Milford Sound
  are outside.
- `load_amenities_by_type(bbox, ...)` passes its bbox to `_query`. If the URL is set and the **whole** query
  bbox (all four corners) lies inside the polygon, the local server is asked **first and alone**, with a
  short timeout (~10 s; measured answers take 0.2–1.2 s). Its answer is used even when it is empty: inside
  the polygon, "no elements" means "nothing mapped there".
- If the local server errors, times out or returns a non-JSON body, fall back to the current race of the
  public mirrors (`OVERPASS_URLS`), then Overture as today. The public mirrors also handle everything outside
  the polygon, bboxes that cross its edge, and anything without a bbox (`load_admin_boundary`, `load_city`).
- **Outside coverage vs. nothing there:** the local Overpass can't tell you a point is outside its data. For
  Zurich it answers `200` with **0 elements**, exactly as it does for an empty spot in the Simpson Desert. So
  the decision must be made *before* querying, from the polygon, never from an empty answer. This mirrors
  the Valhalla `/locate` coverage check added on 2026-10-22. As a staleness guard, if
  `osm3s.timestamp_osm_base` is more than ~7 days old (updates stopped), log a warning and add a caveat.
- The 5-minute "Overpass is down" skip in `geospark/agents/amenities.py` should apply to the **public**
  servers only. A refused public mirror must not stop Australian points from using the local server. Move
  the cooldown into the loader, keyed per endpoint, or check `GEOSPARK_OVERPASS_URL` coverage before the
  cooldown.
- Cache key unchanged (the query text). Provenance stays `openstreetmap-overpass`; record the endpoint
  that answered in the run record so answers can be traced.
- Tests: a local server that answers is used and the public ones are not called; a bbox outside the polygon
  goes to the public race; a local failure falls through to the public race; the cooldown after a public
  failure doesn't block the local server.
- With `OVERPASS_FASTCGI_PROCESSES=4`, the local server runs up to 4 queries at once; the dispatcher queues
  the rest. GeoSpark sends one combined query per request, so this is plenty.

## Updating the data
- **Automatic, daily:** with `OVERPASS_DIFF_URL` set, the container's `update_overpass` loop checks every
  hour (`OVERPASS_UPDATE_SLEEP=3600`) and applies Geofabrik's daily diff when one is published (once a day;
  the latest was stamped 20:21 UTC). Progress goes to `/mnt/geospark/overpass/changes.log` and the container log. Check
  freshness with `osm3s.timestamp_osm_base` in any answer.
- `changes.log` grows by a few KB a day; truncate it occasionally (`: > /mnt/geospark/overpass/changes.log`).
- **Full rebuild** (only if the database is damaged or the image is upgraded across a format change): stop
  the container, `mv /mnt/geospark/overpass /mnt/geospark/overpass.old`, `mkdir` it again, start the
  service (the same build as step 4), verify, then delete `overpass.old`.
- **Image upgrades:** change the pinned tag, `docker compose pull overpass`, then `up -d --no-deps overpass`.
  The database is reused (`init_done`).
