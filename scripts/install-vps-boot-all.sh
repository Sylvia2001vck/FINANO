#!/usr/bin/env bash
# One-time: after instance reboot, auto-start product (:8081) + pitch deck (:8082).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

echo "==> Enable Docker on boot"
sudo systemctl enable docker
sudo systemctl start docker

echo "==> Install FINANO Docker Compose autostart (:8081)"
chmod +x scripts/sync-pitch-deck.sh
sudo cp scripts/finano-app.service /etc/systemd/system/finano-app.service
sudo systemctl daemon-reload
sudo systemctl enable finano-app.service

echo "==> Install pitch deck Nginx autostart (:8082)"
bash scripts/install-pitch-deck-boot.sh

echo "==> Start stacks now (no rebuild)"
sudo systemctl start finano-app.service || true
sudo systemctl start finano-pitch-sync.service || true
sudo systemctl reload nginx || sudo systemctl start nginx

echo ""
echo "==> Quick check"
bash scripts/diagnose-vps.sh
