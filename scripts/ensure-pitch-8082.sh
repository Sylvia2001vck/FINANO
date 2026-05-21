#!/usr/bin/env bash
# Idempotent: make :8082 respond (install nginx if needed, sync files, start services).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

if ! command -v nginx >/dev/null 2>&1; then
  echo "ensure-pitch-8082: installing nginx..."
  sudo apt-get update -qq
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y nginx
fi

bash scripts/sync-pitch-deck.sh

if [[ ! -f /etc/nginx/sites-enabled/finano-pitch ]]; then
  bash scripts/setup-pitch-deck-nginx.sh
fi

if [[ -f scripts/finano-pitch-sync.service ]] && [[ ! -f /etc/systemd/system/finano-pitch-sync.service ]]; then
  sudo cp scripts/finano-pitch-sync.service /etc/systemd/system/
  sudo systemctl daemon-reload
  sudo systemctl enable finano-pitch-sync.service
fi

sudo systemctl enable nginx
sudo systemctl start finano-pitch-sync.service 2>/dev/null || true
sudo systemctl start nginx
sudo systemctl reload nginx

if curl -fsS -o /dev/null --connect-timeout 3 http://127.0.0.1:8082/; then
  echo "ensure-pitch-8082: OK http://127.0.0.1:8082/"
else
  echo "ensure-pitch-8082: local check failed — run: bash scripts/diagnose-vps.sh" >&2
  exit 1
fi
