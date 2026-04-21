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
    # 并行打分智能体（基本面/技术面/风控）单次 LLM 总等待上限（秒），超时走规则引擎，避免卡死
    mafb_agent_llm_timeout_sec: float = Field(default=16.0, alias="MAFB_AGENT_LLM_TIMEOUT_SEC", ge=4, le=120)
    # 云端主模型（DashScope）单链路超时（秒），超时后立即降级到后续通道
    mafb_cloud_primary_timeout_sec: float = Field(default=8.0, alias="MAFB_CLOUD_PRIMARY_TIMEOUT_SEC", ge=2.0, le=30.0)
    # 主模型协议/路由异常时的自动回退模型（同 DashScope 通道）
    mafb_qwen_fallback_model: str = Field(default="qwen-plus", alias="MAFB_QWEN_FALLBACK_MODEL")
    # qwen3* 仅灰度：false 时主链路不启用 qwen3（建议只在探针/灰度环境开启）
    mafb_qwen3_gray_enabled: bool = Field(default=False, alias="MAFB_QWEN3_GRAY_ENABLED")
    # qwen3 灰度允许的 Agent 列表（逗号分隔）：例如 profiling,kline
    mafb_qwen3_gray_agents_raw: str = Field(default="profiling,kline", alias="MAFB_QWEN3_GRAY_AGENTS")
    # qwen3 协议握手独立超时（秒），失败立即降级，避免吃满主链路 timeout
    mafb_llm_handshake_timeout_sec: float = Field(default=2.5, alias="MAFB_LLM_HANDSHAKE_TIMEOUT_SEC", ge=1.0, le=8.0)
    # 按 Agent 单独指定模型（留空则回退到 FINANCE_MODEL_NAME / QWEN_FINANCE_MODEL）
    mafb_model_fundamental: str = Field(default="", alias="MAFB_MODEL_FUNDAMENTAL")
    mafb_model_technical: str = Field(default="", alias="MAFB_MODEL_TECHNICAL")
    mafb_model_risk: str = Field(default="", alias="MAFB_MODEL_RISK")
    mafb_model_profiling: str = Field(default="", alias="MAFB_MODEL_PROFILING")
    mafb_model_kline: str = Field(default="", alias="MAFB_MODEL_KLINE")
    mafb_model_compliance: str = Field(default="", alias="MAFB_MODEL_COMPLIANCE")
    # 并行智能体的 LLM 并发上限（默认 1：减少同模型并发排队导致的超时）
    mafb_llm_max_concurrency: int = Field(default=1, alias="MAFB_LLM_MAX_CONCURRENCY", ge=1, le=8)
    # K 线相似：对候选基金拉历史净值的最大次数（再大主要被 lsjz 节流拖慢）
    mafb_kline_similar_max_nav_fetches: int = Field(default=64, alias="MAFB_KLINE_SIMILAR_MAX_NAV_FETCHES", ge=16, le=400)
    # tiered：PAA 分段数（粗排特征维度）
    mafb_kline_paa_bins: int = Field(default=32, alias="MAFB_KLINE_PAA_BINS", ge=8, le=128)
    # tiered：粗排后进入 DTW 精排的最大候选数（控制耗时）
    mafb_kline_fine_pool: int = Field(default=48, alias="MAFB_KLINE_FINE_POOL", ge=8, le=200)
    # Sakoe-Chiba 带相对半宽（越大越接近全量 DTW、越慢）
    mafb_kline_dtw_band_ratio: float = Field(default=0.18, alias="MAFB_KLINE_DTW_BAND_RATIO", ge=0.05, le=0.5)
    # tiered 精排最大耗时（秒）；超时时回退粗排结果并标记 fast_mode
    mafb_kline_fine_timeout_sec: float = Field(default=2.0, alias="MAFB_KLINE_FINE_TIMEOUT_SEC", ge=0.2, le=20.0)
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
    # 区间 lsjz-json：热数据直接内存命中（秒回）；超过热 TTL 后尝试增量合并而非整段重翻页
    fund_lsjz_hot_ttl_sec: float = Field(default=180.0, ge=15.0, le=3600.0, alias="FUND_LSJZ_HOT_TTL_SEC")
    fund_lsjz_stale_max_sec: float = Field(default=86400.0, ge=60.0, le=604800.0, alias="FUND_LSJZ_STALE_MAX_SEC")
    fund_lsjz_incremental_merge: bool = Field(default=True, alias="FUND_LSJZ_INCREMENTAL_MERGE")
    fund_lsjz_http_cache_max: int = Field(default=512, ge=32, le=5000, alias="FUND_LSJZ_HTTP_CACHE_MAX")
    # K8s 多副本：可选 Redis 分布式缓存（未配置时自动回退进程内缓存）
    redis_url: str = Field(default="", alias="REDIS_URL")
    redis_cache_prefix: str = Field(default="finano", alias="REDIS_CACHE_PREFIX")
    redis_socket_timeout_sec: float = Field(default=1.2, ge=0.2, le=10.0, alias="REDIS_SOCKET_TIMEOUT_SEC")
    # 热点聚合：服务端定时批处理 + 客户端读缓存
    hot_scheduler_enabled: bool = Field(default=True, alias="HOT_SCHEDULER_ENABLED")
    hot_refresh_interval_sec: int = Field(default=3600, ge=300, le=86400, alias="HOT_REFRESH_INTERVAL_SEC")
    hot_top_n: int = Field(default=10, ge=3, le=30, alias="HOT_TOP_N")
    hot_cache_ttl_sec: int = Field(default=3900, ge=60, le=172800, alias="HOT_CACHE_TTL_SEC")

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
    def mafb_qwen3_gray_agents(self) -> List[str]:
        return [item.strip().lower() for item in self.mafb_qwen3_gray_agents_raw.split(",") if item.strip()]

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
