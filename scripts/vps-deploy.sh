#!/usr/bin/env bash
# 在 VPS 上：项目根目录执行（与 docker-compose.yml 同级）。
# 期望已由 CI 把 frontend-dist.tgz 放到当前目录，或已手动解压好 frontend/dist。
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.prebuilt-frontend.yml)

if [[ -f frontend-dist.tgz ]]; then
  tar xzf frontend-dist.tgz -C frontend
  rm -f frontend-dist.tgz
fi

if [[ ! -d frontend/dist ]] || [[ -z "$(ls -A frontend/dist 2>/dev/null)" ]]; then
  echo "frontend/dist 为空或不存在：请先由 CI 上传 frontend-dist.tgz 或在 frontend 目录执行 npm run build" >&2
  exit 1
fi

"${COMPOSE[@]}" build --parallel 1 backend
"${COMPOSE[@]}" build frontend
"${COMPOSE[@]}" up -d
