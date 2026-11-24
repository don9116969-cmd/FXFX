#!/usr/bin/env bash
set -euo pipefail

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
user="$(id -un)"
if [[ "$user" == root || "$root" == *'"'* || "$root" == *$'\n'* || "$root" == *'%'* ]]; then
  echo 'Run as your regular VPS user from a directory without quotes, percent signs, or newlines.' >&2
  exit 1
fi
if [[ ! -f "$root/.env" ]]; then
  echo 'Create .env from deploy/paper.env.example before installing.' >&2
  exit 1
fi
chmod 600 "$root/.env"

if ! python3 -m venv "$root/.paper-venv"; then
  if command -v apt-get >/dev/null; then
    sudo apt-get update
    sudo apt-get install -y python3 python3-venv
  elif command -v dnf >/dev/null; then
    sudo dnf install -y python3 python3-pip
  else
    echo 'Install Python 3 and its venv support, then rerun the installer.' >&2
    exit 1
  fi
  python3 -m venv "$root/.paper-venv"
fi
"$root/.paper-venv/bin/python" -m pip install -r "$root/deploy/paper_requirements.txt"
(cd "$root" && "$root/.paper-venv/bin/python" -m src.paper_engine --check-config)

unit="$(mktemp)"
trap 'rm -f "$unit"' EXIT
cat > "$unit" <<EOF
[Unit]
Description=FXFX paper trading and Telegram status
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=$user
WorkingDirectory=$root
ExecStart="$root/.paper-venv/bin/python" -m src.paper_engine
Environment=PYTHONDONTWRITEBYTECODE=1
StateDirectory=fxfx-paper
StateDirectoryMode=0700
UMask=0077
Restart=on-failure
RestartSec=5s
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict

[Install]
WantedBy=multi-user.target
EOF
sudo install -m 0644 "$unit" /etc/systemd/system/fxfx-paper.service
sudo systemctl daemon-reload
sudo systemctl enable fxfx-paper.service
sudo systemctl restart fxfx-paper.service
sudo systemctl --no-pager status fxfx-paper.service
