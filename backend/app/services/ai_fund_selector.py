"""FBTI + 五行：多阶段选股（偏好 JSON → 随机 400 → 规则 Top20 → 大模型 Top5），失败则规则兜底。"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.agent import llm_client as _llm  # noqa: PLC2701
from app.agent.fund_catalog import get_fund_by_code, list_funds_catalog_sample
from app.core.config import settings

logger = logging.getLogger(__name__)

_FBTI_SAMPLE_POOL = 400
_FBTI_RANK_TOP = 20
_FBTI_PROMPT_MAX_FUNDS = 20

_STRATEGY_LIBRARY = {
    "factors": ["value", "growth", "momentum", "low_volatility", "quality", "size", "dividend"],
    "alpha_models": ["multi_factor", "sector_rotation", "trend_follow", "defensive_barbell", "risk_parity"],
}

# 规则兜底时名称含以下片段的基金每种片段最多选一只，避免 Top20 里同主题挤满 5 只。
_NAME_DIVERSITY_FRAGMENTS = (
    "价值成长",
    "沪港深",
    "稳健增长",
    "科技创新",
    "消费主题",
)


def _thin_fund_for_fbti_prompt(row: dict[str, Any]) -> dict[str, Any]:
    """去掉长 doc 等，避免单次请求撑爆上下文（全市场模式下尤其明显）。"""
    return {
        "code": row.get("code"),
        "name": row.get("name"),
        "type": row.get("type"),
        "track": row.get("track"),
        "risk_rating": row.get("risk_rating"),
        "sharpe_3y": row.get("sharpe_3y"),
        "max_drawdown_3y": row.get("max_drawdown_3y"),
        "momentum_60d": row.get("momentum_60d"),
        "aum_billion": row.get("aum_billion"),
    }


def _use_eastmoney_catalog() -> bool:
    return (settings.fund_catalog_mode or "static").strip().lower() == "eastmoney_full"


def _extract_json(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        return json.loads(m.group())
    except json.JSONDecodeError:
        return None


def _cloud_configured() -> bool:
    return bool(
        (settings.dashscope_api_key or "").strip()
        or (settings.deepseek_api_key or "").strip()
        or ((settings.ollama_base_url or "").strip() and (settings.ollama_model or "").strip())
    )


def _invoke_json_llm(
    system: str,
    user: str,
    *,
    require_funds: bool = True,
) -> tuple[dict[str, Any] | None, str]:
    """
    返回 (解析后的 JSON 或 None, 原因码)。
    原因码：ok | no_llm_response | llm_exception | not_json | no_funds_key
    """
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    try:
        raw = _llm._invoke_finance_llm(messages, user)
    except Exception:
        logger.exception("FBTI AI 选股：_invoke_finance_llm 异常")
        return None, "llm_exception"
    if not raw:
        return None, "no_llm_response"
    parsed = _extract_json(raw)
    if not parsed:
        logger.warning("FBTI AI 选股：模型返回中未解析出 JSON（前 200 字）：%s", (raw or "")[:200])
        return None, "not_json"
    if require_funds and not isinstance(parsed.get("funds"), list):
        logger.warning("FBTI AI 选股：JSON 缺少 funds 数组")
        return None, "no_funds_key"
    return parsed, "ok"


def _default_preferences_from_arch(arch: dict[str, Any], wuxing: str) -> dict[str, Any]:
    """LLM 未返回可用偏好时的确定性默认（与人格标签、五行一致）。"""
    tags = list(arch.get("tags") or [])
    tag_s = " ".join(tags)
    risky = "激进" in tag_s
    steady = "稳健" in tag_s
    risk_pref = "high" if risky and not steady else "low" if steady and not risky else "medium"
    preferred: list[str] = []
    wx = wuxing or str(arch.get("wuxing") or "")
    if "金" in wx or "土" in wx:
        preferred.extend(["宽基", "价值", "债", "红利"])
    if "木" in wx or "水" in wx:
        preferred.extend(["成长", "科技", "创新"])
    if "火" in wx:
        preferred.extend(["主题", "行业", "新能源"])
    return {
        "summary": f"按人格标签「{tag_s or '—'}」与五行「{wx or '—'}」做演示向量化偏好。",
        "risk_preference": risk_pref,
        "preferred_tracks": preferred[:5],
        "avoid_tracks": [],
        "prefer_etf": None,
        "emphasize_sharpe": steady,
        "emphasize_low_drawdown": steady,
        "emphasize_momentum": risky,
    }


def _default_intent_from_arch(
    arch: dict[str, Any],
    wuxing: str,
    natural_intent: str = "",
    mood: str = "",
) -> dict[str, Any]:
    wx = str(wuxing or arch.get("wuxing") or "")
    sectors: list[str] = []
    if "火" in wx:
        sectors.extend(["半导体", "通信", "人工智能"])
    if "水" in wx:
        sectors.extend(["交通物流", "红利低波"])
    if "木" in wx:
        sectors.extend(["医药", "消费成长"])
    if "金" in wx:
        sectors.extend(["价值红利", "宽基"])
    if "土" in wx:
        sectors.extend(["宽基", "央国企"])
    if not sectors:
        sectors = ["宽基", "行业轮动"]
    style = "High Alpha / Momentum" if ("激进" in mood or "冲" in natural_intent) else "Balanced Multi-Factor"
    return {
        "intent": natural_intent.strip() or "结合金融人格与五行偏好的娱乐向选基",
        "mapped_sectors": sectors[:4],
        "strategy_style": style,
        "risk_tolerance": "Aggressive" if style.startswith("High") else "Balanced",
        "confidence": 0.55,
        "explain": [f"五行={wx or '未知'}", f"情绪={mood or '中性'}"],
    }


def infer_metaphysics_finance_intent_with_ai(
    *,
    fbti_code: str,
    fbti_name: str,
    wuxing: str,
    time_label: str,
    arch: dict[str, Any],
    natural_intent: str = "",
    mood: str = "",
) -> tuple[dict[str, Any], str]:
    system = (
        "你是玄学到金融策略翻译器。仅输出一个合法 JSON："
        "intent(字符串), mapped_sectors(字符串数组), strategy_style(字符串), risk_tolerance(字符串), "
        "confidence(0~1 数字), explain(字符串数组)。不得承诺收益。"
    )
    user = f"""用户金融人格：{fbti_code}（{fbti_name}）
