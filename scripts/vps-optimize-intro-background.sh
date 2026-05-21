#!/usr/bin/env bash
# Run on VPS when SSH/Actions may disconnect. Survives logout; log: /tmp/finano-optimize-video.log
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="/tmp/finano-optimize-video.log"

{
  echo "=== $(date -Is) start ==="
  cd "${ROOT}"
  command -v git-lfs >/dev/null 2>&1 && git lfs pull || true
  if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "Installing ffmpeg..."
    sudo DEBIAN_FRONTEND=noninteractive apt-get update -qq
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y ffmpeg
  fi
  chmod +x scripts/optimize-intro-video.sh scripts/sync-pitch-deck.sh
  bash scripts/optimize-intro-video.sh
  bash scripts/sync-pitch-deck.sh
  ls -lh pitch-deck/assets/finano_concept.mp4 /var/www/finano-pitch-ppt/assets/finano_concept.mp4
  echo "=== $(date -Is) done ==="
} >> "${LOG}" 2>&1 &

echo "Running in background. Tail log: tail -f ${LOG}"
