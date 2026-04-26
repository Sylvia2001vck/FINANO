from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.agent.fund_catalog import list_funds_catalog_sample, list_funds_catalog_window, static_demo_pool_size
from app.agent.kline_retriever import get_shadow_segments_for_matches, retrieve_technical_matches
from app.services.similar_funds import similar_funds
from app.agent.graph import get_mafb_state_after_stream, invoke_mafb, stream_mafb_stages
from app.agent.task_registry import create_mafb_task, get_mafb_task
from app.agent.llm_client import probe_qwen_llm
from app.agent.profiling import build_user_profile
from app.core.exceptions import APIException
from app.core.responses import success_response
from app.core.security import get_current_user
from app.db.session import get_db
from app.modules.agent.schemas import AgentProfileSave, LLMProbeRequest, MAFBRunRequest
from app.modules.user.models import User
from app.modules.user.service import update_investor_profile
from app.services.ai_fund_selector import (
    infer_bazi_today_analysis_with_ai,
    infer_metaphysics_finance_intent_with_ai,
    infer_strategy_bundle_with_ai,
    iter_fbti_ai_selection_sse_events,
    run_fbti_ai_selection,
)
from app.services.user_agent_fund_pool import add_to_pool, list_pool_funds, remove_from_pool
from app.services.fbti_engine import match_archetype
from app.services.bazi_wuxing import BAZI_TIME_SLOT_TO_HOUR, derive_bazi_text_from_birth

router = APIRouter(prefix="/agent", tags=["mafb"])

try:
    from zoneinfo import ZoneInfo

    _BJ = ZoneInfo("Asia/Shanghai")
except Exception:
    _BJ = None


def _initial_state(payload: MAFBRunRequest, risk_preference: int | None, fbti_profile: str | None) -> dict:
    eff_fbti = fbti_profile if payload.include_fbti else None
    return {
        "include_fbti": payload.include_fbti,
        "fbti_profile": eff_fbti,
        "fund_code": payload.fund_code.strip(),
        "layout_facing": None,
        "risk_preference": risk_preference,
        "status": "queued",
        "task_id": "",
        "agent_scores": {},
        "agent_reasons": {},
        "compliance_notes": [],
        "compliance_rewrite_needed": False,
        "is_compliant": True,
        "blocked_reason": "",
        "final_report": {},
        "rag_chunks": [],
        "proposed_portfolio": [],
        "technical_retrieval": {},
    }


