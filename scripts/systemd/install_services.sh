#!/bin/bash
set -e

# Dynamically resolve directory path where install_services.sh is executed
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$( cd "$SCRIPT_DIR/../.." && pwd )"
USER_NAME="$(whoami)"

# Resolve Python venv path
PYTHON_BIN="$PROJECT_DIR/venv/bin/python"
UVICORN_BIN="$PROJECT_DIR/venv/bin/uvicorn"

if [ ! -f "$PYTHON_BIN" ]; then
    PYTHON_BIN="$(which python3)"
fi

echo "[+] Installing Sentinel systemd services..."
echo "  - Project Directory: $PROJECT_DIR"
echo "  - Python Executable: $PYTHON_BIN"
echo "  - System User:       $USER_NAME"

mkdir -p "$PROJECT_DIR/logs"

# Generate sentinel-scheduler.service dynamically
cat <<EOF | sudo tee /etc/systemd/system/sentinel-scheduler.service > /dev/null
[Unit]
Description=Sentinel Macro Scheduler Daemon
After=network.target

[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$PROJECT_DIR
ExecStart=$PYTHON_BIN scripts/macro_scheduler_cli.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

# Generate sentinel-orchestrator.service dynamically
cat <<EOF | sudo tee /etc/systemd/system/sentinel-orchestrator.service > /dev/null
[Unit]
Description=Sentinel Portfolio Orchestrator Daemon
After=network.target

[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$PROJECT_DIR
ExecStart=$PYTHON_BIN scripts/sentinel_orchestrator.py --background
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

# Generate sentinel-api.service dynamically
cat <<EOF | sudo tee /etc/systemd/system/sentinel-api.service > /dev/null
[Unit]
Description=Sentinel IntentCore FastAPI Webhook Server
After=network.target

[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$PROJECT_DIR
ExecStart=$UVICORN_BIN functions.api.server:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

echo "[+] Reloading systemd manager configuration..."
sudo systemctl daemon-reload

echo "[+] Enabling services to start on boot..."
sudo systemctl enable sentinel-scheduler.service
sudo systemctl enable sentinel-orchestrator.service
sudo systemctl enable sentinel-api.service

echo "[+] Restarting services..."
sudo systemctl restart sentinel-scheduler.service
sudo systemctl restart sentinel-orchestrator.service
sudo systemctl restart sentinel-api.service

echo "🎉 All Sentinel services dynamically generated, installed, and started!"
