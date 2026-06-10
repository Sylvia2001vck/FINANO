#!/usr/bin/env bash
# Pitch deck only (:8082). For product + pitch use install-vps-boot-all.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

chmod +x scripts/sync-pitch-deck.sh scripts/ensure-pitch-8082.sh scripts/diagnose-vps.sh

echo "==> Install systemd unit (sync pitch-deck before nginx on boot)"
sudo cp scripts/finano-pitch-sync.service /etc/systemd/system/finano-pitch-sync.service
sudo systemctl daemon-reload
sudo systemctl enable finano-pitch-sync.service

echo "==> Ensure Nginx :8082 is up now"
bash scripts/ensure-pitch-8082.sh

echo ""
echo "Done. After reboot, finano-pitch-sync + nginx bring back :8082."
echo "For product :8081 too, run: bash scripts/install-vps-boot-all.sh"