五行偏好：{wuxing}
当前时间：{time_label}
人格标签：{json.dumps(list(arch.get('tags') or []), ensure_ascii=False)}
用户自然语言意图：{natural_intent or "（未提供）"}
用户当前情绪：{mood or "（未提供）"}
请把“玄学/情绪描述”翻译成金融可执行意图 JSON。"""
    parsed, why = _invoke_json_llm(system, user, require_funds=False)
    if parsed is None or why != "ok":
        return _default_intent_from_arch(arch, wuxing, natural_intent, mood), why
    out = {
        "intent": str(parsed.get("intent") or "").strip() or (natural_intent.strip() or "娱乐向选基"),
        "mapped_sectors": list(parsed.get("mapped_sectors") or [])[:6],
        "strategy_style": str(parsed.get("strategy_style") or "Balanced Multi-Factor"),
        "risk_tolerance": str(parsed.get("risk_tolerance") or "Balanced"),
        "confidence": float(parsed.get("confidence") or 0.6),
        "explain": list(parsed.get("explain") or [])[:6],
    }
    if not out["mapped_sectors"]:
        out["mapped_sectors"] = _default_intent_from_arch(arch, wuxing)["mapped_sectors"]
    out["confidence"] = max(0.0, min(1.0, out["confidence"]))
    return out, "ok"


def infer_strategy_bundle_with_ai(intent_payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
    system = (
        "你是策略调度器。只输出合法 JSON：factors(数组), alpha_models(数组), "
        "weights(对象，键为 factor，值为 0~1), rationale(字符串)。"
        "factors 必须从给定白名单中选择。"
    )
    user = f"""金融意图：
{json.dumps(intent_payload, ensure_ascii=False)}
策略白名单：
{json.dumps(_STRATEGY_LIBRARY, ensure_ascii=False)}
请给出 3~5 个因子与 1~2 个 alpha 模型，并给出可解释原因。"""
    parsed, why = _invoke_json_llm(system, user, require_funds=False)
    if parsed is None or why != "ok":
        sectors = list(intent_payload.get("mapped_sectors") or [])
        factors = ["momentum", "growth"] if any("半导体" in str(x) or "科技" in str(x) for x in sectors) else ["value", "quality"]
        return {
            "factors": factors,
            "alpha_models": ["multi_factor", "sector_rotation"],
            "weights": {factors[0]: 0.55, factors[1]: 0.45 if len(factors) > 1 else 0.35},
            "rationale": "按意图关键词回退到规则策略组合。",
        }, why
    factors = [f for f in list(parsed.get("factors") or []) if f in _STRATEGY_LIBRARY["factors"]][:5]
    if not factors:
        factors = ["momentum", "growth"]
    alphas = [m for m in list(parsed.get("alpha_models") or []) if m in _STRATEGY_LIBRARY["alpha_models"]][:2] or ["multi_factor"]
    weights_raw = parsed.get("weights") if isinstance(parsed.get("weights"), dict) else {}
    weights = {k: float(v) for k, v in weights_raw.items() if k in factors and isinstance(v, (int, float))}
    if not weights:
        p = round(1.0 / len(factors), 3)
        weights = {k: p for k in factors}
    return {
        "factors": factors,
        "alpha_models": alphas,
        "weights": weights,
        "rationale": str(parsed.get("rationale") or "基于意图做因子与策略匹配。"),
    }, "ok"


def infer_selection_preferences_with_ai(
    *,
    fbti_code: str,
    fbti_name: str,
    wuxing: str,
    time_label: str,
    arch: dict[str, Any],
    natural_intent: str = "",
    mood: str = "",
    intent_payload: dict[str, Any] | None = None,
    strategy_bundle: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str]:
    """
    阶段一：仅从人格与五行推断结构化偏好（不附带基金列表，控制 token）。
    返回 (preferences_dict, why)；why 非 ok 时调用方应使用 _default_preferences_from_arch。
    """
    tags = arch.get("tags") or []
    blurb = str(arch.get("blurb") or "")
    system = (
        "你只输出一个合法 JSON 对象，不要 Markdown。键必须包含："
        "summary（字符串，≤100 字，中性描述选股倾向）、"
        "risk_preference（字符串，仅允许 low|medium|high）、"
        "preferred_tracks（字符串数组，0~6 个中文赛道/风格关键词）、"
        "avoid_tracks（字符串数组，可为空）、"
        "prefer_etf（布尔或 null，null 表示不强调）、"
        "emphasize_sharpe（布尔）、emphasize_low_drawdown（布尔）、emphasize_momentum（布尔）。"
        "不得承诺收益；基于金融人格与五行做推断。"
    )
    user = f"""金融人格代码：{fbti_code}，名称：{fbti_name}。
