# Deploying GeoSpark

Get GeoSpark live on a free VM with Cloudflare Tunnel. Total cost: $0/month.

## Architecture

```
Internet --> Cloudflare Edge (SSL, DDoS) --> Tunnel --> geospark-api (127.0.0.1:8080)
                                                          |   private network "geospark-net"
                                                          +--> geospark-ollama    (local LLM: /ask, agents)
                                                          +--> geospark-valhalla  (isochrones, travel times)
                                                          +--> geospark-overpass  (OpenStreetMap queries)
                                                          |
                                                          +--> public data: Nominatim, Overture Maps (S3),
                                                               Copernicus DEM, Open-Meteo; OpenRouter (optional)
```

No public IP needed. No ports to open. No SSL certs to manage. Only the API is required; the three
services on the right are optional and each one is a block in
[`docker-compose.override.example.yml`](docker-compose.override.example.yml) (see "The full stack" below).

## Running on a shared server (read this first)

The production server also runs other apps (UrbanMind, TerraScout, GeoLibre, Umami). Anything added
for GeoSpark must leave them untouched and keep every byte under `/mnt`. These rules come from how the
server is actually set up (checked 2026-10-23), and every GeoSpark service follows them.

**How the server is organised**

| What | Where |
|---|---|
| Each app | its own folder and compose project: `/mnt/geospark`, `/mnt/urbanmind/app`, `/mnt/terrascout/app`, `/mnt/geolibre/app` |
| Container data | bind mounts from that app's folder, e.g. `/mnt/geospark/data`, `/mnt/geospark/valhalla`, `/mnt/ollama` |
| Images, layers, named volumes, container logs | Docker `data-root` = `/mnt/docker-data` (`/etc/docker/daemon.json`) |
| containerd | `root = /mnt/containerd-data`; only its runtime state is in `/run` (memory, not disk) |
| Log limits | json-file: 100 MB × 5 server-wide; GeoSpark containers 10 MB × 3 |
| Public traffic | each app's own Cloudflare tunnel container; app ports bind to `127.0.0.1` only |

**Rules for any new GeoSpark service** (Ollama and Valhalla are the examples)

1. **Data under `/mnt/geospark/<service>`**, as a bind mount you can see and back up. No anonymous
   volumes or paths elsewhere on the host. Check `docker info -f '{{.DockerRootDir}}'` prints
   `/mnt/docker-data` before starting anything new.
2. **Defined in `/mnt/geospark/docker-compose.override.yml`**, on the `geospark-net` network, with no
   published port (or `127.0.0.1:` only if the host truly needs it). The public reaches GeoSpark only
   through `geospark-cloudflared`.
3. **Run as uid 1000** (`user: "1000:1000"`) when the image allows it, so files are owned by `ubuntu`.
4. **Limits from a measured test run**: `deploy.resources.limits` for memory and CPUs (Valhalla: 6 GB,
   2 CPUs, measured build peak 4.2 GB), `restart: unless-stopped`, and json-file logs capped at
   `max-size: 10m`, `max-file: 3`.
5. **Build metadata stays under `/mnt`**: run compose as `sudo env BUILDX_CONFIG=/mnt/geospark/.buildx
   docker compose ...` (without it, buildx wrote 477 files to `/root/.docker`).
6. **Change only GeoSpark's services**, one at a time: `docker compose -f docker-compose.prod.yml -f
   docker-compose.override.yml up -d --no-deps <service>` (add `--no-build` to reuse the image).
   Never run `docker system prune`, `docker volume prune` or `docker image prune -a` (they delete other
   apps' data and images), never stop or restart the Docker daemon, and never touch another app's
   compose project, network or tunnel.
7. **Back up before editing**: `cp .env .env.bak-$(date +%F)-<reason>` and the same for
   `docker-compose.override.yml`. Every server change is approved by the maintainer first.

**Check that nothing else was affected**

```bash
# Before: note every container's ID; after the change, only GeoSpark's should differ
docker ps --format '{{.Names}} {{.ID}}' | sort > /mnt/geospark/.containers-before
# ... make the change ...
docker ps --format '{{.Names}} {{.ID}}' | sort | diff /mnt/geospark/.containers-before -

# Nothing written outside /mnt: mark the start, then list files newer than the marker elsewhere
sudo touch /mnt/geospark/.change-start
# ... make the change ...
sudo find / -xdev \( -path /proc -o -path /sys -o -path /run -o -path /tmp -o -path /var/log \) -prune \
  -o -newer /mnt/geospark/.change-start -type f -print | head -50
