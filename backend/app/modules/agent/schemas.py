from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AgentProfileSave(BaseModel):
    """保存 MAFB 用的命理个性化画像（落库 + 返回结构化特征）。"""

    user_birth: str = Field(description="ISO 日期 YYYY-MM-DD")
    user_mbti: str = Field(min_length=4, max_length=4)
    layout_facing: str | None = Field(default=None, description="N/S/E/W")
    risk_preference: int | None = Field(default=None, ge=1, le=5, description="用户自报风险 1-5")


class MAFBRunRequest(BaseModel):
    fund_code: str = Field(min_length=4, max_length=10, description="锚定分析的基金/ETF 代码")
    user_birth: str | None = Field(default=None, description="未传且 use_saved_profile 时用库中画像")
    user_mbti: str | None = None
    layout_facing: str | None = None
    use_saved_profile: bool = Field(default=False, description="为 true 时用数据库中已保存的 MBTI/生日等补齐缺省字段")


class MAFBRunResponse(BaseModel):
    final_report: dict[str, Any]
    state_snapshot: dict[str, Any]
