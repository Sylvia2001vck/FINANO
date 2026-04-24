from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AgentProfileSave(BaseModel):
    """保存 MAFB 用的命理个性化画像（落库 + 返回结构化特征）。"""

    user_birth: str = Field(description="ISO 日期 YYYY-MM-DD")
    birth_time_slot: str | None = Field(
        default=None,
        description="出生时段编码：ZI/CHOU/YIN/MAO/CHEN/SI/WU/WEI/SHEN/YOU/XU/HAI",
    )
    user_mbti: str = Field(min_length=4, max_length=4)
    risk_preference: int | None = Field(default=None, ge=1, le=5, description="用户自报风险 1-5")


class MAFBRunRequest(BaseModel):
    fund_code: str = Field(min_length=4, max_length=10, description="锚定分析的基金/ETF 代码")
    include_fbti: bool = Field(
        default=True,
        description="为 true 时将账户已保存的 FBTI 纳入画像与后续推理；为 false 时仅用账户风险偏好档位（不含人格偏好）",
    )


class MAFBRunResponse(BaseModel):
    final_report: dict[str, Any]
    state_snapshot: dict[str, Any]


class LLMProbeRequest(BaseModel):
    model: str = Field(default="", description="可选覆盖模型名；为空时使用 FINANCE_MODEL_NAME / QWEN_FINANCE_MODEL")
    prompt: str = Field(min_length=1, max_length=2000, description="调试用短 prompt")
    timeout_sec: float = Field(default=10.0, ge=2.0, le=60.0, description="单次探针超时（秒）")
