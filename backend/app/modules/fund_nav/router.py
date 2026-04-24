"""基金历史净值 JSON 代理（天天基金 f10/lsjz），供前端 ECharts 画图。

浏览器不直连东财：统一 Referer/UA 与频控由服务端完成。
区间查询走内存 LRU + 增量合并；长连接见 ``/funds/ws/lsjz-json``。
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.core.responses import success_response
from app.core.security import decode_access_token, get_current_user
from app.db.session import get_db
from app.modules.user.models import User
from app.modules.fund_nav.service import get_fund_snapshot_status
from app.services.fund_data import fetch_lsjz_eastmoney_json_api_cached

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/funds", tags=["fund-nav"])


@router.get("/snapshot-status")
def snapshot_status(_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    data = get_fund_snapshot_status(db)
    return success_response(data=data, message="ok")


@router.get("/lsjz-json")
def get_fund_lsjz_json(
    fund_code: str = Query(..., min_length=6, max_length=6, description="6 位基金代码"),
    page_index: int = Query(1, ge=1, le=5000),
    page_size: int = Query(50, ge=5, le=200),
    start_date: str | None = Query(
        None,
        description="与 end_date 同时传：按区间拉全量（YYYY-MM-DD）；不传则单页模式",
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    ),
    end_date: str | None = Query(
        None,
        description="与 start_date 同时传：按区间拉全量（YYYY-MM-DD）",
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    ),
    _user: User = Depends(get_current_user),
):
    """
    服务端代拉 `https://api.fund.eastmoney.com/f10/lsjz`（带 Referer，避免浏览器跨域与 403）。
    传 `start_date`+`end_date` 时按日期区间自动翻页，并启用 **内存缓存与尾部增量合并**（减少重复全量翻页）。
    否则使用 `page_index`/`page_size` 单页兼容（不走区间缓存）。
    返回 `points_asc`：日期升序，字段 date / dwjz，可直接喂 ECharts `time` 轴。
    """
    data = fetch_lsjz_eastmoney_json_api_cached(
        fund_code,
        page_index=page_index,
        page_size=page_size,
        start_date=start_date,
        end_date=end_date,
    )
    return success_response(data=data, message="ok" if data.get("ok") else (data.get("error") or "failed"))


@router.websocket("/ws/lsjz-json")
async def websocket_lsjz_json(websocket: WebSocket) -> None:
    """
    单次查询可走 HTTP；切换基金/区间频繁时可用 WebSocket，避免重复 TCP/TLS 握手。
    认证：`query token=<JWT>`（与 REST Bearer 同源）。

    客户端文本帧 JSON::

        {"action":"get","fund_code":"510300","start_date":"2025-01-01","end_date":"2026-04-17"}

    服务端返回 JSON：`{"type":"lsjz","payload":{...}}`（payload 与 HTTP data 字段结构一致）。
    """
    await websocket.accept()
    token = (websocket.query_params.get("token") or "").strip()
    try:
        decode_access_token(token)
    except Exception:
        await websocket.close(code=4401)
        return

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                body = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "invalid_json"})
                continue
            if body.get("action") != "get":
                await websocket.send_json({"type": "error", "message": "unsupported_action"})
                continue
            fc = str(body.get("fund_code") or "").strip()
            sd = body.get("start_date")
            ed = body.get("end_date")
            if not fc or not sd or not ed:
                await websocket.send_json({"type": "error", "message": "fund_code+start_date+end_date_required"})
                continue
            payload = fetch_lsjz_eastmoney_json_api_cached(
                fc,
                page_index=1,
                page_size=200,
                start_date=str(sd),
                end_date=str(ed),
            )
            await websocket.send_json({"type": "lsjz", "payload": payload})
    except WebSocketDisconnect:
        logger.debug("lsjz websocket disconnected")