五行偏好：{wuxing}。
参考时间：{time_label}。
人格标签：{json.dumps(tags, ensure_ascii=False)}
人格简介：{blurb}
用户自然语言：{natural_intent or "（无）"}
用户情绪：{mood or "（无）"}
意图翻译层输出：{json.dumps(intent_payload or {}, ensure_ascii=False)}
策略匹配层输出：{json.dumps(strategy_bundle or {}, ensure_ascii=False)}
请输出上述 JSON。"""
    parsed, why = _invoke_json_llm(system, user, require_funds=False)
    if parsed is None or why != "ok":
        return _default_preferences_from_arch(arch, wuxing), why
    # 轻量归一化，避免缺键导致打分异常
    out: dict[str, Any] = {
        "summary": str(parsed.get("summary") or "").strip() or "（模型未给摘要）",
        "risk_preference": str(parsed.get("risk_preference") or "medium").lower().strip(),
        "preferred_tracks": list(parsed.get("preferred_tracks") or [])[:8],
        "avoid_tracks": list(parsed.get("avoid_tracks") or [])[:8],
        "prefer_etf": parsed.get("prefer_etf"),
        "emphasize_sharpe": bool(parsed.get("emphasize_sharpe")),
        "emphasize_low_drawdown": bool(parsed.get("emphasize_low_drawdown")),
        "emphasize_momentum": bool(parsed.get("emphasize_momentum")),
    }
    if out["risk_preference"] not in ("low", "medium", "high"):
        out["risk_preference"] = "medium"
    return out, "ok"


def _score_fund_for_preferences(row: dict[str, Any], prefs: dict[str, Any], wuxing: str) -> float:
    track = str(row.get("track") or "").lower()
    name = str(row.get("name") or "").lower()
    blob = track + name
    score = 0.0
    for kw in prefs.get("preferred_tracks") or []:
        k = str(kw).strip().lower()
        if k and k in blob:
            score += 2.2
    for kw in prefs.get("avoid_tracks") or []:
        k = str(kw).strip().lower()
        if k and k in blob:
            score -= 3.0
    risk_pref = str(prefs.get("risk_preference") or "medium").lower()
    rr = float(row.get("risk_rating") or 3)
    if risk_pref == "low":
        score += max(0.0, 5.5 - rr) * 0.9
    elif risk_pref == "high":
        score += max(0.0, rr - 2.0) * 0.85
    else:
        score -= abs(rr - 3.0) * 0.15
    pe = prefs.get("prefer_etf")
    if pe is True:
        if "etf" in str(row.get("type") or "").lower() or "etf" in name:
            score += 1.4
    elif pe is False:
        if "etf" not in str(row.get("type") or "").lower() and "etf" not in name:
            score += 0.4
    sharpe = float(row.get("sharpe_3y") or 0.0)
    dd = float(row.get("max_drawdown_3y") or 0.35)
    mom = float(row.get("momentum_60d") or 0.0)
    if prefs.get("emphasize_sharpe"):
        score += sharpe * 2.0
    if prefs.get("emphasize_low_drawdown"):
        score -= dd * 1.6
    if prefs.get("emphasize_momentum"):
        score += mom * 2.8
    wx = (wuxing or "").lower()
    if "金" in wx:
        if any(x in blob for x in ("固收", "债", "货币", "稳健", "红利", "价值")):
            score += 1.0
    if "木" in wx or "水" in wx:
        if any(x in blob for x in ("科技", "成长", "创新", "医药", "消费")):
            score += 0.85
    if "火" in wx:
        if any(x in blob for x in ("主题", "行业", "新能源", "芯片", "军工")):
            score += 0.85
    if "土" in wx:
        if any(x in blob for x in ("宽基", "300", "50", "中证", "指数")):
            score += 0.85
    return score


def _sample_and_rank_top_pool(
    prefs: dict[str, Any],
    wuxing: str,
) -> tuple[list[dict[str, Any]], int, int]:
    """随机 400（或池子不足时取全量）→ 打分 → Top20 瘦身行。"""
    sampled, pool_size, seed_used = list_funds_catalog_sample(limit=_FBTI_SAMPLE_POOL)
    thin = [_thin_fund_for_fbti_prompt(dict(r)) for r in sampled]
    thin.sort(key=lambda r: _score_fund_for_preferences(r, prefs, wuxing), reverse=True)
    top = thin[:_FBTI_RANK_TOP]
    return top, pool_size, seed_used


def _pick_diverse_fallback_funds(snap: list[dict[str, Any]], k: int = 5) -> list[dict[str, Any]]:
    """在已按分数排序的候选上尽量分散名称主题，不足 k 再顺序补齐。"""
    if len(snap) <= k:
        return list(snap)
    picked: list[dict[str, Any]] = []
    used_frag: set[str] = set()
    for row in snap:
        if len(picked) >= k:
            break
        name = str(row.get("name") or "")
        frag_hit = next((f for f in _NAME_DIVERSITY_FRAGMENTS if f in name), None)
        if frag_hit and frag_hit in used_frag:
            continue
        if frag_hit:
            used_frag.add(frag_hit)
        picked.append(row)
    codes = {str(p.get("code")) for p in picked}
    i = 0
    while len(picked) < k and i < len(snap):
        c = str(snap[i].get("code") or "")
        if c and c not in codes:
            picked.append(snap[i])
            codes.add(c)
        i += 1
    return picked[:k]


def _merge_live_quotes_if_applicable(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not (settings.fund_live_quote_enabled and not _use_eastmoney_catalog()):
        return rows
    merged: list[dict[str, Any]] = []
    for row in rows:
        full = get_fund_by_code(str(row["code"]), include_live=None)
        if not full:
            merged.append(row)
            continue
        x = dict(row)
        if full.get("live_quote"):
            x["live_quote"] = full["live_quote"]
        merged.append(x)
    return merged


def select_funds_with_ai(
    *,
    fbti_code: str,
    fbti_name: str,
    wuxing: str,
    time_label: str,
    fund_snapshot: list[dict[str, Any]],
    rules_summary: str = "",
    compact_user_reason: bool = False,
) -> dict[str, Any]:
    """
    阶段三：仅对 Top20 瘦身快照调用大模型，输出最多 5 只。
    返回 { "reason": str, "funds": [ { code, name, wuxing_tag, change_hint, ... } ] }
    """
    snap = fund_snapshot[:_FBTI_PROMPT_MAX_FUNDS]
    snap_json = json.dumps(snap, ensure_ascii=False)
    rules_block = (rules_summary or "").strip()
    if rules_block:
        rules_block = f"AI 归纳的选股偏好摘要：{rules_block}\n"
    system = (
        "你只输出一个合法 JSON 对象，键为 reason（字符串）与 funds（数组）。"
        "funds 每项含：code,name,wuxing_tag,change_hint（字符串，可写估值涨跌概况或「见行情」）。"
        "不得承诺收益；从给定快照中优选不超过 5 只；理由需中性合规。"
    )
    user = f"""用户金融人格：{fbti_code}（{fbti_name}），五行偏好：{wuxing}，参考时辰：{time_label}
{rules_block}筛选规则（演示）：
1）匹配人格风险与周期风格；2）五行对应：金=稳健/价值、木=成长、水=科技均衡、火=热点弹性、土=宽基核心；
3）结合下列基金快照（已按规则从随机大样本中预筛的候选，含可选 live_quote）优选不超过 5 只。