```

The last command should list only the operating system's own files (logs, timers), never anything
from Docker or the new service.

## The full stack (as run at geospark.terrascout.app)

[`deploy/docker-compose.override.example.yml`](docker-compose.override.example.yml) is the production
configuration: the API plus Ollama, Valhalla and Overpass, with the settings and limits that were measured
and tested. Use it like this:

1. `cp deploy/docker-compose.override.example.yml docker-compose.override.yml` (gitignored), and change the
   `/mnt/geospark/...` paths and the Geofabrik region if yours differ. Delete the services you don't want.
2. Start **one service at a time** with
   `docker compose -f docker-compose.prod.yml -f docker-compose.override.yml up -d --no-deps <service>`,
   and wait until it is healthy:
   - `ollama`, then `docker exec geospark-ollama ollama pull qwen2.5:7b` (about 5 GB of memory while loaded);
   - `valhalla`: builds its routing tiles (Australia: ~10 min, peak 4.2 GB, 3.8 GB on disk);
   - `overpass`: builds its database (Australia: ~55 min, peak 5.3 GB, 8.5 GB on disk).
3. Add the matching lines to `.env` (see [`.env.example`](../.env.example)) and recreate only the API:
   `GEOSPARK_VALHALLA_URL=http://geospark-valhalla:8002` and
   `GEOSPARK_OVERPASS_URL=http://geospark-overpass/api/interpreter`.
4. Check: `/api/v1/isochrone` answers for a point in your region, the agents find nearby places in under a
   second, and `docker ps` shows nothing else changed.

Without Valhalla, reachable-area requests are refused in production. Without Overpass, the agents use the
public Overpass servers (rate-limited) and fall back to Overture Maps. Without Ollama, `/ask` and the agents
need an OpenRouter key.

## Step 1: Get a Free VM

**Option A: Oracle Cloud Always Free (best specs)**
- 4 ARM cores, 24GB RAM (or 2x AMD 1GB)
- Truly free forever
- Caveat: Often out of capacity. Keep trying different regions.
- Sign up: https://cloud.oracle.com/

**Option B: Google Cloud e2-micro (most reliable)**
- 0.25 vCPU, 1GB RAM -- enough for GeoSpark API
- Always free in us-west1, us-central1, us-east1
- Sign up: https://cloud.google.com/free

**Option C: AWS t2.micro (12-month free)**
- 1 vCPU, 1GB RAM
- Free for 12 months
- Sign up: https://aws.amazon.com/free/

**Option D: fly.io (simplest)**
- 3 shared-cpu VMs free
- No credit card for small apps
- Sign up: https://fly.io/

For any VM, choose **Ubuntu 22.04 LTS** as the OS.

## Step 2: Set Up Cloudflare Tunnel

