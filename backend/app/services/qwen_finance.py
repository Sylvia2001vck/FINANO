import json

from app.core.config import settings
from app.core.dashscope_setup import apply_dashscope_settings

try:
    import dashscope
except ImportError:
    dashscope = None


def _local_analysis(trade_data: dict, stats: dict) -> dict:
    profit = float(trade_data.get("profit", 0) or 0)
    fee = float(trade_data.get("fee", 0) or 0)
    win_rate = float(stats.get("win_rate", 0) or 0)
    strengths = []
    problems = []
    suggestions = []

    if profit > 0:
        strengths.append("该笔交易实现正收益，说明离场结果优于亏损样本。")
    else:
        problems.append("该笔交易未形成正收益，需要复盘入场依据与止损执行。")

    if fee <= max(abs(profit) * 0.05, 20):
        strengths.append("手续费占比可控，交易成本没有明显侵蚀结果。")
    else:
        problems.append("手续费占比较高，可能削弱策略净收益。")

    if win_rate >= 50:
        strengths.append("当前历史胜率不低于 50%，说明策略具备一定稳定性。")
    else:
        problems.append("当前历史胜率偏低，策略一致性仍需加强。")

    suggestions.append("补充当时的入场逻辑、止损条件和离场触发点，形成可复用复盘模板。")
    suggestions.append("将本笔交易与同类标的放在一起比较，验证是否存在重复性执行偏差。")

    return {
        "strengths": strengths[:2] or ["交易记录已完整保存，可继续沉淀为样本。"],
        "problems": problems[:2] or ["暂未发现明显结构性问题，但仍应关注样本量是否足够。"],
        "suggestions": suggestions[:2],
    }


def analyze_trade(trade_data: dict, stats: dict):
    if not settings.dashscope_api_key or dashscope is None:
        return _local_analysis(trade_data, stats)

    apply_dashscope_settings(dashscope)
    system_prompt = (
        "你是 Finano 专业交易复盘助手，只基于用户提供的交易数据做事实性分析，"
        "不预测市场，不给出投资建议。严格输出 JSON，字段为 strengths、problems、suggestions。"
    )
    user_prompt = f"交易数据：{trade_data}\n历史统计：{stats}\n请分析这笔交易的优缺点和改进建议。"
    response = dashscope.Generation.call(
        model="qwen-plus",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        result_format="message",
        temperature=0.1,
        max_tokens=512,
    )
    content = response.output.choices[0].message.content
    if isinstance(content, dict):
        return content
    try:
        return json.loads(content)
    except Exception:
        return _local_analysis(trade_data, stats)
