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

mkdir -p "${DST}"
rsync -a --delete "${SRC}/" "${DST}/"
echo "sync-pitch-deck: ${SRC} -> ${DST}"
