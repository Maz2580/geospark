# Deploying GeoSpark

Get GeoSpark live on a free VM with Cloudflare Tunnel. Total cost: $0/month.

## Architecture

```
Internet --> Cloudflare Edge (SSL, DDoS) --> Tunnel --> VM:8000 (GeoSpark API)
                                                        |
                                                        +--> Supabase (remote DB)
                                                        +--> OpenRouter (free LLMs)
```

No public IP needed. No ports to open. No SSL certs to manage.

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
# Set OPENROUTER_API_KEY and CLOUDFLARE_TUNNEL_TOKEN

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

# Stop everything
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
