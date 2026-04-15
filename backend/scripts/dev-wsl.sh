#!/usr/bin/env bash
# WSL / Linux：在 backend 目录创建 .venv 并启动 uvicorn
# 优先 python3.10→3.11→3.12；若无则使用 python3（须 <3.13，避免 SQLAlchemy 等兼容问题）
# 用法：chmod +x scripts/dev-wsl.sh && ./scripts/dev-wsl.sh
set -euo pipefail

BACKEND_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$BACKEND_ROOT"

py_lt_313() {
  local cmd="$1"
  "$cmd" -c 'import sys; raise SystemExit(0 if sys.version_info < (3, 13) else 1)' 2>/dev/null
}

pick_python() {
  for cmd in python3.10 python3.11 python3.12; do
    if command -v "$cmd" &>/dev/null && py_lt_313 "$cmd"; then
      echo "$cmd"
      return 0
    fi
  done
  if command -v python3 &>/dev/null && py_lt_313 python3; then
    echo python3
    return 0
  fi
  if command -v python3 &>/dev/null; then
    echo "当前 python3 为 3.13+，与本项目依赖不兼容。请安装 python3.12：sudo apt install python3.12 python3.12-venv" >&2
  fi
  return 1
}

PY="$(pick_python || true)"
if [[ -z "$PY" ]]; then
  echo "未找到可用的 Python（需要 3.10～3.12）。请先安装，例如："
  echo "  sudo apt update && sudo apt install -y python3 python3-venv python3-pip"
  echo "若仍无 3.12：sudo apt install -y python3.12 python3.12-venv"
  exit 1
fi

if [[ ! -d .venv ]]; then
  if ! "$PY" -m venv .venv 2>/dev/null; then
    echo "创建 venv 失败。请安装 venv 组件，例如："
    echo "  sudo apt update && sudo apt install -y python3-venv"
    echo "或（指定小版本）：sudo apt install -y python3.12-venv"
    exit 1
  fi
fi

# shellcheck source=/dev/null
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# --app-dir：WSL 下项目在 /mnt/d/ 时，强制以 backend 为根解析 app 包，避免偶发导入/路由不完整
exec uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 --app-dir "$BACKEND_ROOT"
