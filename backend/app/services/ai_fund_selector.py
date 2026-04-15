"""FBTI + 五行 + 基金池（含可选实时行情）→ 大模型 JSON 选股；失败则规则兜底。"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.agent.fund_catalog import list_funds
from app.agent import llm_client as _llm  # noqa: PLC2701

logger = logging.getLogger(__name__)


def _extract_json(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        return json.loads(m.group())
    except json.JSONDecodeError:
        return None


def _invoke_json_llm(system: str, user: str) -> dict[str, Any] | None:
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    try:
        raw = _llm._invoke_finance_llm(messages, user)
    except Exception:
        return None
    if not raw:
        return None
    return _extract_json(raw)


def select_funds_with_ai(
    *,
    fbti_code: str,
    fbti_name: str,
    wuxing: str,
    time_label: str,
    fund_snapshot: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    返回 { "reason": str, "funds": [ { code, name, wuxing_tag, change_hint, ... } ] }
    """
    snap_json = json.dumps(fund_snapshot[:40], ensure_ascii=False)
    system = (
        "你只输出一个合法 JSON 对象，键为 reason（字符串）与 funds（数组）。"
        "funds 每项含：code,name,wuxing_tag,change_hint（字符串，可写估值涨跌概况或「见行情」）。"
        "不得承诺收益；选 5 只以内；理由需中性合规。"
    )
    user = f"""用户金融人格：{fbti_code}（{fbti_name}），五行偏好：{wuxing}，参考时辰：{time_label}
筛选规则（演示）：
1）匹配人格风险与周期风格；2）五行对应：金=稳健/价值、木=成长、水=科技均衡、火=热点弹性、土=宽基核心；
3）结合下列基金快照（含可选 live_quote）优选不超过 5 只。

基金快照：
{snap_json}
"""
    parsed = _invoke_json_llm(system, user)
    if parsed and isinstance(parsed.get("funds"), list):
        return parsed

    # 规则兜底：取前 5 只演示池
    logger.info("FBTI AI selector fallback to rule-based list")
    funds = fund_snapshot[:5]
    return {
        "reason": (
            f"云端模型不可用，已按演示池与人格「{fbti_code}」做规则占位展示；"
            "配置 DASHSCOPE_API_KEY 后可启用语义筛选。"
        ),
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


def build_fund_snapshot_for_fbti() -> list[dict[str, Any]]:
    """与列表接口一致：含可选 live_quote。"""
    return list_funds()
