#!/usr/bin/env bash
# Sync pitch-deck from repo checkout to Nginx web root (run on boot and after deploy).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="${ROOT}/pitch-deck"
DST="/var/www/finano-pitch-ppt"

if [[ ! -d "${SRC}" ]]; then
  echo "sync-pitch-deck: ${SRC} not found, skip" >&2
  exit 0
fi

# Intro video / BGM are Git LFS; without pull, only pointer files (~130B) get rsync'd.
if command -v git-lfs >/dev/null 2>&1 && git -C "${ROOT}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git -C "${ROOT}" lfs pull
fi

# CI/deploy user often cannot write /var/www without sudo (one-time: install-pitch-deck-boot.sh)
if [[ ! -d "${DST}" ]]; then
  sudo mkdir -p "${DST}"
fi
if [[ -w "${DST}" ]]; then
  rsync -a --delete "${SRC}/" "${DST}/"
else
  sudo rsync -a --delete "${SRC}/" "${DST}/"
fi
echo "sync-pitch-deck: ${SRC} -> ${DST}"

MP4="${SRC}/assets/finano_concept.mp4"
if [[ -f "${MP4}" ]]; then
  size="$(wc -c < "${MP4}" | tr -d ' ')"
  if [[ "${size}" -lt 1000000 ]]; then
    echo "sync-pitch-deck: WARN ${MP4} is only ${size} bytes — run: sudo apt install -y git-lfs && git lfs install && git lfs pull" >&2
  fi
fi
