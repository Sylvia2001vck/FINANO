from __future__ import annotations

import uuid
from typing import Any, Iterator

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from app.agent.nodes import (
    node_asset_allocation,
    node_blocked,
    node_compliance,
    node_fundamental,
    node_kline_similar,
    node_load_fund_and_rag,
    node_profiling,
    node_risk,
    node_technical,
    node_user_profiling,
    node_voting,
    route_after_compliance,
    route_parallel_analysts,
)
from app.agent.state import MAFBState

_COMPILED = None

# 与 stream 的 updates 事件对应，供前端展示「当前阶段」
MAFB_NODE_LABELS: dict[str, str] = {
    "profile": "用户画像（FBTI 金融人格 + 风险偏好）",
    "rag": "基金档案加载与 FAISS 向量检索",
    "fundamental": "基本面智能体（规模、夏普、回撤等）",
    "technical": "技术面智能体（动量与趋势特征）",
    "risk": "风控智能体（标的下行风险与防御能力）",
    "kline_similar": "K线形态学智能体（PAA/DTW 形态重演）",
    "profiling": "画像匹配智能体（标的 × 用户性格适配）",
    "allocation": "资产配置与组合权重草案",
    "compliance": "合规审查（禁宣词 / 错配 / 可选大模型）",
    "voting": "加权汇总与 TOP5 / 报告生成",
    "blocked": "合规拦截分支（输出受限说明）",
}


def build_mafb_graph() -> StateGraph:
    graph = StateGraph(MAFBState)
    graph.add_node("profile", node_user_profiling)
    graph.add_node("rag", node_load_fund_and_rag)
    graph.add_node("fundamental", node_fundamental)
    graph.add_node("technical", node_technical)
    graph.add_node("risk", node_risk)
    graph.add_node("kline_similar", node_kline_similar)
    graph.add_node("profiling", node_profiling)
    graph.add_node("allocation", node_asset_allocation)
    graph.add_node("compliance", node_compliance)
    graph.add_node("voting", node_voting)
    graph.add_node("blocked", node_blocked)

    graph.set_entry_point("profile")
    graph.add_edge("profile", "rag")
    graph.add_conditional_edges("rag", route_parallel_analysts)
    graph.add_edge("fundamental", "kline_similar")
    graph.add_edge("technical", "kline_similar")
    graph.add_edge("risk", "kline_similar")
    graph.add_edge("kline_similar", "profiling")
    graph.add_edge("profiling", "allocation")
    graph.add_edge("allocation", "compliance")
    graph.add_conditional_edges(
        "compliance",
        route_after_compliance,
        {
            "voting": "voting",
            "blocked": "blocked",
        },
    )
    graph.add_edge("voting", END)
    graph.add_edge("blocked", END)
    return graph


def get_compiled_graph():
    global _COMPILED
    if _COMPILED is None:
        _COMPILED = build_mafb_graph().compile(checkpointer=MemorySaver())
    return _COMPILED


def invoke_mafb(initial: dict) -> dict:
    """Run full workflow; returns final state (includes final_report)."""
    app = get_compiled_graph()
    cfg = {"configurable": {"thread_id": str(uuid.uuid4())}}
    return app.invoke(initial, cfg)


def stream_mafb_stages(initial: dict, thread_id: str) -> Iterator[dict[str, Any]]:
    """LangGraph stream_mode=updates：每个节点完成时 yield 一条；结束后需配合 get_state 取终态。"""
    app = get_compiled_graph()
    cfg = {"configurable": {"thread_id": thread_id}}
    for chunk in app.stream(initial, cfg, stream_mode="updates"):
        for node, _delta in chunk.items():
            yield {
                "event": "stage",
                "node": node,
                "label": MAFB_NODE_LABELS.get(node, node),
            }


def get_mafb_state_after_stream(thread_id: str) -> dict[str, Any] | None:
    """与 stream_mafb_stages 使用相同 thread_id，读取合并后的最终状态。"""
    app = get_compiled_graph()
    cfg = {"configurable": {"thread_id": thread_id}}
    snap = app.get_state(cfg)
    if snap is None:
        return None
    vals = getattr(snap, "values", None)
    if vals is None:
        return None
    if isinstance(vals, dict):
        return vals
    try:
        return dict(vals)
    except (TypeError, ValueError):
        return None
