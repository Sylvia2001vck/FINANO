"""
Finance LLM adapter — 精简容灾：

1. 唯一模型通道：DashScope 通义千问（FINANCE_MODEL_NAME / QWEN_FINANCE_MODEL）
2. 失败/超时：直接回退规则引擎（由 nodes.py 兜底）

不再走 DeepSeek / Ollama / 本地模型链路，便于定位超时根因并降低尾延迟不确定性。
"""

from __future__ import annotations

import concurrent.futures
import contextvars
import json
import logging
import re
import threading
import time
from typing import Any

from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.dashscope_setup import apply_dashscope_settings
from app.agent.runtime_trace import emit_agent_event

logger = logging.getLogger(__name__)
_LLM_CONCURRENCY_GATE = threading.BoundedSemaphore(value=max(1, int(settings.mafb_llm_max_concurrency)))
_MODEL_PRECHECK: dict[str, tuple[float, bool]] = {}
_MODEL_PRECHECK_LOCK = threading.Lock()
_MODEL_PRECHECK_TTL_SEC = 600.0

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


def _raw_preview(text: str, limit: int = 320) -> str:
    s = (text or "").replace("\n", "\\n").replace("\r", "")
    return s[:limit]


def _parse_agent_score(raw: str, expected_name: str) -> AgentScore:
    data = _extract_json_object(raw)
    data.setdefault("agent_name", expected_name)
    if data.get("error") and not data.get("reason"):
        data["reason"] = str(data.get("error"))
    if data.get("score") is None:
        data["score"] = 0
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
        "manager_score",
        "manager_return_annual",
        "stock_top10_concentration",
        "stock_equity_ratio",
        "holding_drift",
        "quarter_samples",
        "momentum_60d",
        "volatility_60d",
        "ema_5",
        "ema_20",
        "ema_60",
        "bias_20",
        "rsi_14",
        "macd_dif",
        "macd_dea",
        "macd_hist",
        "macd_signal",
        "technical_retrieval",
        "technical_summary",
        "risk_summary",
        "news_signals",
        "fee_rate",
    )
    out = {k: fund.get(k) for k in keep if k in fund}
    if not out:
        out = dict(fund or {})
    return out


