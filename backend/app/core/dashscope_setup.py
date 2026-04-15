"""DashScope SDK 全局配置：api_key + 可选国际节点 / 自定义 OpenAPI 根。"""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


def apply_dashscope_settings(dashscope_module: Any) -> None:
    """
    在每次 Generation.call 前调用：写入 api_key，并按需覆盖国际/自定义域名。

    阿里云文档（新加坡）推荐只设置 **base_http_api_url** 为带 **/api/v1** 的根：
    https://dashscope-intl.aliyuncs.com/api/v1

    切勿与 **base_api_url**（仅 host）同时写入，否则部分 dashscope 版本会拼出错误 path，返回 400 url error。

    若当前安装的 SDK 仅有 **base_api_url**、没有 **base_http_api_url**，再退化为只设 host（与旧版示例一致）。
    环境变量：DASHSCOPE_USE_INTL=true 或 DASHSCOPE_BASE_URL=...
    """
    key = (settings.dashscope_api_key or "").strip()
    if not key:
        return
    dashscope_module.api_key = key
    root = settings.dashscope_http_api_root
    if not root:
        return
    if hasattr(dashscope_module, "base_http_api_url"):
        dashscope_module.base_http_api_url = root
        logger.debug("DashScope base_http_api_url=%s", root)
        return
    host = root.removesuffix("/api/v1").rstrip("/")
    if hasattr(dashscope_module, "base_api_url"):
        dashscope_module.base_api_url = host
        logger.debug("DashScope base_api_url=%s (fallback, no base_http_api_url)", host)
