#!/usr/bin/env bash
# ==============================================================================
# FXFX 24/5 Production Cloud VPS Setup Script
# Installs Python dependencies, sets up systemd background service,
# and enables automatic startup on reboot.
# ==============================================================================

set -e

echo ">>> [1/4] Updating Linux packages..."
sudo apt-get update -y
sudo apt-get install -y python3 python3-pip python3-venv git curl

echo ">>> [2/4] Setting up Python virtual environment..."
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo ">>> [3/4] Configuring systemd background service (fxfx.service)..."
CURRENT_DIR=$(pwd)
CURRENT_USER=$(whoami)

sudo bash -c "cat > /etc/systemd/system/fxfx.service" <<EOL
[Unit]
Description=FXFX 24/5 Live Multi-Strategy Trading Engine
After=network.target

[Service]
Type=simple
User=${CURRENT_USER}
WorkingDirectory=${CURRENT_DIR}
ExecStart=${CURRENT_DIR}/venv/bin/python -u src/live_engine.py
Restart=always
RestartSec=10
EnvironmentFile=${CURRENT_DIR}/.env

[Install]
WantedBy=multi-user.target
EOL

echo ">>> [4/4] Starting and enabling fxfx.service..."
sudo systemctl daemon-reload
sudo systemctl enable fxfx.service
sudo systemctl start fxfx.service

echo "=============================================================================="
echo "[SUCCESS] FXFX 24/5 Trading Engine is now running in the background!"
echo "Check status anytime with:  sudo systemctl status fxfx"
echo "View live logs with:        sudo journalctl -u fxfx -f"
echo "Stop engine with:           sudo systemctl stop fxfx"
echo "=============================================================================="