基金快照（至多 {_FBTI_RANK_TOP} 条）：
{snap_json}
"""
    parsed, why = _invoke_json_llm(system, user, require_funds=True)
    if parsed is not None and why == "ok":
        return parsed

    logger.info("FBTI AI selector fallback to rule-based list (why=%s)", why)
    funds = _pick_diverse_fallback_funds(snap, k=5)
    has_ds = bool((settings.dashscope_api_key or "").strip())
    mode = (settings.mafb_llm_mode or "auto").lower().strip()
    model_hint = (settings.finance_model_name or settings.qwen_finance_model or "").strip() or "（未设置）"
    mode_hint = (settings.mafb_llm_mode or "auto").strip()

    if compact_user_reason:
        if why == "no_llm_response" and mode == "local_only":
            reason_txt = (
                f"末段模型无输出（MAFB_LLM_MODE=local_only）。已用人格「{fbti_code}」规则列出 5 只；"
                "请确认本机已装 torch 且 LOCAL_FINANCE_LLM_ENABLED=true。"
            )
        elif why == "no_llm_response" and not _cloud_configured():
            reason_txt = (
                f"未配置可用云端 Key。已用人格「{fbti_code}」规则列出 5 只；"
                "请在运行 uvicorn 所用目录的 backend/.env 中设置 DASHSCOPE_API_KEY 等。"
            )
        elif why == "no_llm_response" and _cloud_configured():
            reason_txt = (
                f"末段模型未返回可用内容，已用人格「{fbti_code}」规则列出 5 只占位。"
                f"请核对 backend/.env 密钥、模型名「{model_hint}」是否在百炼开通，并查看额度与网络。"
            )
            logger.warning(
                "FBTI 终筛 no_llm_response（compact 文案已展示）；model=%s mode=%s",
                model_hint,
                mode_hint,
            )
        elif why in ("not_json", "no_funds_key"):
            reason_txt = (
                f"末段返回非合法 JSON 或缺少 funds。已用人格「{fbti_code}」规则列出 5 只；可尝试更换 FINANCE_MODEL_NAME。"
            )
        elif why == "llm_exception":
            reason_txt = f"末段调用异常，已用人格「{fbti_code}」规则列出 5 只；详情见后端日志。"
        else:
            reason_txt = (
                f"末段语义筛选未生效，已用人格「{fbti_code}」规则列出 5 只。"
                + ("" if has_ds else " 请配置 DASHSCOPE_API_KEY 等后重试。")
            )
    elif why == "no_llm_response" and mode == "local_only":
        reason_txt = (
            f"当前为 MAFB_LLM_MODE=local_only，但本地模型未返回内容（是否已安装 torch 与 "
            f"requirements-optional-local-llm，且 LOCAL_FINANCE_LLM_ENABLED=true）。"
            f"已按预筛候选与人格「{fbti_code}」做规则占位。"
        )
    elif why == "no_llm_response" and not _cloud_configured():
        reason_txt = (
            "未检测到可用的云端 API（请在启动 uvicorn 时的当前目录下的 backend/.env 中设置 "
            "DASHSCOPE_API_KEY 或 DEEPSEEK_API_KEY；WSL 直跑时与仓库根目录 .env 不是同一份）。"
            f"已按预筛候选与人格「{fbti_code}」做规则占位。"
        )
    elif why == "no_llm_response" and _cloud_configured():
        reason_txt = (
            "已配置云端/扩展通道，但本次大模型未返回可用内容，已按预筛候选与人格「"
            f"{fbti_code}」用规则列出占位结果。"
            "常见原因与处理："
            f"① DashScope 报 401 / InvalidApiKey：在启动 uvicorn 时的 **backend/.env** 中更换有效的 `DASHSCOPE_API_KEY`（与仓库根目录 `.env` 不是同一份）。"
            f"② 模型名与账号不匹配：当前 `FINANCE_MODEL_NAME`/`QWEN_FINANCE_MODEL` 为「{model_hint}」，请在阿里云百炼控制台核对该模型是否已开通。"
            f"③ 当前 `MAFB_LLM_MODE={mode_hint}`；若为 `local_only` 需本机已装 torch 且能加载 `LOCAL_FINANCE_MODEL_ID`。"
            "④ 额度用尽或网络超时：稍后重试或换通道。"
            "⑤ 若仅「FBTI 一键选股」失败：可查看终端日志。"
        )
    elif why in ("not_json", "no_funds_key"):
        reason_txt = (
            f"模型已返回内容，但不是合法 JSON 或缺少 `funds` 数组，无法用于选股展示。"
            f"已按预筛候选与人格「{fbti_code}」做规则占位；可尝试调整提示或更换 `FINANCE_MODEL_NAME`。"
        )
    elif why == "llm_exception":
        reason_txt = (
            f"调用大模型时发生异常，已按预筛候选与人格「{fbti_code}」做规则占位；请查看后端日志。"
        )
    else:
        reason_txt = (
            f"云端语义筛选未生效，已按预筛候选与人格「{fbti_code}」做规则占位。"
            + ("" if has_ds else " 配置 `DASHSCOPE_API_KEY`（或其它已支持通道）后重试。")
        )

    return {
        "reason": reason_txt,
        "funds": [
            {
                "code": str(f.get("code")),
                "name": str(f.get("name")),
                "wuxing_tag": wuxing[:2] if wuxing else "土",
                "change_hint": str((f.get("live_quote") or {}).get("gszzl") or "—"),
            }
            for f in funds
        ],
    }


def iter_fbti_ai_selection_sse_events(
    *,
    fbti_code: str,
    fbti_name: str,
    wuxing: str,
    time_label: str,
    arch: dict[str, Any],
    natural_intent: str = "",
    mood: str = "",
):
    """同步生成器：依次 yield 阶段 dict，最后 yield 与 run_fbti_ai_selection 相同结构的 result dict。"""
    yield {"event": "stage", "node": "intent", "label": "玄学语义 -> 金融意图翻译…"}
    intent_payload, why_intent = infer_metaphysics_finance_intent_with_ai(
        fbti_code=fbti_code,
        fbti_name=fbti_name,
        wuxing=wuxing,
        time_label=time_label,
        arch=arch,
        natural_intent=natural_intent,
        mood=mood,
    )
    if why_intent != "ok":
        logger.info("FBTI 意图翻译阶段回退规则 (why=%s)", why_intent)
    yield {"event": "intent", "data": intent_payload}

    yield {"event": "stage", "node": "strategy", "label": "金融意图 -> 因子/Alpha 策略匹配…"}
    strategy_bundle, why_strategy = infer_strategy_bundle_with_ai(intent_payload)
    if why_strategy != "ok":
        logger.info("FBTI 策略匹配阶段回退规则 (why=%s)", why_strategy)
    yield {"event": "strategy", "data": strategy_bundle}

    yield {"event": "stage", "node": "prefs", "label": "归纳选股偏好（大模型）…"}
    prefs, why_pref = infer_selection_preferences_with_ai(
        fbti_code=fbti_code,
        fbti_name=fbti_name,
        wuxing=wuxing,
        time_label=time_label,
        arch=arch,
        natural_intent=natural_intent,
        mood=mood,
        intent_payload=intent_payload,
        strategy_bundle=strategy_bundle,
    )
    if why_pref != "ok":
        logger.info("FBTI 偏好阶段未取到模型 JSON，已用人格默认规则 (why=%s)", why_pref)

    yield {"event": "stage", "node": "pool", "label": "随机抽样与规则 Top20…"}
    top20, pool_size, _seed = _sample_and_rank_top_pool(prefs, wuxing)
    prefix = (
        f"全库约 {pool_size} 只中随机抽至多 {_FBTI_SAMPLE_POOL} 只，按偏好规则保留 Top{_FBTI_RANK_TOP}；"
        f"再由模型终筛。"
    )
    if not top20:
        yield {
            "event": "result",
            "data": {"reason": f"{prefix} 基金目录为空，无法选股。".strip(), "funds": []},
        }
        return

    yield {"event": "stage", "node": "quotes", "label": "合并估值数据（若开启）…"}
    top20 = _merge_live_quotes_if_applicable(top20)
    yield {"event": "stage", "node": "llm", "label": "大模型终筛至多 5 只…"}
    summary = str(prefs.get("summary") or "")
    result = select_funds_with_ai(
        fbti_code=fbti_code,
        fbti_name=fbti_name,
        wuxing=wuxing,
        time_label=time_label,
        fund_snapshot=top20,
        rules_summary=summary,
        compact_user_reason=True,
    )
    base_reason = str(result.get("reason") or "").strip()
    strategy_text = f"策略：factors={strategy_bundle.get('factors')}, alpha={strategy_bundle.get('alpha_models')}。"
    result["intent"] = intent_payload
    result["strategy_bundle"] = strategy_bundle
    result["reason"] = f"{prefix} {strategy_text} {base_reason}".strip()
    yield {"event": "result", "data": result}


def run_fbti_ai_selection(
    *,
    fbti_code: str,
    fbti_name: str,
    wuxing: str,
    time_label: str,
    arch: dict[str, Any],
    natural_intent: str = "",
    mood: str = "",
) -> dict[str, Any]:
    """
    对外入口：偏好 LLM → 随机 400 → 规则 Top20 → 选股 LLM Top5。
    返回与原先 select_funds_with_ai 相同结构：{ reason, funds }。
    """
    last: dict[str, Any] | None = None
    for ev in iter_fbti_ai_selection_sse_events(
        fbti_code=fbti_code,
        fbti_name=fbti_name,
        wuxing=wuxing,
        time_label=time_label,
        arch=arch,
        natural_intent=natural_intent,
        mood=mood,
    ):
        if isinstance(ev, dict) and ev.get("event") == "result" and isinstance(ev.get("data"), dict):
            last = ev["data"]
    return last if last is not None else {"reason": "选股流程未返回结果", "funds": []}


def build_fund_snapshot_for_fbti() -> list[dict[str, Any]]:
    """
    兼容旧调用：返回「随机样本 + 中性默认偏好」下的 Top20 瘦身快照（不含两次 LLM）。
    新逻辑请使用 run_fbti_ai_selection。
    """
    prefs = {
        "summary": "",
        "risk_preference": "medium",
        "preferred_tracks": [],
        "avoid_tracks": [],
        "prefer_etf": None,
        "emphasize_sharpe": False,
        "emphasize_low_drawdown": False,
        "emphasize_momentum": False,
    }
    top20, _, _ = _sample_and_rank_top_pool(prefs, wuxing="")
    return _merge_live_quotes_if_applicable(top20)
