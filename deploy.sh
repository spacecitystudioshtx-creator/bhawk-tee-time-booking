#!/bin/bash
# deploy.sh - Deploy updated files into Docker containers on the server
# Handles read-only container filesystems by finding host volume paths
set -e

echo "=== Deploying bhawk booking updates ==="

# 1. Update book_tee_time.py in bhawk-booking
echo "[1/5] Updating book_tee_time.py in bhawk-booking..."
docker exec -i bhawk-booking bash -c 'cat > /app/book_tee_time.py' < /tmp/book_tee_time.py

# 2. Update server.py in bhawk-status
# The container filesystem is read-only, so find the host bind-mount path
echo "[2/5] Updating server.py in bhawk-status..."
STATUS_APP_HOST=$(docker inspect bhawk-status --format '{{range .Mounts}}{{if eq .Destination "/app"}}{{.Source}}{{end}}{{end}}')
if [ -n "$STATUS_APP_HOST" ]; then
    cp /tmp/server.py "$STATUS_APP_HOST/server.py"
    echo "    Wrote to host path: $STATUS_APP_HOST/server.py"
else
    # Fallback: try to find it via the container's upper dir (overlay fs)
    STATUS_UPPER=$(docker inspect bhawk-status --format '{{.GraphDriver.Data.UpperDir}}')
    if [ -n "$STATUS_UPPER" ]; then
        mkdir -p "$STATUS_UPPER/app"
        cp /tmp/server.py "$STATUS_UPPER/app/server.py"
        echo "    Wrote to overlay upper dir"
    else
        echo "    ERROR: Could not find writable path for bhawk-status /app/"
        exit 1
    fi
fi

# 3. Write booking_config.json via booking container (logs volume is writable)
echo "[3/5] Writing booking_config.json..."
docker exec -i bhawk-booking bash -c 'cat > /app/logs/booking_config.json' < /tmp/booking_config.json

# 4. Update cron to run daily
echo "[4/5] Updating cron to daily schedule..."
docker exec bhawk-booking bash -c 'echo "50 6 * * * cd /app && DISPLAY=:99 HEADLESS=true /usr/bin/python3 /app/book_tee_time.py >> /app/logs/cron_\$(date +\%Y-\%m-\%d).log 2>&1" | crontab -'

# 5. Restart status dashboard to pick up new server.py
echo "[5/5] Restarting bhawk-status..."
docker restart bhawk-status

# Cleanup
rm -f /tmp/book_tee_time.py /tmp/server.py /tmp/booking_config.json /tmp/deploy.sh

echo ""
echo "=== Deploy complete ==="
echo ""
echo "=== Verification ==="
echo "CRON:"
docker exec bhawk-booking crontab -l
echo ""
echo "CONFIG:"
docker exec bhawk-booking cat /app/logs/booking_config.json
echo ""
echo "CONTAINERS:"
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
