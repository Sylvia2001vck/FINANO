#!/usr/bin/env bash
# Re-encode intro MP4 for smooth web playback (H.264 + faststart, ~720p).
# Requires: ffmpeg (sudo apt install -y ffmpeg)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${ROOT}/pitch-deck/assets/finano_concept.mp4"
BAK="${ROOT}/pitch-deck/assets/finano_concept.source.mp4"
TMP="${OUT}.tmp.mp4"

if [[ ! -f "${OUT}" ]]; then
  echo "Missing ${OUT}" >&2
  exit 1
fi

size="$(wc -c < "${OUT}" | tr -d ' ')"
if [[ "${size}" -gt 500000 ]] && [[ "${size}" -lt 6000000 ]]; then
  echo "optimize-intro-video: ${OUT} is already ${size} bytes (~web size), skip encode."
  exit 0
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "Install ffmpeg: sudo apt install -y ffmpeg" >&2
  exit 1
fi

if [[ ! -f "${BAK}" ]]; then
  if [[ "${size}" -lt 1000000 ]]; then
    echo "ERROR: ${OUT} is only ${size} bytes (Git LFS pointer?). Run: git lfs pull" >&2
    exit 1
  fi
  cp -a "${OUT}" "${BAK}"
  echo "Backed up original -> finano_concept.source.mp4"
fi
if [[ "${size}" -lt 500000 ]] && [[ -f "${BAK}" ]] && [[ "$(wc -c < "${BAK}" | tr -d ' ')" -gt 1000000 ]]; then
  echo "Using backup source (current file looks already optimized or broken)."
  INPUT="${BAK}"
elif [[ -f "${BAK}" ]]; then
  INPUT="${BAK}"
else
  INPUT="${OUT}"
fi

echo "optimize-intro-video: encoding ${INPUT} (preset fast, ~1–3 min on VPS)..."
ffmpeg -y -i "${INPUT}" \
  -vf "scale='min(1280,iw)':-2" \
  -c:v libx264 -preset fast -crf 26 -profile:v main -pix_fmt yuv420p \
  -movflags +faststart \
  -an \
  "${TMP}"

mv -f "${TMP}" "${OUT}"
ls -lh "${OUT}" "${BAK}"
echo "Done. Commit & push pitch-deck/assets/finano_concept.mp4 (Git LFS), then redeploy."