@router.post("/profile")
def save_agent_profile(
    payload: AgentProfileSave,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """保存 MBTI、生日、风险偏好，并返回结构化画像（供报告「命理个性化层」）。"""
    bd = date.fromisoformat(payload.user_birth)
    slot = str(payload.birth_time_slot or "").strip().upper()
    if slot and slot not in BAZI_TIME_SLOT_TO_HOUR:
        raise APIException(code=40003, message="birth_time_slot 非法", status_code=400)
    user = update_investor_profile(
        db,
        current_user.id,
        mbti=payload.user_mbti,
        birth_date=bd,
        birth_time_slot=slot or None,
        layout_facing="",
        risk_preference=payload.risk_preference,
    )
    structured = build_user_profile(
        payload.user_birth,
        payload.user_mbti.upper(),
        None,
        payload.risk_preference if payload.risk_preference is not None else user.risk_preference,
    )
    return success_response(
        data={
            "user_id": user.id,
            "saved_fields": {
                "mbti": user.mbti,
                "birth_date": user.birth_date.isoformat() if user.birth_date else None,
                "birth_time_slot": user.birth_time_slot,
                "risk_preference": user.risk_preference,
            },
            "structured_profile": structured,
        },
        message="画像已保存并生成结构化特征",
    )


@router.get("/profile")
def get_agent_profile(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user = db.get(User, current_user.id)
    if not user:
        raise APIException(code=10001, status_code=404)
    if not user.birth_date or not user.mbti:
        return success_response(
            data={"saved_fields": None, "structured_profile": None},
            message="尚未保存画像，请使用 POST /api/v1/agent/profile",
        )
    structured = build_user_profile(
        user.birth_date.isoformat(),
        user.mbti,
        None,
        user.risk_preference,
    )
    return success_response(
        data={
            "saved_fields": {
                "mbti": user.mbti,
                "birth_date": user.birth_date.isoformat(),
                "birth_time_slot": user.birth_time_slot,
                "risk_preference": user.risk_preference,
            },
            "structured_profile": structured,
        },
        message="ok",
    )


def _mafb_response_payload(result: dict) -> dict:
    report = result.get("final_report") or {}
    safe_snapshot = {
        "weighted_total": result.get("weighted_total"),
        "agent_scores": result.get("agent_scores"),
        "agent_reasons": result.get("agent_reasons"),
        "is_compliant": result.get("is_compliant"),
        "blocked_reason": result.get("blocked_reason"),
        "compliance_notes": result.get("compliance_notes") or [],
        "technical_retrieval": result.get("technical_retrieval") or {},
    }
    return {"final_report": report, "state_snapshot": safe_snapshot}


@router.post("/run")
def run_mafb_pipeline(
    payload: MAFBRunRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """运行完整 LangGraph MAFB 流水线。"""
    user = db.get(User, current_user.id)
    if not user:
        raise APIException(code=10001, status_code=404)

    state = _initial_state(payload, user.risk_preference, user.fbti_profile)
    result = invoke_mafb(state)
    return success_response(
        data=_mafb_response_payload(result),
        message="MAFB 流水线执行完成",
    )


@router.post("/run/stream")
def run_mafb_pipeline_stream(
    payload: MAFBRunRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """SSE：按节点推送阶段名，最后一条 event=result 与 POST /agent/run 结构一致。"""
    user = db.get(User, current_user.id)
    if not user:
        raise APIException(code=10001, status_code=404)

    initial = _initial_state(payload, user.risk_preference, user.fbti_profile)
    thread_id = str(uuid.uuid4())

    def event_gen():
        try:
            bootstrap = {
                "event": "stage",
                "node": "bootstrap",
                "label": "执行计划已生成：正在启动基本面/技术面/风控/业绩风格归因并行分析…",
            }
            yield f"data: {json.dumps(bootstrap, ensure_ascii=False)}\n\n"
            for ev in stream_mafb_stages(initial, thread_id):
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
            final = get_mafb_state_after_stream(thread_id) or invoke_mafb(initial)
            out = _mafb_response_payload(final)
            yield f"data: {json.dumps({'event': 'result', 'data': out}, ensure_ascii=False, default=str)}\n\n"
        except Exception as e:  # noqa: BLE001 — 流式响应需把错误写入终端
            yield f"data: {json.dumps({'event': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/run/async")
def run_mafb_pipeline_async(
    payload: MAFBRunRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    异步注册任务：立即返回 task_id，后端后台线程跑 LangGraph。
    可轮询 GET /agent/status/{task_id} 获取阶段与最终结果，规避网关长连接超时。
    """
    user = db.get(User, current_user.id)
    if not user:
        raise APIException(code=10001, status_code=404)
    initial = _initial_state(payload, user.risk_preference, user.fbti_profile)
    task_id = create_mafb_task(initial, owner_user_id=current_user.id)
    return success_response(
        data={"task_id": task_id, "status": "queued"},
        message="MAFB 任务已提交",
    )


@router.get("/status/{task_id}")
def get_mafb_pipeline_status(
    task_id: str,
    since: int = Query(0, ge=0, description="事件游标：仅返回 [since:] 的新事件"),
    current_user: User = Depends(get_current_user),
):
    rec = get_mafb_task(task_id)
    if not rec:
        raise APIException(code=40004, message="task not found", status_code=404)
    if int(rec.get("owner_user_id") or 0) != int(current_user.id):
        raise APIException(code=10003, status_code=403, message="forbidden")

    status = str(rec.get("status") or "unknown")
    out: dict[str, Any] = {
        "task_id": task_id,
        "status": status,
        "stage_node": rec.get("stage_node"),
        "stage_label": rec.get("stage_label"),
        "error": rec.get("error"),
        "created_at": rec.get("created_at"),
        "updated_at": rec.get("updated_at"),
        "done": status in ("completed", "failed"),
    }
    trace_events = list(rec.get("trace_events") or [])
    if since >= len(trace_events):
        out["trace_events"] = []
        out["next_cursor"] = len(trace_events)
    else:
        out["trace_events"] = trace_events[since:]
        out["next_cursor"] = len(trace_events)
    if status == "completed" and isinstance(rec.get("result_state"), dict):
        out["data"] = _mafb_response_payload(rec["result_state"])
    return success_response(data=out, message="ok")


@router.post("/llm-probe")
def llm_probe(
    payload: LLMProbeRequest,
    _user: User = Depends(get_current_user),
):
    """Qwen 通道快速探针：返回耗时、状态、错误码与 raw 片段。"""
    data = probe_qwen_llm(
        payload.prompt,
        model=(payload.model or "").strip() or None,
        timeout_sec=float(payload.timeout_sec),
    )
    return success_response(data=data, message="ok" if data.get("ok") else "probe_failed")


@router.get("/funds/catalog-status")
def fund_catalog_status(_user=Depends(get_current_user)):
    """全市场模式：是否已缓存、是否正在拉取（含同步 GET /funds）、错误信息；静态模式始终 ready。"""
    mode = (settings.fund_catalog_mode or "static").strip().lower()
    if mode != "eastmoney_full":
        return success_response(
            data={
                "catalog_mode": settings.fund_catalog_mode,
                "cached": True,
                "count": static_demo_pool_size(),
                "busy": False,
                "error": None,
            },
            message="ok",
        )
    from app.agent.eastmoney_fund_loader import get_catalog_status

    st = get_catalog_status()
    return success_response(
        data={"catalog_mode": settings.fund_catalog_mode, **st},
        message="ok",
    )


@router.post("/funds/warm-catalog")
def warm_fund_catalog(_user=Depends(get_current_user)):
    """在后台线程开始拉取天天基金全量索引（与首次访问目录共享单飞锁）；静态模式跳过。"""
    mode = (settings.fund_catalog_mode or "static").strip().lower()
    if mode != "eastmoney_full":
        return success_response(data={"status": "skipped", "catalog_mode": settings.fund_catalog_mode}, message="当前为静态演示池")
    from app.agent.eastmoney_fund_loader import start_warm_catalog_background

    status = start_warm_catalog_background()
    return success_response(
        data={"status": status, "catalog_mode": settings.fund_catalog_mode},
        message="ok",
    )


class MyPoolCodesBody(BaseModel):
    codes: list[str]


@router.get("/funds")
def list_demo_funds(
    view: str = Query(
        "catalog",
        description="catalog=顺序分页+搜索 | random=筛选后随机抽样 | my_pool=我的自选",
    ),
    limit: int = Query(200, ge=1, le=5000, description="catalog 为分页条数；random 为抽样条数"),
    offset: int = Query(0, ge=0),
    q: str | None = Query(None, description="按代码或名称子串筛选（catalog / random 均可用）"),
    seed: int | None = Query(None, description="random 时随机种子，不传则用当前时间毫秒"),
    track: str | None = Query(None, description="random：赛道子串筛选"),
    fund_type: str | None = Query(None, description="random：类型字段子串筛选"),
    etf_only: bool = Query(False, description="random：仅 ETF"),
    risk_min: int | None = Query(None, ge=1, le=5),
    risk_max: int | None = Query(None, ge=1, le=5),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    view_l = (view or "catalog").lower().strip()
    if view_l == "my_pool":
        items, total = list_pool_funds(db, current_user.id)
        return success_response(
            data={
                "items": items,
                "total": total,
                "catalog_mode": settings.fund_catalog_mode,
                "limit": total,
                "offset": 0,
                "view": "my_pool",
                "sample_seed": None,
                "filter_total": None,
            },
            message="ok",
        )
    if view_l == "random":
        items, filt_total, seed_used = list_funds_catalog_sample(
            limit=limit,
            seed=seed,
            query=q,
            track_kw=track,
            type_kw=fund_type,
            etf_only=etf_only,
            risk_min=risk_min,
            risk_max=risk_max,
        )
        return success_response(
            data={
                "items": items,
                "total": len(items),
                "catalog_mode": settings.fund_catalog_mode,
                "limit": limit,
                "offset": 0,
                "view": "random",
                "sample_seed": seed_used,
                "filter_total": filt_total,
            },
            message="ok",
        )

    items, total = list_funds_catalog_window(limit=limit, offset=offset, query=q)
    return success_response(
        data={
            "items": items,
            "total": total,
            "catalog_mode": settings.fund_catalog_mode,
            "limit": limit,
            "offset": offset,
            "view": "catalog",
            "sample_seed": None,
            "filter_total": None,
        },
        message="ok",
    )


@router.post("/funds/my-pool")
def my_pool_add_codes(
    body: MyPoolCodesBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """批量加入自选（6 位代码，自动去重；非法项忽略）。"""
    n = add_to_pool(db, current_user.id, body.codes)
    items, total = list_pool_funds(db, current_user.id)
    return success_response(
        data={"added": n, "items": items, "total": total},
        message=f"已处理，新增 {n} 条",
    )


@router.delete("/funds/my-pool/{fund_code}")
def my_pool_remove_code(
    fund_code: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ok = remove_from_pool(db, current_user.id, fund_code)
    if not ok:
        raise APIException(code=40004, message="未找到该自选或代码无效", status_code=404)
    items, total = list_pool_funds(db, current_user.id)
    return success_response(data={"items": items, "total": total}, message="已移除")


@router.get("/funds/similar")
def list_similar_funds(
    code: str = Query(..., min_length=6, max_length=6, description="6 位基金/ETF 代码"),
    top_k: int = Query(10, ge=1, le=20),
    _user=Depends(get_current_user),
):
    """基于当前基金目录多维特征（Pandas 归一化 + 余弦相似度）找相似基金。"""
    rows = similar_funds(code, top_k=top_k)
    return success_response(data={"reference_code": code.strip(), "similar": rows}, message="ok")


@router.get("/funds/kline-shadow")
def list_kline_shadow_segments(
    code: str = Query(..., min_length=6, max_length=6, description="6 位基金/ETF 代码"),
    top_k: int = Query(5, ge=1, le=10),
    _user=Depends(get_current_user),
):
    """离线仓+FAISS：返回 Technical 相似窗口与可视化影子线片段。"""
    retrieval = retrieve_technical_matches(code.strip(), top_k=top_k)
    matches = list(retrieval.get("matches") or [])
    segments = get_shadow_segments_for_matches(matches)
    return success_response(
        data={
            "reference_code": code.strip(),
            "ok": bool(retrieval.get("ok")),
            "error": retrieval.get("error"),
            "query": retrieval.get("query"),
            "match_dates": [
                {"code": m.get("code"), "start_date": m.get("start_date"), "end_date": m.get("end_date"), "similarity": m.get("similarity")}
                for m in matches
            ],
            "segments": segments,
            "data_version": retrieval.get("data_version") or {},
        },
        message="ok" if retrieval.get("ok") else "data_not_ready",
    )


class FbtiSelectBody(BaseModel):
    """可选覆盖参数（默认读当前登录用户画像）。"""
    fbti_code: str | None = None
    wuxing: str | None = None
    bazi_text: str | None = None
    natural_intent: str | None = None
    mood: str | None = None
    auto_confirm: bool = False


def _fbti_time_label() -> str:
    if _BJ:
        return datetime.now(_BJ).strftime("%Y-%m-%d %H:%M 北京时间")
    return datetime.now().strftime("%Y-%m-%d %H:%M 本地时间")


def _fbti_select_context(
    payload: FbtiSelectBody,
    current_user: User,
    db: Session,
) -> tuple[User, dict, str, str]:
    """校验用户与 FBTI，返回 (user, arch, wuxing, time_label)。"""
    user = db.get(User, current_user.id)
    if not user:
        raise APIException(code=10001, status_code=404)
    code = (payload.fbti_code or user.fbti_profile) or ""
    bazi = str(payload.bazi_text or "").strip()
    has_birth = bool(user.birth_date)
    if not code and not bazi and not has_birth:
        raise APIException(
            code=40002,
            message="请先在用户档案保存生日+出生时段，或先完成 FBTI 测试，或手动提供八字文本",
            status_code=400,
        )
    if not code:
        code = "RLDC"
    arch = match_archetype(code)
    wx = (payload.wuxing or user.user_wuxing) or str(arch.get("wuxing") or "")
    return user, arch, wx, _fbti_time_label()


def _resolve_bazi_text(payload: FbtiSelectBody, user: User) -> str:
    manual = str(payload.bazi_text or "").strip()
    if manual:
        return manual
    if user.birth_date:
        return derive_bazi_text_from_birth(user.birth_date, user.birth_time_slot)
    return ""


@router.post("/ai/fbti-select")
def fbti_ai_select_funds(
    payload: FbtiSelectBody = FbtiSelectBody(),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """FBTI + 五行娱乐融合：偏好 JSON → 随机样本 → 规则 Top20 → 模型终筛至多 5 只。"""
    user, arch, wx, time_label = _fbti_select_context(payload, current_user, db)
    bazi_text = _resolve_bazi_text(payload, user)
    result = dict(
        run_fbti_ai_selection(
            fbti_code=str(arch.get("matched_code", arch["code"])),
            fbti_name=str(arch["name"]),
            wuxing=wx,
            time_label=time_label,
            arch=arch,
            natural_intent=str(payload.natural_intent or ""),
            mood=str(payload.mood or ""),
            bazi_text=bazi_text,
        )
    )
    return success_response(data=result, message="FBTI AI 选股完成")


@router.post("/ai/fbti-select/intent")
def fbti_ai_select_intent(
    payload: FbtiSelectBody = FbtiSelectBody(),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """阶段预览：八字当日解读 + 玄学语义翻译 + 策略匹配，供前端确认后再执行。"""
    _user, arch, wx, time_label = _fbti_select_context(payload, current_user, db)
    bazi_text = _resolve_bazi_text(payload, _user)
    fbti_code = str(arch.get("matched_code", arch["code"]))
    fbti_name = str(arch["name"])
    bazi_payload, _ = infer_bazi_today_analysis_with_ai(
        bazi_text=bazi_text,
        time_label=time_label,
        natural_intent=str(payload.natural_intent or ""),
        mood=str(payload.mood or ""),
    )
    intent_payload, _ = infer_metaphysics_finance_intent_with_ai(
        fbti_code=fbti_code,
        fbti_name=fbti_name,
        wuxing=wx,
        time_label=time_label,
        arch=arch,
        natural_intent=(str(payload.natural_intent or "") + f"；八字解读摘要：{str(bazi_payload.get('bazi_summary') or '')}").strip("；"),
        mood=str(payload.mood or ""),
        bazi_text=bazi_text,
        bazi_analysis=bazi_payload,
    )
    strategy_bundle, _ = infer_strategy_bundle_with_ai(intent_payload)
    need_confirm = (not bool(payload.auto_confirm)) and float(intent_payload.get("confidence") or 0.0) < 0.85
    return success_response(
        data={
            "bazi_analysis": bazi_payload,
            "intent": intent_payload,
            "strategy_bundle": strategy_bundle,
            "need_confirm": need_confirm,
        },
        message="intent_preview_ready",
    )


@router.post("/ai/fbti-select/stream")
def fbti_ai_select_funds_stream(
    payload: FbtiSelectBody = FbtiSelectBody(),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """SSE：阶段提示 + 最终结果（data 与 POST /ai/fbti-select 的 data 结构一致）。"""
    user, arch, wx, time_label = _fbti_select_context(payload, current_user, db)
    bazi_text = _resolve_bazi_text(payload, user)
    fbti_code = str(arch.get("matched_code", arch["code"]))
    fbti_name = str(arch["name"])

    def event_gen():
        try:
            for ev in iter_fbti_ai_selection_sse_events(
                fbti_code=fbti_code,
                fbti_name=fbti_name,
                wuxing=wx,
                time_label=time_label,
                arch=arch,
                natural_intent=str(payload.natural_intent or ""),
                mood=str(payload.mood or ""),
                bazi_text=bazi_text,
            ):
                if ev.get("event") == "result" and isinstance(ev.get("data"), dict):
                    yield f"data: {json.dumps({'event': 'result', 'data': ev['data']}, ensure_ascii=False, default=str)}\n\n"
                else:
                    yield f"data: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"
        except Exception as e:  # noqa: BLE001
            yield f"data: {json.dumps({'event': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
