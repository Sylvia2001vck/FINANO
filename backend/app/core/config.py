from __future__ import annotations

import json
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    project_name: str = "Finano"
    environment: str = "development"
    api_v1_prefix: str = "/api/v1"
    debug: bool = True

    database_url: str = "sqlite:///./finano.db"

    secret_key: str = "change-me-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440

    baidu_ocr_app_id: str = ""
    baidu_ocr_api_key: str = ""
    baidu_ocr_secret_key: str = ""
    dashscope_api_key: str = ""
    # 国际/新加坡控制台创建的 Key 通常需走国际域名；为 true 时等价于 DASHSCOPE_BASE_URL 指向 dashscope-intl
    dashscope_use_intl: bool = Field(default=False, alias="DASHSCOPE_USE_INTL")
    # 显式覆盖 DashScope OpenAPI 根路径（须含 /api/v1，或只填 host 由程序补全）。留空则国内用 SDK 默认、国际用 USE_INTL
    dashscope_base_url: str = Field(default="", alias="DASHSCOPE_BASE_URL")
    # 优先使用 FINANCE_MODEL_NAME（如 qwen3-max、qwen-plus）；未设时回退 QWEN_FINANCE_MODEL
    finance_model_name: str = Field(default="", alias="FINANCE_MODEL_NAME")
    # 回退：DashScope 模型名（与 FINANCE_MODEL_NAME 二选一即可）
    qwen_finance_model: str = Field(default="qwen-plus", alias="QWEN_FINANCE_MODEL")
    # MAFB 推理模式：auto=先云端后本地；cloud_only；local_only（无网演示）
    mafb_llm_mode: str = "auto"
    deepseek_api_key: str = ""
    deepseek_api_base: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-chat"
    ollama_base_url: str = ""
    ollama_model: str = ""
    # 离线兜底：Qwen-1.8B 系开源权重（默认官方 Chat；可改为 HF 上金融微调仓库名）
    local_finance_model_id: str = "Qwen/Qwen1.8B-Chat"
    local_finance_llm_enabled: bool = True
    local_finance_max_new_tokens: int = 384

    cors_origins_raw: str = Field(
        default='["http://localhost:5173", "http://127.0.0.1:5173"]',
        alias="CORS_ORIGINS",
    )

    # 环境变量 FUND_LIVE_QUOTE_ENABLED=true 时合并天天基金估值 JSONP（失败则仅用静态池）
    fund_live_quote_enabled: bool = False
    # static=内置演示池；eastmoney_full=启动后首次访问时从天天基金 fundcode_search.js 拉全市场索引（约 1.5 万+）
    fund_catalog_mode: str = Field(default="static", alias="FUND_CATALOG_MODE")

    @property
    def cors_origins(self) -> List[str]:
        raw = self.cors_origins_raw.strip()
        if raw.startswith("["):
            return json.loads(raw)
        return [item.strip() for item in raw.split(",") if item.strip()]

    @property
    def dashscope_finance_model(self) -> str:
        """MAFB / DashScope 实际调用的模型名（通用强模型 + 金融 Prompt ≈ 垂直金融助手）。"""
        name = (self.finance_model_name or "").strip()
        return name if name else self.qwen_finance_model

    @property
    def dashscope_http_api_root(self) -> str | None:
        """
        传给 dashscope Python SDK 的 OpenAPI 根（通常以 /api/v1 结尾）。
        None：不覆盖，使用 SDK 默认（中国大陆 dashscope.aliyuncs.com）。
        """
        raw = (self.dashscope_base_url or "").strip().rstrip("/")
        if raw:
            return raw if raw.endswith("/api/v1") else f"{raw}/api/v1"
        if self.dashscope_use_intl:
            return "https://dashscope-intl.aliyuncs.com/api/v1"
        return None


settings = Settings()
