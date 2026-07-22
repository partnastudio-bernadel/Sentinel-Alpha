#!/bin/bash
set -e

echo "[+] Installing Sentinel systemd services..."

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
SENTIMENT_DIR="$( cd "$SCRIPT_DIR/../.." && pwd )"

# Ensure logs directory exists
mkdir -p "$SENTIMENT_DIR/logs"

# Copy service unit files to /etc/systemd/system/
sudo cp "$SCRIPT_DIR/sentinel-scheduler.service" /etc/systemd/system/
sudo cp "$SCRIPT_DIR/sentinel-orchestrator.service" /etc/systemd/system/
sudo cp "$SCRIPT_DIR/sentinel-api.service" /etc/systemd/system/

# Reload systemd daemon
echo "[+] Reloading systemd manager configuration..."
sudo systemctl daemon-reload

# Enable services to start automatically on boot
echo "[+] Enabling services to start on boot..."
sudo systemctl enable sentinel-scheduler.service
sudo systemctl enable sentinel-orchestrator.service
sudo systemctl enable sentinel-api.service

# Start services
echo "[+] Starting services..."
sudo systemctl restart sentinel-scheduler.service
sudo systemctl restart sentinel-orchestrator.service
sudo systemctl restart sentinel-api.service

echo "🎉 All Sentinel services successfully installed, enabled, and started!"
