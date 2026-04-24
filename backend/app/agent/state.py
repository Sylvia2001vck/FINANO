from __future__ import annotations

from typing import Annotated, Any, TypedDict


def _merge_scores(left: dict[str, int] | None, right: dict[str, int] | None) -> dict[str, int]:
    base = dict(left or {})
    base.update(right or {})
    return base


def _merge_str_list(left: list[str] | None, right: list[str] | None) -> list[str]:
    return list(left or []) + list(right or [])


def _merge_reasons(left: dict[str, str] | None, right: dict[str, str] | None) -> dict[str, str]:
    return {**(left or {}), **(right or {})}


def _merge_dict_any(left: dict[str, Any] | None, right: dict[str, Any] | None) -> dict[str, Any]:
    return {**(left or {}), **(right or {})}


class MAFBState(TypedDict, total=False):
    """Shared graph state — all agents read/write the same object (no memory silos)."""

    include_fbti: bool
    fbti_profile: str | None
    fund_code: str
    layout_facing: str
    risk_preference: int | None
    status: str
    task_id: str

    user_profile: dict[str, Any]
    risk_level: int

    fund_data: dict[str, Any]
    rag_chunks: list[str]
    technical_retrieval: Annotated[dict[str, Any], _merge_dict_any]

    agent_scores: Annotated[dict[str, int], _merge_scores]
    agent_reasons: Annotated[dict[str, str], _merge_reasons]

    proposed_portfolio: list[dict[str, Any]]

    compliance_notes: Annotated[list[str], _merge_str_list]
    compliance_rewrite_needed: bool

    is_compliant: bool
    blocked_reason: str

    weighted_total: float
    final_report: dict[str, Any]
