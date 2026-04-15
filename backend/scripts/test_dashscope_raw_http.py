#!/usr/bin/env python3
"""
纯 HTTP 打新加坡国际站（与 curl 对照）。

- **多模态**模型（如 qwen3.6-plus、带 VL 的型号）须用：
  .../services/aigc/multimodal-generation/generation
- **纯文本**模型（如 qwen-plus）一般用：
  .../services/aigc/text-generation/generation

密钥从 backend/.env 的 DASHSCOPE_API_KEY 读取，勿写进代码。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import httpx  # noqa: E402

from app.core.config import settings  # noqa: E402

INTL_MULTIMODAL_URL = (
    "https://dashscope-intl.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
)


def main() -> None:
    key = (settings.dashscope_api_key or "").strip()
    if not key:
        print("未配置 DASHSCOPE_API_KEY（backend/.env）", file=sys.stderr)
        sys.exit(1)

    model = settings.dashscope_finance_model
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    # 多模态 OpenAPI：messages[].content 为 parts 数组
    body = {
        "model": model,
        "input": {
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": "只回复两个字：你好"}],
                }
            ]
        },
        "parameters": {"result_format": "message", "max_tokens": 64},
    }

    print("POST", INTL_MULTIMODAL_URL)
    print("model:", model)
    r = httpx.post(INTL_MULTIMODAL_URL, headers=headers, json=body, timeout=120.0)
    print("status:", r.status_code)
    try:
        print(json.dumps(r.json(), ensure_ascii=False, indent=2)[:8000])
    except Exception:
        print(r.text[:8000])


if __name__ == "__main__":
    main()
