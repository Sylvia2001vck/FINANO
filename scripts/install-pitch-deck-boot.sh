#!/usr/bin/env bash
# One-time on VPS: Nginx :8082 + sync on boot + enable nginx on reboot.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

chmod +x scripts/sync-pitch-deck.sh

echo "==> Install systemd unit (sync pitch-deck before nginx)"
sudo cp scripts/finano-pitch-sync.service /etc/systemd/system/finano-pitch-sync.service
sudo systemctl daemon-reload
sudo systemctl enable finano-pitch-sync.service

echo "==> Initial sync"
bash scripts/sync-pitch-deck.sh

echo "==> Configure Nginx :8082"
bash scripts/setup-pitch-deck-nginx.sh

echo "==> Enable Nginx on boot"
sudo systemctl enable nginx
sudo systemctl start finano-pitch-sync.service 2>/dev/null || true
sudo systemctl reload nginx

echo ""
echo "Done. After reboot, :8082 will come back automatically."
echo "  systemctl status finano-pitch-sync.service"
echo "  systemctl status nginx"
echo "  curl -I http://127.0.0.1:8082/"