def _build_score_prompt(
    agent_key: str,
    agent_role: str,
    fund: dict[str, Any],
    rag_chunks: list[str],
    user_risk: int,
    user_profile: dict[str, Any] | None = None,
) -> str:
    rag = "\n".join(f"- {c}" for c in (rag_chunks or [])[:4])
    fund_json = json.dumps(_compact_fund_for_llm(fund), ensure_ascii=False)
    agent = (agent_key or "").strip().lower()
    user_block = ""
    if agent == "profiling":
        up = json.dumps(user_profile or {}, ensure_ascii=False)
        user_block = f"\n用户画像(JSON)：{up}\n用户风险等级(1-5)：{user_risk}"
    metric_hints = {
        "fundamental": "重点评估持仓集中度/风格漂移、经理能力与管理规模，同时结合夏普与回撤；新闻仅作辅助，主要用于识别政策导致的逻辑变动。",
        "technical": "重点评估EMA(5/20/60)、Bias20、RSI14、MACD信号、60日动量与波动率，并结合technical_retrieval中的相似度、历史窗口日期与后续收益统计；不做价格预测。",
        "risk": "重点评估最大回撤、波动率、Sortino、VaR95、持仓集中度、流动性标签与指数相关性；负面舆情仅作辅助放大器，不得覆盖量化主结论。",
        "attribution": "重点评估超额收益来源（选股、风格Beta、风格择时、风险控制）及大盘/小盘、价值/成长、质量风格相似度与偏离度。",
        "profiling": "重点评估用户画像与标的风格适配度，解释错配风险与行为后果。",
    }
    agent_name_scope = "fundamental / technical / risk / attribution / profiling"
    no_user_rule = ""
    if agent in {"fundamental", "technical", "risk", "attribution"}:
        no_user_rule = "\n严禁提及“用户/投资者/画像/适配”等词，只讨论标的本身。"
    return f"""你是公募基金/ETF投研助手，仅基于给定结构化数据做事实性评估，不预测价格，不承诺收益。
角色：{agent_role}
基金事实(JSON)：{fund_json}
RAG检索片段：
{rag}
{user_block}
分析侧重点：{metric_hints.get(agent, "围绕给定事实做可解释打分。")}
{no_user_rule}

请严格输出一个 JSON 对象，键为 agent_name, score, reason。
若任一关键指标缺失或为 0（不适用于 risk_rating），必须改为输出：
{{"agent_name":"{agent}","score":0,"reason":"{{\"error\":\"数据源未就绪\"}}"}}。
score 为整数 -2~+2（-2 强烈负面，+2 强烈正面）。
reason 必须用中文，且按以下四段组织（可用分号连接）：
【核心结论】一句话判断；
【硬事实数据】至少引用 2 个数值（如夏普、回撤、动量、风险评级差）；
【逻辑推演】说明数据如何导致该结论；
【评分标签】根据 agent_name 使用：基本面打分 / 技术面打分 / 风险评分 / 形态评分 / 适配打分。
agent_name 使用英文标识：{agent_name_scope} 之一，且必须与当前角色一致。
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
            err_code = getattr(response, "code", None)
            err_msg = getattr(response, "message", None)
            emit_agent_event(
                "llm_http_error",
                f"DashScope 非200响应：status={code}, code={err_code}, message={err_msg}",
            )
            return None
        choices = getattr(getattr(response, "output", None), "choices", None) or []
        if not choices:
            logger.warning("DashScope empty choices: %s", response)
            emit_agent_event("llm_http_error", "DashScope 返回空 choices")
            return None
        text = _dashscope_extract_assistant_text(choices[0])
        if not (text or "").strip():
            logger.warning("DashScope empty assistant text: %s", response)
            emit_agent_event("llm_http_error", "DashScope assistant text 为空")
            return None
        return text.strip()
    except Exception:
        logger.exception("DashScope 调用失败 — 将尝试本地 Qwen-1.8B 降级")
        emit_agent_event("llm_error", "DashScope 调用抛异常（见后端日志堆栈）")
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


def _resolve_model_for_agent(agent_key: str | None) -> str:
    agent = (agent_key or "").strip().lower()
    model_map = {
        "fundamental": (settings.mafb_model_fundamental or "").strip(),
        "technical": (settings.mafb_model_technical or "").strip(),
        "risk": (settings.mafb_model_risk or "").strip(),
        "profiling": (settings.mafb_model_profiling or "").strip(),
        "attribution": (settings.mafb_model_kline or "").strip(),
        "compliance": (settings.mafb_model_compliance or "").strip(),
    }
    chosen = model_map.get(agent) or ""
    if chosen:
        return chosen
    return settings.dashscope_finance_model


def _invoke_finance_llm(messages: list[dict[str, str]], prompt_fallback: str, *, agent_key: str | None = None) -> str | None:
    """
    仅调用 DashScope 通义千问；失败/超时返回 None，由上层走规则引擎。
    """
    _ = prompt_fallback
    messages_aug = _augment_messages_with_finance_persona(messages)
    cloud_deadline = float(settings.mafb_cloud_primary_timeout_sec)
    handshake_deadline = float(settings.mafb_llm_handshake_timeout_sec)

    def _run_with_timeout(channel: str, fn, *args, timeout_sec: float | None = None):
        t0 = time.monotonic()
        emit_agent_event("llm_channel_start", f"{channel} 开始调用")
        deadline = float(timeout_sec if timeout_sec is not None else cloud_deadline)
        ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            fut = ex.submit(fn, *args)
            try:
                out = fut.result(timeout=deadline)
                dt = time.monotonic() - t0
                emit_agent_event("llm_channel_done", f"{channel} 返回（{dt:.2f}s）")
                return out
            except concurrent.futures.TimeoutError:
                logger.warning("Cloud LLM timed out (%.1fs), fallback next channel", deadline)
                dt = time.monotonic() - t0
                emit_agent_event(
                    "llm_timeout",
                    f"{channel} 超时（deadline={deadline:.1f}s，elapsed={dt:.2f}s），切换降级链路",
                )
                return None
            except Exception as e:  # noqa: BLE001
                dt = time.monotonic() - t0
                emit_agent_event(
                    "llm_error",
                    f"{channel} 异常（{type(e).__name__}: {e}，elapsed={dt:.2f}s），切换降级链路",
                )
                return None
        finally:
            ex.shutdown(wait=False, cancel_futures=True)

    def _cached_model_health(model_name: str) -> bool | None:
        with _MODEL_PRECHECK_LOCK:
            hit = _MODEL_PRECHECK.get(model_name)
            if not hit:
                return None
            ts, ok = hit
            if time.time() - ts > _MODEL_PRECHECK_TTL_SEC:
                return None
            return ok

    def _set_model_health(model_name: str, ok: bool) -> None:
        with _MODEL_PRECHECK_LOCK:
            _MODEL_PRECHECK[model_name] = (time.time(), bool(ok))

    model = _resolve_model_for_agent(agent_key)
    agent = (agent_key or "default").strip().lower()
    fallback_model = (settings.mafb_qwen_fallback_model or "qwen-plus").strip()
    use_model = model

    # qwen3* 仅灰度启用：默认主链路直接使用稳定 fallback 模型
    if "qwen3" in (model or "").lower():
        gray_agents = set(settings.mafb_qwen3_gray_agents)
        allow_qwen3 = bool(settings.mafb_qwen3_gray_enabled) and (agent in gray_agents)
        if not allow_qwen3:
            emit_agent_event("llm_gray_off", f"{agent} 不在 qwen3 灰度名单，主链路使用 {fallback_model}")
            use_model = fallback_model
        else:
            h = _cached_model_health(model)
            if h is None:
                probe_msgs = [{"role": "system", "content": "你是助手"}, {"role": "user", "content": "回复 OK"}]
                probe = _run_with_timeout(
                    "DashScopeHandshake",
                    _invoke_dashscope,
                    probe_msgs,
                    model,
                    timeout_sec=handshake_deadline,
                )
                ok = bool(probe)
                _set_model_health(model, ok)
                if not ok:
                    emit_agent_event("llm_handshake_fail", f"{agent} 的 {model} 预检失败，自动切换 {fallback_model}")
                    use_model = fallback_model
            elif h is False:
                emit_agent_event("llm_handshake_fail", f"{agent} 的 {model} 最近预检失败，自动切换 {fallback_model}")
                use_model = fallback_model

    emit_agent_event("llm_try", f"尝试 DashScope：agent={agent}, model={use_model}")
    raw = _run_with_timeout("DashScope", _invoke_dashscope, messages_aug, use_model)
    if raw is None:
        emit_agent_event("llm_fallback", "Qwen 未返回，交由规则引擎兜底")
    else:
        emit_agent_event("llm_raw", f"Qwen原始返回片段：{_raw_preview(raw, 520)}")
    return raw


def invoke_finance_agent_score(
    agent_key: str,
    agent_role_zh: str,
    fund: dict[str, Any],
    rag_chunks: list[str],
    user_risk: int,
    *,
    llm_deadline_sec: float | None = None,
    user_profile: dict[str, Any] | None = None,
) -> AgentScore | None:
    """
    返回结构化打分；若所有通道不可用或解析失败则返回 None，由调用方走规则引擎。
    agent_key: fundamental | technical | risk | attribution | profiling

    llm_deadline_sec：单次 LLM 链路上限（秒）；None 时用 settings.mafb_agent_llm_timeout_sec；≤0 表示不限制。
    """
    prompt = _build_score_prompt(agent_key, agent_role_zh, fund, rag_chunks, user_risk, user_profile)
    emit_agent_event("agent_start", f"{agent_key} 开始 LLM 打分")
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
            emit_agent_event("agent_queue", f"{agent_key} 在并发闸门排队 {gate_wait:.2f}s")

        if deadline and deadline > 0:
            ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            try:
                # 传播 task runtime trace 上下文到子线程，确保 llm_try/timeout/raw 等事件可回传前端
                ctx = contextvars.copy_context()
                fut = ex.submit(ctx.run, _invoke_finance_llm, messages, prompt, agent_key=agent_key)
                try:
                    raw = fut.result(timeout=float(deadline))
                except concurrent.futures.TimeoutError:
                    logger.warning("Finance LLM 打分超时（%ss，agent=%s），将走规则引擎", deadline, agent_key)
                    emit_agent_event("agent_timeout", f"{agent_key} 超时（{deadline}s），切换规则引擎")
                    raw = None
            finally:
                ex.shutdown(wait=False, cancel_futures=True)
        else:
            raw = _invoke_finance_llm(messages, prompt, agent_key=agent_key)
    finally:
        _LLM_CONCURRENCY_GATE.release()

    if raw is None:
        emit_agent_event("agent_fallback", f"{agent_key} 使用规则引擎")
        return None

    try:
        score = _parse_agent_score(raw, agent_key)
        if score.agent_name != agent_key:
            score = score.model_copy(update={"agent_name": agent_key})
        emit_agent_event("agent_done", f"{agent_key} LLM 打分完成：score={score.score}")
        emit_agent_event(
            "agent_json_ok",
            f"{agent_key} JSON解析成功：agent_name={score.agent_name}, score={score.score}",
        )
        return score
    except Exception:
        logger.warning("Failed to parse AgentScore from LLM output: %s", raw[:500])
        emit_agent_event(
            "agent_parse_fail",
            f"{agent_key} 输出解析失败，切换规则引擎；raw_preview={_raw_preview(raw)}",
        )
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

    raw = _invoke_finance_llm(messages, user, agent_key="compliance")
    if raw is None:
        return None
    try:
        data = _extract_json_object(raw)
        return ComplianceLLMResult.model_validate(data)
    except Exception:
        logger.warning("Failed to parse ComplianceLLMResult: %s", raw[:500])
        return None


def probe_qwen_llm(prompt: str, *, model: str | None = None, timeout_sec: float = 10.0) -> dict[str, Any]:
    """
    调试探针：仅测试 Qwen 通道可用性与返回格式，不走业务图逻辑。
    返回耗时、HTTP状态、错误码/消息、raw 片段，便于快速定位模型路由问题。
    """
    use_model = (model or "").strip() or settings.dashscope_finance_model
    msgs = [
        {"role": "system", "content": "你是金融助手。尽量简短回答。"},
        {"role": "user", "content": prompt},
    ]
    out: dict[str, Any] = {
        "ok": False,
        "channel": "dashscope",
        "model": use_model,
        "elapsed_sec": 0.0,
        "status_code": None,
        "code": None,
        "message": None,
        "raw": None,
    }

    if not settings.dashscope_api_key:
        out["message"] = "missing DASHSCOPE_API_KEY"
        return out
    try:
        import dashscope
    except ImportError:
        out["message"] = "dashscope package not installed"
        return out

    apply_dashscope_settings(dashscope)
    api_key = (settings.dashscope_api_key or "").strip()
    t0 = time.monotonic()
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        def _call():
            if _dashscope_model_uses_multimodal_api(use_model):
                from dashscope import MultiModalConversation

                mm_messages = _dashscope_messages_to_multimodal(msgs)
                return MultiModalConversation.call(
                    api_key=api_key,
                    model=use_model,
                    messages=mm_messages,
                    result_format="message",
                    temperature=0.1,
                    max_tokens=256,
                )
            return dashscope.Generation.call(
                api_key=api_key,
                model=use_model,
                messages=msgs,
                result_format="message",
                temperature=0.1,
                max_tokens=256,
            )

        fut = ex.submit(_call)
        try:
            resp = fut.result(timeout=float(timeout_sec))
        except concurrent.futures.TimeoutError:
            out["elapsed_sec"] = round(time.monotonic() - t0, 3)
            out["message"] = f"timeout after {timeout_sec:.1f}s"
            return out

        out["elapsed_sec"] = round(time.monotonic() - t0, 3)
        status = getattr(resp, "status_code", None)
        out["status_code"] = status
        out["code"] = getattr(resp, "code", None)
        out["message"] = getattr(resp, "message", None)
        choices = getattr(getattr(resp, "output", None), "choices", None) or []
        if choices:
            text = _dashscope_extract_assistant_text(choices[0]).strip()
            out["raw"] = text[:2000]
        out["ok"] = bool(status == 200 and out.get("raw"))
        return out
    except Exception as e:  # noqa: BLE001
        out["elapsed_sec"] = round(time.monotonic() - t0, 3)
        out["message"] = f"{type(e).__name__}: {e}"
        return out
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
