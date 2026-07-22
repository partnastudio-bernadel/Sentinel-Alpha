#!/bin/bash
set -e

echo "[+] Installing Sentinel systemd services..."

# Ensure target directory exists
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

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
echo ""
echo "Check status:"
echo "  sudo systemctl status sentinel-scheduler"
echo "  sudo systemctl status sentinel-orchestrator"
echo "  sudo systemctl status sentinel-api"
