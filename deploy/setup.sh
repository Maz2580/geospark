#!/usr/bin/env bash
# GeoSpark VM Setup Script
# Works on Ubuntu 22.04+ / Debian 12+ (Oracle Cloud, GCP, AWS free tiers)
#
# Usage:
#   curl -sSL https://raw.githubusercontent.com/Maz2580/geospark/main/deploy/setup.sh | bash
#   # or after cloning:
#   bash deploy/setup.sh

set -euo pipefail

echo "=== GeoSpark Production Setup ==="
echo ""

# --- 1. Install Docker if not present ---
if ! command -v docker &>/dev/null; then
    echo "[1/5] Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker "$USER"
    echo "  Docker installed. You may need to log out and back in for group changes."
else
    echo "[1/5] Docker already installed."
fi

# --- 2. Install Docker Compose plugin if not present ---
if ! docker compose version &>/dev/null 2>&1; then
    echo "[2/5] Installing Docker Compose plugin..."
    sudo apt-get update && sudo apt-get install -y docker-compose-plugin
else
    echo "[2/5] Docker Compose already installed."
fi

# --- 3. Clone or update GeoSpark ---
INSTALL_DIR="$HOME/geospark"
if [ -d "$INSTALL_DIR" ]; then
    echo "[3/5] Updating GeoSpark..."
    cd "$INSTALL_DIR"
    git pull --ff-only
else
    echo "[3/5] Cloning GeoSpark..."
    git clone https://github.com/Maz2580/geospark.git "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# --- 4. Configure environment ---
if [ ! -f .env ]; then
    echo "[4/5] Creating .env from template..."
    cp .env.production .env
    echo ""
    echo "  !! IMPORTANT: Edit .env with your API keys !!"
    echo "  nano $INSTALL_DIR/.env"
    echo ""
else
    echo "[4/5] .env already exists, keeping it."
fi

# --- 5. Build and start ---
echo "[5/5] Building and starting GeoSpark..."
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml up -d

echo ""
echo "=== GeoSpark is running! ==="
echo ""
echo "  API:     http://localhost:8000"
echo "  Health:  http://localhost:8000/health"
echo "  Status:  http://localhost:8000/api/v1/status"
echo "  Docs:    http://localhost:8000/docs"
echo ""
echo "To expose via Cloudflare Tunnel:"
echo "  1. Edit .env and set CLOUDFLARE_TUNNEL_TOKEN"
echo "  2. docker compose -f docker-compose.prod.yml --profile tunnel up -d"
echo ""
echo "Useful commands:"
echo "  docker compose -f docker-compose.prod.yml logs -f    # View logs"
echo "  docker compose -f docker-compose.prod.yml restart    # Restart"
echo "  docker compose -f docker-compose.prod.yml down       # Stop"
echo ""
