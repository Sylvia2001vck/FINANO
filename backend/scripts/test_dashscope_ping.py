#!/usr/bin/env python3
"""
10 秒自测 DashScope 是否通（国际/国内由 backend/.env 决定）。

脚本会自动把工作目录切到「本文件所在仓库的 backend 根」，并读那里的 .env。
因此不必先 cd 到项目里，可用绝对路径从任意目录运行，例如 WSL：

  python /mnt/d/FINANO/backend/scripts/test_dashscope_ping.py

若项目不在 D 盘，请把路径换成你的 FINANO 实际位置；在资源管理器里对 D:\\FINANO
右键「复制路径」后，把反斜杠改成 / 并加上 /backend/scripts/... 即可。

或在 backend 目录下相对路径运行：

  cd /mnt/d/FINANO/backend
  python scripts/test_dashscope_ping.py

Windows（仓库在 D:\\FINANO）:

  d:\\FINANO\\backend\\.venv\\Scripts\\python.exe d:\\FINANO\\backend\\scripts\\test_dashscope_ping.py

依赖：须用「已安装 backend/requirements.txt 的 Python」运行；若报缺 dashscope，见运行时下方的 pip 命令。
逻辑与 **`app.agent.llm_client._invoke_dashscope`** 一致（Qwen3 自动走多模态接口）。

需已配置 DASHSCOPE_API_KEY；国际控制台 Key 请加 DASHSCOPE_USE_INTL=true
或 DASHSCOPE_BASE_URL=https://dashscope-intl.aliyuncs.com
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)


def _die_missing_deps(exc: ModuleNotFoundError) -> None:
    py = sys.executable
    print("当前 Python:", py, file=sys.stderr)
    print("错误:", exc, file=sys.stderr)
    print(
        "\n请在该环境里安装依赖（二选一）：\n"
        f"  {py} -m pip install dashscope==1.18.0 pydantic pydantic-settings\n"
        "或安装完整后端：\n"
        f"  cd {ROOT} && {py} -m pip install -r requirements.txt\n",
        file=sys.stderr,
    )
    sys.exit(4)


try:
    import dashscope
except ModuleNotFoundError as e:
    _die_missing_deps(e)

from app.agent.llm_client import (  # noqa: E402
    _augment_messages_with_finance_persona,
    _invoke_dashscope,
)
from app.core.config import settings  # noqa: E402
from app.core.dashscope_setup import apply_dashscope_settings  # noqa: E402


def main() -> None:
    if not (settings.dashscope_api_key or "").strip():
        print("未设置 DASHSCOPE_API_KEY，跳过。")
        sys.exit(1)

    apply_dashscope_settings(dashscope)
    root = settings.dashscope_http_api_root
    host = root.removesuffix("/api/v1").rstrip("/") if root else None
    print("dashscope_http_api_root:", root or "(default CN)")
    if getattr(dashscope, "base_http_api_url", None):
        print("sdk base_http_api_url:", dashscope.base_http_api_url)
    if getattr(dashscope, "base_api_url", None):
        print("sdk base_api_url:", dashscope.base_api_url)
    print("resolved host (info):", host or "(unset)")
    print("model:", settings.dashscope_finance_model)

    msgs = _augment_messages_with_finance_persona(
        [{"role": "user", "content": "只回复两个字：你好"}]
    )
    text = _invoke_dashscope(msgs, settings.dashscope_finance_model)
    if text is None:
        print("invoke failed (see backend logs / DashScope response above)")
        sys.exit(2)
    print("content:", text)


if __name__ == "__main__":
    main()
