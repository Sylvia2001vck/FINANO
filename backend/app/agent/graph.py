from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.agent.nodes import (
    node_asset_allocation,
    node_blocked,
    node_compliance,
    node_fundamental,
    node_kline_similar,
    node_load_fund_and_rag,
    node_risk,
    node_technical,
    node_user_profiling,
    node_voting,
    route_after_compliance,
    route_parallel_analysts,
)
from app.agent.state import MAFBState

_COMPILED = None


def build_mafb_graph() -> StateGraph:
    graph = StateGraph(MAFBState)
    graph.add_node("profile", node_user_profiling)
    graph.add_node("rag", node_load_fund_and_rag)
    graph.add_node("fundamental", node_fundamental)
    graph.add_node("technical", node_technical)
    graph.add_node("risk", node_risk)
    graph.add_node("kline_similar", node_kline_similar)
    graph.add_node("allocation", node_asset_allocation)
    graph.add_node("compliance", node_compliance)
    graph.add_node("voting", node_voting)
    graph.add_node("blocked", node_blocked)

    graph.set_entry_point("profile")
    graph.add_edge("profile", "rag")
    graph.add_conditional_edges("rag", route_parallel_analysts)
    graph.add_edge("fundamental", "allocation")
    graph.add_edge("technical", "allocation")
    graph.add_edge("risk", "allocation")
    graph.add_edge("kline_similar", "allocation")
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
        _COMPILED = build_mafb_graph().compile()
    return _COMPILED


def invoke_mafb(initial: dict) -> dict:
    """Run full workflow; returns final state (includes final_report)."""
    app = get_compiled_graph()
    return app.invoke(initial)
