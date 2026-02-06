#!/bin/bash
# setup_server.sh - One-time server setup for the tee time booking bot
# Run this after cloning the repo on your server:
#   chmod +x setup_server.sh && sudo ./setup_server.sh
#
# What this does:
#   1. Installs Google Chrome (required by undetected-chromedriver)
#   2. Creates a Python virtual environment and installs dependencies
#   3. Creates logs/ and screenshots/ directories
#   4. Installs the cron job to run every Friday at 6:50 AM

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CRON_USER="${SUDO_USER:-$USER}"

echo "=== Black Hawk Tee Time Bot - Server Setup ==="
echo "Install directory: $SCRIPT_DIR"
echo "Cron user: $CRON_USER"
echo ""

# --- 1. Install Google Chrome ---
if ! command -v google-chrome &>/dev/null && ! command -v chromium-browser &>/dev/null; then
    echo "[1/4] Installing Google Chrome..."
    if command -v apt-get &>/dev/null; then
        apt-get update -qq
        apt-get install -y wget gnupg2
        wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg
        echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list
        apt-get update -qq
        apt-get install -y google-chrome-stable
    elif command -v yum &>/dev/null; then
        yum install -y wget
        wget https://dl.google.com/linux/direct/google-chrome-stable_current_x86_64.rpm
        yum localinstall -y google-chrome-stable_current_x86_64.rpm
        rm -f google-chrome-stable_current_x86_64.rpm
    else
        echo "ERROR: Could not detect package manager (apt/yum). Install Google Chrome manually."
        exit 1
    fi
    echo "Chrome installed successfully."
else
    echo "[1/4] Google Chrome already installed, skipping."
fi

# --- 2. Python virtual environment + dependencies ---
echo "[2/4] Setting up Python virtual environment..."
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found. Install Python 3.8+ first."
    exit 1
fi

cd "$SCRIPT_DIR"
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q
echo "Python dependencies installed."

# --- 3. Create output directories ---
echo "[3/4] Creating logs and screenshots directories..."
mkdir -p "$SCRIPT_DIR/logs" "$SCRIPT_DIR/screenshots"
chown -R "$CRON_USER":"$CRON_USER" "$SCRIPT_DIR/logs" "$SCRIPT_DIR/screenshots" 2>/dev/null || true

# --- 4. Install cron job ---
echo "[4/4] Installing cron job..."

# The cron entry: run every Friday at 6:50 AM (10 min before 7 AM booking opens)
CRON_CMD="50 6 * * 5 $SCRIPT_DIR/run_booking.sh"

# Check if cron job already exists for this user
EXISTING_CRON=$(crontab -u "$CRON_USER" -l 2>/dev/null || true)
if echo "$EXISTING_CRON" | grep -qF "run_booking.sh"; then
    echo "Cron job already exists, updating..."
    echo "$EXISTING_CRON" | grep -vF "run_booking.sh" | { cat; echo "$CRON_CMD"; } | crontab -u "$CRON_USER" -
else
    echo "Adding new cron job..."
    { echo "$EXISTING_CRON"; echo "$CRON_CMD"; } | crontab -u "$CRON_USER" -
fi

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Cron schedule: Every Friday at 6:50 AM"
echo "  The script will wait until exactly 7:00 AM to search for tee times."
echo ""
echo "Logs:        $SCRIPT_DIR/logs/"
echo "Screenshots: $SCRIPT_DIR/screenshots/"
echo ""
echo "To test manually:  cd $SCRIPT_DIR && ./run_booking.sh"
echo "To check cron:     crontab -l"
echo "To view last log:  ls -t $SCRIPT_DIR/logs/ | head -1 | xargs -I{} cat $SCRIPT_DIR/logs/{}"
