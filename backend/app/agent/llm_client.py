"""
Finance LLM adapter — 双链路容灾：

1. 主力：阿里云 DashScope 通义千问（模型名由 FINANCE_MODEL_NAME / QWEN_FINANCE_MODEL 配置）
   + 统一「金融专家」系统人设（通用强模型 + 专业 Prompt ≈ 金融垂直助手，无需单独 qwen-finance SKU）
2. 降级：DeepSeek、Ollama（与 DashScope 不同密钥/通道）
3. 再降级：本地开源 Qwen-1.8B 系 CPU 推理（见 local_qwen.py）
4. 再失败：由 nodes 规则引擎兜底，演示不翻车

说明：不再链接 LangChain Tongyi 作为 DashScope 后的回退——二者共用同一 API Key，
无效密钥时会重复 401 且 tenacity 打出冗长堆栈。

Qwen3 等多模态模型须走 **MultiModalConversation**（multimodal-generation）；纯文本模型仍用 **Generation**。
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import re
import threading
import time
from typing import Any

from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.dashscope_setup import apply_dashscope_settings
from app.agent.local_qwen import invoke_local_qwen_finance

logger = logging.getLogger(__name__)
_LLM_CONCURRENCY_GATE = threading.BoundedSemaphore(value=max(1, int(settings.mafb_llm_max_concurrency)))

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


def _compact_fund_for_llm(fund: dict[str, Any]) -> dict[str, Any]:
    """
    仅保留打分必要字段，减少提示词体积与模型首包延迟。
    """
    keep = (
        "code",
        "name",
        "track",
        "risk_rating",
        "aum_billion",
        "sharpe_3y",
        "max_drawdown_3y",
        "momentum_60d",
        "volatility_60d",
        "fee_rate",
    )
    out = {k: fund.get(k) for k in keep if k in fund}
    if not out:
        out = dict(fund or {})
    return out


def _build_score_prompt(agent_role: str, fund: dict[str, Any], rag_chunks: list[str], user_risk: int) -> str:
    rag = "\n".join(f"- {c}" for c in (rag_chunks or [])[:4])
    fund_json = json.dumps(_compact_fund_for_llm(fund), ensure_ascii=False)
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


def _dashscope_model_uses_multimodal_api(model: str) -> bool:
    """与百炼文档一致：Qwen3 / VL / QVQ 等走 multimodal-generation，不能只用纯文本 Generation。"""
    m = (model or "").strip().lower()
    if not m:
        return False
    if "-vl" in m or m.startswith("qvq"):
        return True
    if "qwen3" in m:
        return True
    return False


def _dashscope_messages_to_multimodal(messages: list[dict[str, str]]) -> list[dict[str, Any]]:
    """MultiModalConversation：每条 content 为 [{\"text\": \"...\"}, ...]。"""
    out: list[dict[str, Any]] = []
    for m in messages:
        role = str(m.get("role") or "user")
        raw = m.get("content", "")
        if isinstance(raw, list):
            out.append({"role": role, "content": raw})
            continue
        text = "" if raw is None else str(raw)
        out.append({"role": role, "content": [{"text": text}]})
    return out


def _dashscope_extract_assistant_text(choice: Any) -> str:
    """兼容 Generation 与 MultiModalConversation 的 choices[0].message.content。"""
    msg = getattr(choice, "message", None)
    if msg is None:
        return ""
    content = getattr(msg, "content", None)
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for p in content:
            if isinstance(p, dict) and p.get("text") is not None:
                parts.append(str(p["text"]))
            elif isinstance(p, str):
                parts.append(p)
        return "".join(parts)
    if isinstance(content, dict):
        t = content.get("text")
        if t is not None:
            return str(t)
        return json.dumps(content, ensure_ascii=False)
    return str(content)


def _invoke_dashscope(messages: list[dict[str, str]], model: str) -> str | None:
    if not settings.dashscope_api_key:
        return None
    try:
        import dashscope
    except ImportError:
        return None
    apply_dashscope_settings(dashscope)
    api_key = (settings.dashscope_api_key or "").strip()
    try:
        if _dashscope_model_uses_multimodal_api(model):
            from dashscope import MultiModalConversation

            mm_messages = _dashscope_messages_to_multimodal(messages)
            response = MultiModalConversation.call(
                api_key=api_key,
                model=model,
                messages=mm_messages,
                result_format="message",
                temperature=0.1,
                max_tokens=512,
            )
        else:
            response = dashscope.Generation.call(
                api_key=api_key,
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
        text = _dashscope_extract_assistant_text(choices[0])
        if not (text or "").strip():
            logger.warning("DashScope empty assistant text: %s", response)
            return None
        return text.strip()
    except Exception:
        logger.exception("DashScope 调用失败 — 将尝试本地 Qwen-1.8B 降级")
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
            timeout=min(28.0, max(8.0, float(settings.mafb_agent_llm_timeout_sec))),
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
            timeout=min(28.0, max(8.0, float(settings.mafb_agent_llm_timeout_sec))),
        )
        r.raise_for_status()
        return str(r.json().get("response") or "")
    except Exception:
        logger.exception("Ollama invocation failed")
        return None


def _invoke_finance_llm(messages: list[dict[str, str]], prompt_fallback: str) -> str | None:
    """
    DashScope（dashscope_finance_model）→ DeepSeek → Ollama → 本地 Qwen-1.8B；均失败则 None。
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
    *,
    llm_deadline_sec: float | None = None,
) -> AgentScore | None:
    """
    返回结构化打分；若所有通道不可用或解析失败则返回 None，由调用方走规则引擎。
    agent_key: fundamental | technical | risk

    llm_deadline_sec：单次 LLM 链路上限（秒）；None 时用 settings.mafb_agent_llm_timeout_sec；≤0 表示不限制。
    """
    prompt = _build_score_prompt(agent_role_zh, fund, rag_chunks, user_risk)
    messages = [
        {
            "role": "system",
            "content": "你只输出合法 JSON 对象，键为 agent_name, score, reason。",
        },
        {"role": "user", "content": prompt},
    ]

    deadline = settings.mafb_agent_llm_timeout_sec if llm_deadline_sec is None else llm_deadline_sec
    gate_enter_t0 = time.monotonic()
    _LLM_CONCURRENCY_GATE.acquire()
    gate_wait = time.monotonic() - gate_enter_t0
    try:
        if gate_wait > 0.2:
            logger.info("Finance LLM 并发闸门等待 %.2fs（agent=%s）", gate_wait, agent_key)

        if deadline and deadline > 0:
            ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            try:
                fut = ex.submit(_invoke_finance_llm, messages, prompt)
                try:
                    raw = fut.result(timeout=float(deadline))
                except concurrent.futures.TimeoutError:
                    logger.warning("Finance LLM 打分超时（%ss，agent=%s），将走规则引擎", deadline, agent_key)
                    raw = None
            finally:
                ex.shutdown(wait=False, cancel_futures=True)
        else:
            raw = _invoke_finance_llm(messages, prompt)
    finally:
        _LLM_CONCURRENCY_GATE.release()

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
