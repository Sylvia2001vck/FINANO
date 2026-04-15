"""
Finance LLM adapter — 双链路容灾：

1. 主力：阿里云 DashScope 通义千问（模型名由 FINANCE_MODEL_NAME / QWEN_FINANCE_MODEL 配置）
   + 统一「金融专家」系统人设（通用强模型 + 专业 Prompt ≈ 金融垂直助手，无需单独 qwen-finance SKU）
2. 降级：本地开源 Qwen-1.8B 系权重 CPU 推理（无需 API，见 local_qwen.py）
3. 备选：LangChain Tongyi、DeepSeek、Ollama
4. 再失败：由 nodes 规则引擎兜底，演示不翻车
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from pydantic import BaseModel, Field

from app.core.config import settings
from app.agent.local_qwen import invoke_local_qwen_finance

logger = logging.getLogger(__name__)

# 通用模型 + 专业人设 = 金融分析助手（与 DashScope 控制台实际模型名配合使用）
FINANCE_EXPERT_SYSTEM_PROMPT = """你是一位专业、持牌、严谨的金融投资顾问。
你擅长基金分析、资产配置、风险控制、投资回报评估。
你必须遵守合规要求：不预测短期涨跌、不承诺收益、不提供具体交易时点，只做客观分析。
你输出内容必须专业、清晰、有数据支撑、结构化、可执行。
请以专业金融分析师的身份回答。"""


def _augment_messages_with_finance_persona(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    """在首条 system 前叠加金融专家人设；若无 system 则插入一条。"""
    prefix = FINANCE_EXPERT_SYSTEM_PROMPT.strip() + "\n\n"
    out: list[dict[str, str]] = []
    for m in messages:
        out.append(dict(m))
    if not out:
        return [{"role": "system", "content": FINANCE_EXPERT_SYSTEM_PROMPT.strip()}]
    if out[0].get("role") == "system":
        out[0] = {
            "role": "system",
            "content": prefix + (out[0].get("content") or ""),
        }
    else:
        out.insert(0, {"role": "system", "content": FINANCE_EXPERT_SYSTEM_PROMPT.strip()})
    return out


class AgentScore(BaseModel):
    agent_name: str = Field(description="智能体名称")
    score: int = Field(ge=-2, le=2, description="打分 -2~+2")
    reason: str = Field(description="中性、合规的金融推理理由，禁止承诺收益")


class ComplianceLLMResult(BaseModel):
    """合规 Agent 结构化输出；最终是否拦截仍由硬规则兜底。"""

    allow_continue: bool = Field(description="是否允许进入最终组合输出")
    compliance_score: int = Field(ge=-2, le=2, description="投教话术合规倾向分")
    advisory_notes: str = Field(description="投教补充说明，避免违规表述")


def _extract_json_object(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        raise ValueError("no json object in model output")
    return json.loads(m.group())


def _parse_agent_score(raw: str, expected_name: str) -> AgentScore:
    data = _extract_json_object(raw)
    data.setdefault("agent_name", expected_name)
    return AgentScore.model_validate(data)


def _build_score_prompt(agent_role: str, fund: dict[str, Any], rag_chunks: list[str], user_risk: int) -> str:
    rag = "\n".join(f"- {c}" for c in (rag_chunks or [])[:6])
    fund_json = json.dumps(fund, ensure_ascii=False)
    return f"""你是公募基金/ETF投研助手，仅基于给定结构化数据做事实性评估，不预测价格，不承诺收益。
角色：{agent_role}
用户风险等级(1-5)：{user_risk}
基金事实(JSON)：{fund_json}
RAG检索片段：
{rag}

