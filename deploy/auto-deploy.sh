#!/bin/bash
# Auto-deploy GeoSpark: pull latest, rebuild if changed, restart
# Install via cron: */5 * * * * /mnt/geospark/deploy/auto-deploy.sh >> /mnt/geospark/deploy/deploy.log 2>&1
set -e

cd /mnt/geospark

# Fetch latest
git fetch origin main 2>/dev/null

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

if [ "$LOCAL" = "$REMOTE" ]; then
    exit 0  # No changes
fi

echo "$(date): Deploying $REMOTE (was $LOCAL)"

# Pull and rebuild
git pull origin main
docker compose -f docker-compose.prod.yml build --quiet
docker compose -f docker-compose.prod.yml up -d

echo "$(date): Deploy complete"
