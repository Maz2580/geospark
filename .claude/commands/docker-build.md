# Build and Run GeoSpark Docker

Build Docker images and manage containers for GeoSpark.

## Instructions

1. Check `Dockerfile` and `docker-compose.yml` exist in project root
2. Build options:
   - Simple: `docker build -t geospark:latest .`
   - Full stack: `docker compose build`
3. Run options:
   - Dev: `docker compose up` (GeoSpark + PostGIS + Redis)
   - API only: `docker compose up geospark`
   - Detached: `docker compose up -d`
4. Verify:
   - Health check: `curl http://localhost:8000/health`
   - Info: `curl http://localhost:8000/api/v1/info`
5. Clean: `docker compose down -v` (removes volumes too)

## Environment Variables
Copy `.env.example` to `.env` and configure before building.