1. Log in to [Cloudflare Zero Trust](https://one.dash.cloudflare.com)
2. Go to **Networks > Tunnels**
3. Click **Create a tunnel**
4. Name it `geospark`
5. Choose **Cloudflared** as the connector
6. Copy the **tunnel token** (long string starting with `ey...`)
7. In **Public Hostname**, add:
   - Subdomain: `api` (or whatever you want)
   - Domain: your Cloudflare domain
   - Service: `http://geospark:8000`

## Step 3: Deploy

SSH into your VM, then:

```bash
# One-command setup
curl -sSL https://raw.githubusercontent.com/Maz2580/geospark/main/deploy/setup.sh | bash

# Edit your environment
cd ~/geospark
nano .env
# Set OPENROUTER_API_KEY and CLOUDFLARE_TUNNEL_TOKEN, plus GEOSPARK_ENV=production and
# GEOSPARK_ADMIN_TOKEN (required in production, see "Security" below)

# Start with tunnel
docker compose -f docker-compose.prod.yml --profile tunnel up -d
```

That's it. Your API is live at `https://api.yourdomain.com`.

## Step 4: Verify

```bash
# From anywhere
curl https://api.yourdomain.com/health
# {"status":"ok","version":"0.1.0","tools":["geocoder","terrain"]}

curl https://api.yourdomain.com/api/v1/status
# System status with uptime, memory, tool count

# Test a spatial query
curl -X POST https://api.yourdomain.com/api/v1/check-relationship \
  -H "Content-Type: application/json" \
  -d '{
    "geometry_a": {"type": "Polygon", "coordinates": [[[2.29, 48.85], [2.30, 48.85], [2.30, 48.86], [2.29, 48.86], [2.29, 48.85]]]},
    "geometry_b": {"type": "Point", "coordinates": [2.295, 48.855]},
    "relationship": "contains"
  }'
# {"relationship":"contains","result":true,"note":"Ground-truth spatial reasoning via GeoSpark"}
```

## Commands Reference

```bash
# View logs
docker compose -f docker-compose.prod.yml logs -f

# Restart
docker compose -f docker-compose.prod.yml restart

# Update to latest
cd ~/geospark && git pull
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml up -d

# Stop everything (GeoSpark's project only; on the shared server, prefer stopping one service)
docker compose -f docker-compose.prod.yml --profile tunnel down

# Check resource usage
docker stats geospark-api geospark-tunnel
```

## Memory Usage (Expected)

| Component | RAM |
|-----------|-----|
| GeoSpark API | ~200-400MB |
| cloudflared | ~50-100MB |
| **Total** | **~300-500MB** |

Fits comfortably on a 1GB VM. On Oracle's 24GB ARM, you'll have plenty of headroom.

## Troubleshooting

**Tunnel not connecting?**
- Check token: `docker logs geospark-tunnel`
- Verify tunnel is active in Cloudflare dashboard
- Ensure service URL is `http://geospark:8000` (Docker network name)

**Out of memory?**
- Check: `docker stats`
- Reduce workers: edit `Dockerfile.prod` CMD to `--workers 1`
- Add swap: `sudo fallocate -l 1G /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile`

**API returns 503?**
- Check: `docker logs geospark-api`
- Likely missing API key in `.env`

## Security

The public API is open by design: anyone can geocode, measure, query, ask and run agents
without a key. In production (`GEOSPARK_ENV=production`) the server **refuses to start
without `GEOSPARK_ADMIN_TOKEN`**, which protects:

| Needs the admin token | Examples |
|---|---|
| Operator data | `/api/v1/admin/*` (audit log, usage) |
| Flow storage | `POST /api/v1/flows`, `DELETE /api/v1/flows/{id}` |
| LLM gateway | `/api/v1/llm/chat`, `/generate`, `/embeddings`; partners can instead use a key from `GEOSPARK_GATEWAY_KEYS` |

Send the token as `X-Admin-Token: <token>` or `Authorization: Bearer <token>`.

Visitors get a private, size-capped, auto-expiring sandbox for the Memory and Context
demos. Public callers may choose only the local Ollama model or free OpenRouter models, so
nobody can spend paid API credit. Expensive routes are rate-limited per client IP and
capped by `GEOSPARK_MAX_LLM_CONCURRENCY`. All the settings are listed in `.env.example`.

```bash
# Generate a token, then add GEOSPARK_ADMIN_TOKEN=<token> to .env
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

## Optional: public MCP endpoint (`/mcp`)

The same fifteen read-only tools as `geospark-mcp`, over Streamable HTTP, so anyone can add
`https://<your-host>/mcp` to Claude or another MCP client as a custom connector. It never reads
files on the server, uses the normal rate limits (`GEOSPARK_RATE_LIMIT_MCP_RPM`, default 60 per
minute per visitor), and the visitor's own model does the reasoning, so it adds no LLM load.

To turn it on, change only the GeoSpark API container:

```bash
cd /mnt/geospark && cp .env .env.bak-$(date +%F)-mcp
grep -q '^GEOSPARK_MCP_HTTP' .env || printf '\nGEOSPARK_MCP_HTTP=true\n' >> .env
sudo env BUILDX_CONFIG=/mnt/geospark/.buildx docker compose -f docker-compose.prod.yml \
  -f docker-compose.override.yml up -d --no-deps --no-build geospark
```

`--no-deps` restarts only this service and `--no-build` reuses the current image. Check it with an
MCP `initialize` request to `/mcp`. To turn it off, remove the line and run the last command again.

## Optional: self-hosted Valhalla (isochrones and travel times)

`/api/v1/isochrone` and `/api/v1/travel-time` need a Valhalla routing server. Production refuses to
fall back to the volunteer-run public instance. Run one next to GeoSpark, the same way as Ollama: add a
`valhalla` service to `docker-compose.override.yml` (image `ghcr.io/valhalla/valhalla-scripted:<version>`):
- `user: "1000:1000"`, with a bind mount of `/mnt/geospark/valhalla:/custom_files`
- `tile_urls` set to a Geofabrik extract, e.g. Australia
- `server_threads=2` (more threads crashed the build stage in testing)
- `networks: [geospark-net]` and no published port
- limits of `cpus: 2` and `memory: 6G`

Start only that service (`docker compose ... up -d --no-deps valhalla`), then set
`GEOSPARK_VALHALLA_URL=http://geospark-valhalla:8002` in `.env` and recreate `geospark` only.

Australia, measured: about 10 min to build on the server (peak 4.2 GB), 3.8 GB on disk, about 150 MB while
serving. Points outside the extract are refused ("outside its map coverage") rather than answered with
Valhalla's placeholder circle. To refresh the map data, set `force_rebuild=True` once and restart the
container.

## Optional: self-hosted Overpass (OpenStreetMap queries for the agents)

The agents' nearby-place lookups (hospitals, schools, pharmacies...) use Overpass. The public servers
rate-limit by IP, so a busy site soon gets refused. Run one for your region next to GeoSpark and point
`GEOSPARK_OVERPASS_URL` at it (for example `http://geospark-overpass/api/interpreter`): queries whose
area lies inside its coverage polygon go to it first, everything else to the public servers.

The full plan, measurements and the exact service block are in
[OVERPASS_SELFHOST_PLAN.md](OVERPASS_SELFHOST_PLAN.md). In short: image `wiktorn/overpass-api:<version>`,
data in `/mnt/geospark/overpass:/db`, `geospark-net` only with no published port, limits `memory: 8G`,
`cpus: 2`, `OVERPASS_ALLOW_DUPLICATE_QUERIES=yes`. Australia takes about 70 minutes to build once, uses
8.5 GB of disk and under 100 MB of memory while serving, and answers in under a second. Coverage defaults
to the bundled Australia boundary (`geospark/knowledge/coverage/australia.poly`, from Geofabrik); set
`GEOSPARK_OVERPASS_POLY` for another region.