请严格输出一个 JSON 对象，键为 agent_name, score, reason。
score 为整数 -2~+2（-2 强烈负面，+2 强烈正面）。
reason 用中文，中性表述，须包含「历史不代表未来」类风险提示意涵（可简短）。
agent_name 使用英文标识：fundamental / technical / risk 之一。
不要输出 JSON 以外的任何文字。"""


def _invoke_dashscope(messages: list[dict[str, str]], model: str) -> str | None:
    if not settings.dashscope_api_key:
        return None
    try:
        import dashscope
    except ImportError:
        return None
    dashscope.api_key = settings.dashscope_api_key
    try:
        response = dashscope.Generation.call(
            model=model,
            messages=messages,
            result_format="message",
            temperature=0.1,
            max_tokens=512,
        )
        code = getattr(response, "status_code", None)
        if code is not None and code != 200:
            logger.warning("DashScope error: %s", response)
            return None
        choices = getattr(getattr(response, "output", None), "choices", None) or []
        if not choices:
            logger.warning("DashScope empty choices: %s", response)
            return None
        content = choices[0].message.content
        if isinstance(content, dict):
            return json.dumps(content, ensure_ascii=False)
        return str(content)
    except Exception:
        logger.exception("DashScope 调用失败 — 将尝试本地 Qwen-1.8B 降级")
        return None


def _invoke_tongyi(prompt: str) -> str | None:
    if not settings.dashscope_api_key:
        return None
    try:
        from langchain_community.llms import Tongyi
    except ImportError:
        return None
    try:
        model = settings.dashscope_finance_model
        try:
            llm = Tongyi(
                model=model,
                dashscope_api_key=settings.dashscope_api_key,
                temperature=0.1,
            )
        except TypeError:
            llm = Tongyi(
                model_name=model,
                dashscope_api_key=settings.dashscope_api_key,
                temperature=0.1,
            )
        return str(llm.invoke(prompt))
    except Exception:
        logger.exception("Tongyi invocation failed")
        return None


def _invoke_deepseek(messages: list[dict[str, str]]) -> str | None:
    if not settings.deepseek_api_key:
        return None
    try:
        import httpx
    except ImportError:
        return None
    try:
        r = httpx.post(
            f"{settings.deepseek_api_base.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {settings.deepseek_api_key}"},
            json={
                "model": settings.deepseek_model,
                "messages": messages,
                "temperature": 0.1,
                "max_tokens": 512,
            },
            timeout=120.0,
        )
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"]
    except Exception:
        logger.exception("DeepSeek invocation failed")
        return None


def _invoke_ollama(prompt: str) -> str | None:
    if not settings.ollama_base_url or not settings.ollama_model:
        return None
    try:
        import httpx
    except ImportError:
        return None
    try:
        r = httpx.post(
            f"{settings.ollama_base_url.rstrip('/')}/api/generate",
            json={"model": settings.ollama_model, "prompt": prompt, "stream": False},
            timeout=120.0,
        )
        r.raise_for_status()
        return str(r.json().get("response") or "")
    except Exception:
        logger.exception("Ollama invocation failed")
        return None


def _invoke_finance_llm(messages: list[dict[str, str]], prompt_fallback: str) -> str | None:
    """
    主力 DashScope（模型名 dashscope_finance_model）+ 金融人设 → 本地 Qwen-1.8B → 其他 API → None。
    """
    mode = (settings.mafb_llm_mode or "auto").lower().strip()
    messages_aug = _augment_messages_with_finance_persona(messages)
    tongyi_prompt = f"{FINANCE_EXPERT_SYSTEM_PROMPT.strip()}\n\n{prompt_fallback}"

    if mode == "local_only":
        return (
            invoke_local_qwen_finance(messages_aug, tongyi_prompt)
            or _invoke_ollama(tongyi_prompt)
        )

    model = settings.dashscope_finance_model
    raw: str | None = None
    if mode in ("auto", "cloud_only"):
        raw = _invoke_dashscope(messages_aug, model)
    if raw is None and mode in ("auto", "cloud_only"):
        raw = _invoke_tongyi(tongyi_prompt)
    if raw is None and mode in ("auto", "cloud_only"):
        raw = _invoke_deepseek(messages_aug)
    if raw is None and mode in ("auto", "cloud_only"):
        raw = _invoke_ollama(tongyi_prompt)

    # 云端不可用或无 Key：自动切换本地 Qwen-1.8B 系（CPU，无需 API）
    if raw is None and mode == "auto" and settings.local_finance_llm_enabled:
        raw = invoke_local_qwen_finance(messages_aug, tongyi_prompt)
        if raw:
            logger.info("已使用本地 Qwen-1.8B 系权重完成推理（双链路容灾）")

    return raw


def invoke_finance_agent_score(
    agent_key: str,
    agent_role_zh: str,
    fund: dict[str, Any],
    rag_chunks: list[str],
    user_risk: int,
) -> AgentScore | None:
    """
    返回结构化打分；若所有通道不可用或解析失败则返回 None，由调用方走规则引擎。
    agent_key: fundamental | technical | risk
    """
    prompt = _build_score_prompt(agent_role_zh, fund, rag_chunks, user_risk)
    messages = [
        {
            "role": "system",
            "content": "你只输出合法 JSON 对象，键为 agent_name, score, reason。",
        },
        {"role": "user", "content": prompt},
    ]

    raw = _invoke_finance_llm(messages, prompt)
    if raw is None:
        return None

    try:
        score = _parse_agent_score(raw, agent_key)
        if score.agent_name != agent_key:
            score = score.model_copy(update={"agent_name": agent_key})
        return score
    except Exception:
        logger.warning("Failed to parse AgentScore from LLM output: %s", raw[:500])
        return None


def invoke_compliance_llm(text_blob: str, fund_code: str) -> ComplianceLLMResult | None:
    """合规 Agent：大模型辅助审查话术；硬规则在 nodes 中仍优先。"""
    system = (
        "你是基金合规与投教审查助手。只输出 JSON，键为 allow_continue (bool), "
        "compliance_score (-2~2 整数), advisory_notes (字符串)。"
        "不得建议承诺收益或保本。若发现疑似违规营销，设 allow_continue=false。"
    )
    user = f"基金代码：{fund_code}\n待审查文本：\n{text_blob[:4000]}"
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]

    raw = _invoke_finance_llm(messages, user)
    if raw is None:
        return None
    try:
        data = _extract_json_object(raw)
        return ComplianceLLMResult.model_validate(data)
    except Exception:
        logger.warning("Failed to parse ComplianceLLMResult: %s", raw[:500])
        return None
