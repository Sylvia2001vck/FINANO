from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, File, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.agent.fund_catalog import list_funds
from app.agent.fund_similarity import find_similar_kline_funds
from app.services.similar_funds import similar_funds
from app.agent.graph import invoke_mafb
from app.agent.profiling import build_user_profile
from app.core.exceptions import APIException
from app.core.responses import success_response
from app.core.security import get_current_user
from app.db.session import get_db
from app.modules.agent.schemas import AgentProfileSave, MAFBRunRequest
from app.modules.user.models import User
from app.modules.user.service import update_investor_profile
from app.services.birth_ocr import extract_birth_from_image
from app.services.ai_fund_selector import build_fund_snapshot_for_fbti, select_funds_with_ai
from app.services.fbti_engine import match_archetype

router = APIRouter(prefix="/agent", tags=["mafb"])

try:
    from zoneinfo import ZoneInfo

    _BJ = ZoneInfo("Asia/Shanghai")
except Exception:
    _BJ = None


def _initial_state(payload: MAFBRunRequest, risk_preference: int | None) -> dict:
    return {
        "user_birth": payload.user_birth,
        "user_mbti": payload.user_mbti,
        "fund_code": payload.fund_code.strip(),
        "layout_facing": (payload.layout_facing or "").strip() or None,
        "risk_preference": risk_preference,
        "agent_scores": {},
        "agent_reasons": {},
        "compliance_notes": [],
        "is_compliant": True,
        "blocked_reason": "",
        "final_report": {},
        "rag_chunks": [],
        "proposed_portfolio": [],
    }


def _resolve_run_payload(payload: MAFBRunRequest, user: User) -> MAFBRunRequest:
    if not payload.use_saved_profile:
        return payload.model_copy(
            update={
                "user_birth": payload.user_birth or "1990-01-01",
                "user_mbti": (payload.user_mbti or "INTJ").upper(),
            }
        )

    birth = payload.user_birth
    mbti = payload.user_mbti
    layout = payload.layout_facing

    if user.birth_date and not birth:
        birth = user.birth_date.isoformat()
    if user.mbti and not mbti:
        mbti = user.mbti.upper()
    if user.layout_facing and not layout:
        layout = user.layout_facing

    if not birth or not mbti:
        raise APIException(
            code=40001,
            message="请先调用 POST /api/v1/agent/profile 保存生日与 MBTI，或关闭 use_saved_profile 并传参",
            status_code=400,
        )

    return payload.model_copy(
        update={
            "user_birth": birth,
            "user_mbti": mbti.upper(),
            "layout_facing": layout,
        }
    )


@router.post("/profile")
def save_agent_profile(
    payload: AgentProfileSave,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """保存 MBTI、生日、风水朝向、风险偏好，并返回结构化画像（供报告「命理个性化层」）。"""
    bd = date.fromisoformat(payload.user_birth)
    user = update_investor_profile(
        db,
        current_user.id,
        mbti=payload.user_mbti,
        birth_date=bd,
        layout_facing=payload.layout_facing,
        risk_preference=payload.risk_preference,
    )
    structured = build_user_profile(
        payload.user_birth,
        payload.user_mbti.upper(),
        (payload.layout_facing or user.layout_facing or "").strip() or None,
        payload.risk_preference if payload.risk_preference is not None else user.risk_preference,
    )
    return success_response(
        data={
            "user_id": user.id,
            "saved_fields": {
                "mbti": user.mbti,
                "birth_date": user.birth_date.isoformat() if user.birth_date else None,
                "layout_facing": user.layout_facing,
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
        user.layout_facing,
        user.risk_preference,
    )
    return success_response(
        data={
            "saved_fields": {
                "mbti": user.mbti,
                "birth_date": user.birth_date.isoformat(),
                "layout_facing": user.layout_facing,
                "risk_preference": user.risk_preference,
            },
            "structured_profile": structured,
        },
        message="ok",
    )


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

    resolved = _resolve_run_payload(payload, user)
    state = _initial_state(resolved, user.risk_preference)
    result = invoke_mafb(state)
    report = result.get("final_report") or {}
    safe_snapshot = {
        "weighted_total": result.get("weighted_total"),
        "agent_scores": result.get("agent_scores"),
        "is_compliant": result.get("is_compliant"),
        "blocked_reason": result.get("blocked_reason"),
    }
    return success_response(
        data={"final_report": report, "state_snapshot": safe_snapshot},
        message="MAFB 流水线执行完成",
    )


@router.get("/funds")
def list_demo_funds(_user=Depends(get_current_user)):
    return success_response(data=list_funds())


@router.get("/funds/similar")
def list_similar_funds(
    code: str = Query(..., min_length=6, max_length=6, description="6 位基金/ETF 代码"),
    top_k: int = Query(5, ge=1, le=10),
    _user=Depends(get_current_user),
):
    """基于演示池多维特征（Pandas 归一化 + 余弦相似度）找相似基金。"""
    rows = similar_funds(code, top_k=top_k)
    return success_response(data={"reference_code": code.strip(), "similar": rows}, message="ok")


@router.get("/funds/kline-similar")
def list_kline_similar_funds(
    code: str = Query(..., min_length=6, max_length=6, description="6 位基金/ETF 代码"),
    days: int = Query(60, ge=20, le=200),
    top_k: int = Query(5, ge=1, le=10),
    method: str = Query("cosine", description="cosine | dtw"),
    _user=Depends(get_current_user),
):
    """近 N 日对齐日收益率序列：余弦相似度或 DTW（东方财富历史净值）。"""
    m = "dtw" if method.lower().strip() == "dtw" else "cosine"
    rows = find_similar_kline_funds(code.strip(), top_n=top_k, days=days, method=m)
    return success_response(
        data={"reference_code": code.strip(), "days": days, "method": m, "similar": rows},
        message="ok",
    )


@router.post("/ocr-birth")
async def ocr_birth(file: UploadFile = File(...), _user=Depends(get_current_user)):
    content = await file.read()
    birth, hint = extract_birth_from_image(content)
    return success_response(data={"user_birth": birth, "hint": hint}, message="OCR 处理完成")


class FbtiSelectBody(BaseModel):
    """可选覆盖参数（默认读当前登录用户画像）。"""
    fbti_code: str | None = None
    wuxing: str | None = None


@router.post("/ai/fbti-select")
def fbti_ai_select_funds(
    payload: FbtiSelectBody = FbtiSelectBody(),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    FBTI + 五行 + 基金池（含可选实时行情）→ 大模型 JSON 选股；无 Key 时规则兜底。
    """
    user = db.get(User, current_user.id)
    if not user:
        raise APIException(code=10001, status_code=404)
    code = (payload.fbti_code or user.fbti_profile) or ""
    if not code:
        raise APIException(code=40002, message="请先完成 FBTI 测试 POST /api/v1/user/fbti/test", status_code=400)
    arch = match_archetype(code)
    wx = (payload.wuxing or user.user_wuxing) or str(arch.get("wuxing") or "")
    if _BJ:
        now = datetime.now(_BJ)
        time_label = now.strftime("%Y-%m-%d %H:%M 北京时间")
    else:
        time_label = datetime.now().strftime("%Y-%m-%d %H:%M 本地时间")
    snap = build_fund_snapshot_for_fbti()
    result = select_funds_with_ai(
        fbti_code=str(arch.get("matched_code", arch["code"])),
        fbti_name=str(arch["name"]),
        wuxing=wx,
        time_label=time_label,
        fund_snapshot=snap,
    )
    return success_response(data=result, message="FBTI AI 选股完成")
