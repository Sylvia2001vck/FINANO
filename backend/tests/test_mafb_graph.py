"""MAFB LangGraph 全链路单测（依赖 requirements.txt 中的 langgraph==0.2.18）。"""

from __future__ import annotations

from app.agent.graph import get_mafb_state_after_stream, invoke_mafb, stream_mafb_stages
from app.agent.nodes import route_parallel_analysts


def _base_initial():
    return {
        "include_fbti": True,
        "fbti_profile": "RLDC",
        "fund_code": "510300",
        "layout_facing": None,
        "agent_scores": {},
        "agent_reasons": {},
        "compliance_notes": [],
        "is_compliant": True,
        "blocked_reason": "",
        "final_report": {},
        "rag_chunks": [],
        "proposed_portfolio": [],
        "risk_preference": 3,
        "kline_similar_funds": [],
    }


def test_parallel_analysts_fanout_four_nodes():
    sends = route_parallel_analysts(_base_initial())
    assert len(sends) == 4
    targets = {s.node for s in sends}
    assert targets == {"fundamental", "technical", "risk", "kline_similar"}


def test_mafb_pipeline_returns_structured_report():
    result = invoke_mafb(_base_initial())
    report = result.get("final_report") or {}
    assert "verdict" in report
    assert report.get("verdict") == "pass"
    assert "scores" in report
    assert "disclaimer" in report
    scores = report.get("scores") or {}
    for key in ("fundamental", "technical", "risk", "kline", "profiling", "allocation"):
        assert key in scores
    assert "compliance" in report
    assert "kline_similar_funds" in report
    assert "weighted_total" in report
    assert "reasoning_chain" in report
    assert isinstance(report.get("reasoning_chain"), list)
    sim5 = report.get("similarity_top5") or []
    assert isinstance(sim5, list)
    assert len(sim5) <= 5
    assert report.get("user_profile", {}).get("profile_mode") == "fbti_only"
    assert result.get("weighted_total") is not None


def test_mafb_agent_scores_merged_in_state():
    result = invoke_mafb(_base_initial())
    merged = result.get("agent_scores") or {}
    assert "fundamental" in merged
    assert "technical" in merged
    assert "risk" in merged
    assert "kline" in merged


def test_mafb_stream_stages_then_state_matches_invoke_shape():
    import uuid

    initial = _base_initial()
    tid = str(uuid.uuid4())
    stages = list(stream_mafb_stages(initial, tid))
    assert stages
    assert all(s.get("event") == "stage" and s.get("node") for s in stages)
    nodes = {s["node"] for s in stages}
    assert "profile" in nodes and "rag" in nodes
    final = get_mafb_state_after_stream(tid)
    assert final is not None
    report = final.get("final_report") or {}
    assert report.get("verdict") in ("pass", "blocked")
    assert "reasoning_chain" in report
    assert len(report.get("reasoning_chain") or []) >= 6
