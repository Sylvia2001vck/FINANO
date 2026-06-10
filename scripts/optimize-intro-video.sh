#!/usr/bin/env bash
# Re-encode intro MP4 for smooth web playback:
#   - 720p max, 30fps, H.264 faststart
#   - Grayscale baked in (no CSS filter jank)
#   - Keeps audio track (AAC)
# Requires: ffmpeg
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${ROOT}/pitch-deck/assets/finano_concept.mp4"
BAK="${ROOT}/pitch-deck/assets/finano_concept.source.mp4"
TMP="${OUT}.tmp.mp4"
FORCE=0

for arg in "$@"; do
  case "${arg}" in
    --force) FORCE=1 ;;
  esac
done

if [[ ! -f "${OUT}" ]]; then
  echo "Missing ${OUT}" >&2
  exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "Install ffmpeg: sudo apt install -y ffmpeg" >&2
  exit 1
fi

size="$(wc -c < "${OUT}" | tr -d ' ')"

if [[ "${FORCE}" -eq 0 ]] && [[ "${size}" -gt 500000 ]] && [[ "${size}" -lt 6000000 ]]; then
  echo "optimize-intro-video: ${OUT} is already ${size} bytes (~web size)."
  echo "Re-run with --force to re-encode (grayscale + audio + smoother settings)."
  exit 0
fi

if [[ ! -f "${BAK}" ]]; then
  if [[ "${size}" -lt 1000000 ]]; then
    echo "ERROR: ${OUT} is only ${size} bytes (Git LFS pointer?). Run: git lfs pull" >&2
    exit 1
  fi
  cp -a "${OUT}" "${BAK}"
  echo "Backed up original -> finano_concept.source.mp4"
fi

if [[ -f "${BAK}" ]] && [[ "$(wc -c < "${BAK}" | tr -d ' ')" -gt 1000000 ]]; then
  INPUT="${BAK}"
else
  INPUT="${OUT}"
fi

# Grayscale + contrast in ffmpeg (avoid CSS filter on <video> during playback).
# fps=30 + 720p + tune fastdecode keeps decode light on low-end GPUs.
VF="scale='min(720,iw)':-2:flags=lanczos,fps=30,format=yuv420p,hue=s=0,eq=contrast=1.08:brightness=0.03"

echo "optimize-intro-video: encoding ${INPUT} (720p grayscale, audio kept, ~2–4 min on VPS)..."
ffmpeg -y -i "${INPUT}" \
  -map 0:v:0 -map 0:a:0? \
  -vf "${VF}" \
  -c:v libx264 -preset veryfast -crf 24 -profile:v main -level 3.1 \
  -g 60 -keyint_min 60 -sc_threshold 0 -tune fastdecode \
  -c:a aac -b:a 128k -ar 48000 -ac 2 \
  -movflags +faststart \
  "${TMP}"

mv -f "${TMP}" "${OUT}"
ls -lh "${OUT}" "${BAK}"
ffprobe -hide_banner -loglevel error -show_entries stream=codec_type,codec_name,width,height,r_frame_rate -of default=nw=1 "${OUT}" 2>/dev/null || true
echo "Done. Sync: bash scripts/sync-pitch-deck.sh"
