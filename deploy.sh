#!/bin/bash
# deploy.sh - Deploy updated files into Docker containers on the server
# Usage: scp this to server, then run it
set -e

echo "=== Deploying bhawk booking updates ==="

# 1. Copy book_tee_time.py into bhawk-booking (write via docker exec to bypass read-only volume)
echo "[1/5] Updating book_tee_time.py in bhawk-booking..."
docker exec -i bhawk-booking bash -c 'cat > /app/book_tee_time.py' < /tmp/book_tee_time.py

# 2. Copy server.py into bhawk-status
echo "[2/5] Updating server.py in bhawk-status..."
docker exec -i bhawk-status sh -c 'cat > /app/server.py' < /tmp/server.py

# 3. Write booking_config.json to shared logs volume (writable from inside booking container)
echo "[3/5] Writing booking_config.json..."
docker exec -i bhawk-booking bash -c 'cat > /app/logs/booking_config.json' < /tmp/booking_config.json

# 4. Update cron to run daily (not just Saturdays)
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

# Verify
echo "=== Verification ==="
echo "CRON:"
docker exec bhawk-booking crontab -l
echo ""
echo "CONFIG:"
docker exec bhawk-booking cat /app/logs/booking_config.json
echo ""
echo "CONTAINERS:"
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
