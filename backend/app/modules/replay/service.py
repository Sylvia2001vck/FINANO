from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from hashlib import sha256
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.fund_catalog import get_fund_by_code
from app.core.config import settings
from app.core.dashscope_setup import apply_dashscope_settings
from app.core.exceptions import APIException
from app.modules.note.models import Note
from app.modules.replay.models import ReflectionEmbedding, TradeCurveFeature
from app.modules.replay.schemas import (
    ReplayAnalyzeResult,
    ReplayAnalyzeNotePayload,
    ReplayMatchedNote,
    ReplayMatchedTrade,
)
from app.modules.trade.models import Trade
from app.services.fund_data import fetch_lsjz_eastmoney_json_api_cached

try:
    import faiss  # type: ignore
except Exception:  # pragma: no cover
    faiss = None

try:
    import dashscope
except Exception:  # pragma: no cover
    dashscope = None


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def _short(text: str, n: int = 120) -> str:
    t = (text or "").strip()
    return t if len(t) <= n else t[: n - 1] + "…"


def _normalize_vec(vec: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(vec)
    if n <= 1e-12:
        return vec
    return vec / n


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    m = min(len(a), len(b))
    va = np.array(a[:m], dtype=np.float32)
    vb = np.array(b[:m], dtype=np.float32)
    na = float(np.linalg.norm(va))
    nb = float(np.linalg.norm(vb))
    if na <= 1e-12 or nb <= 1e-12:
        return 0.0
    score = float(np.dot(va, vb) / (na * nb))
    return max(0.0, min(1.0, (score + 1.0) / 2.0))


def _parse_embedding_json(raw: str) -> list[float]:
    try:
        arr = json.loads(raw or "[]")
        if isinstance(arr, list):
            return [float(x) for x in arr]
    except Exception:
        pass
    return []


def _pseudo_embedding(text: str, dim: int = 256) -> list[float]:
    vec = np.zeros((dim,), dtype=np.float32)
    payload = (text or "").encode("utf-8", errors="ignore")
    if not payload:
        return vec.tolist()
    for i, b in enumerate(payload):
        vec[(i * 131 + b) % dim] += ((b % 17) + 1) / 17.0
    dig = sha256(payload).digest()
    for i, b in enumerate(dig):
        vec[(i * 13 + b) % dim] += (b / 255.0) * 0.25
    return _normalize_vec(vec).tolist()


def _embed_text(text: str) -> tuple[list[float], str]:
    clean = (text or "").strip()
    if not clean:
        return [], settings.replay_embedding_model
    if not settings.dashscope_api_key or dashscope is None:
        return _pseudo_embedding(clean), "local-pseudo"
    try:
        apply_dashscope_settings(dashscope)
        resp = dashscope.TextEmbedding.call(
            model=settings.replay_embedding_model,
            input=clean,
        )
        emb = None
        output = getattr(resp, "output", None)
        if isinstance(output, dict):
            emb_rows = output.get("embeddings") or []
            if emb_rows:
                emb = emb_rows[0].get("embedding")
        else:
            emb_rows = getattr(output, "embeddings", None) or []
            if emb_rows:
                first = emb_rows[0]
                emb = first.get("embedding") if isinstance(first, dict) else getattr(first, "embedding", None)
        if emb and isinstance(emb, list):
            vec = np.array([float(x) for x in emb], dtype=np.float32)
            vec = _normalize_vec(vec)
            return vec.tolist(), settings.replay_embedding_model
    except Exception:
        pass
    return _pseudo_embedding(clean), "local-pseudo"


def _amount_bucket(x: float) -> str:
    v = abs(float(x))
    if v < 1000:
        return "1千以内"
    if v < 10000:
        return "1千-1万"
    if v < 50000:
        return "1万+"
    if v < 100000:
        return "5万+"
    if v < 500000:
        return "10万+"
    return "50万+"


def _relative_date(v: Any) -> str:
    if not v:
        return "未知时间"
    if isinstance(v, datetime):
        d = v.date()
    elif isinstance(v, date):
        d = v
    else:
        try:
            d = datetime.fromisoformat(str(v)[:10]).date()
        except Exception:
            return "未知时间"
    days = (date.today() - d).days
    if days < 30:
        return "近一个月"
    if days < 90:
        return "近三个月"
    if days < 365:
        return "近一年"
    years = max(1, round(days / 365))
    return f"{years}年前"


def _industry_from_symbol(symbol: str) -> str:
    hit = get_fund_by_code(symbol, include_live=False) or {}
    for key in ("track", "type"):
        val = str(hit.get(key) or "").strip()
        if val:
            return val[:20]
    return "公募基金"


def _build_trade_curve(symbol: str, trade_date: date | None) -> list[float]:
    end_date = trade_date or date.today()
    start = (end_date - timedelta(days=45)).isoformat()
    end = end_date.isoformat()
    payload = fetch_lsjz_eastmoney_json_api_cached(
        symbol,
        start_date=start,
        end_date=end,
        timeout=12.0,
    )
    pts = list(payload.get("points_asc") or [])
    seq: list[float] = []
    for p in pts[-30:]:
        x = p.get("dwjz")
        try:
            seq.append(float(x))
        except Exception:
            continue
    if not seq:
        return []
    base = seq[0] if seq[0] else 1.0
    norm = [(v / base) - 1.0 for v in seq]
    return norm


def upsert_trade_curve_feature(db: Session, user_id: int, trade: Trade) -> None:
    seq = _build_trade_curve(str(trade.symbol or "").strip(), trade.buy_date or trade.trade_date)
    if not seq:
        return
    sig = ",".join(f"{v:.4f}" for v in seq[-8:])
    row = db.scalar(
        select(TradeCurveFeature).where(
            TradeCurveFeature.user_id == user_id,
            TradeCurveFeature.trade_id == trade.id,
        )
    )
    if row is None:
        row = TradeCurveFeature(
            user_id=user_id,
            trade_id=trade.id,
            symbol=trade.symbol,
            nav30_json=json.dumps(seq, ensure_ascii=False),
            curve_signature=sig,
        )
        db.add(row)
    else:
        row.symbol = trade.symbol
        row.nav30_json = json.dumps(seq, ensure_ascii=False)
        row.curve_signature = sig
    db.commit()


def upsert_note_embedding(db: Session, user_id: int, note: Note) -> None:
    text = f"{note.title}\n{note.content}"
    vec, model = _embed_text(text)
    if not vec:
        return
    row = db.scalar(
        select(ReflectionEmbedding).where(
            ReflectionEmbedding.user_id == user_id,
            ReflectionEmbedding.note_id == note.id,
        )
    )
    if row is None:
        row = ReflectionEmbedding(
            user_id=user_id,
            note_id=note.id,
            model=model,
            dim=len(vec),
            embedding_json=json.dumps(vec, ensure_ascii=False),
        )
        db.add(row)
    else:
        row.model = model
        row.dim = len(vec)
        row.embedding_json = json.dumps(vec, ensure_ascii=False)
    db.commit()


def _mask_trade_for_prompt(trade: Trade) -> dict[str, Any]:
    return {
        "symbol_industry": _industry_from_symbol(str(trade.symbol or "")),
        "name": _short(str(trade.name or "")),
        "direction": str(getattr(trade.direction, "value", trade.direction) or ""),
        "trade_time": _relative_date(trade.trade_date),
        "amount_level": _amount_bucket(_safe_float(trade.amount)),
        "profit_level": _amount_bucket(_safe_float(trade.profit)),
        "notes": _short(str(trade.notes or ""), 200),
    }


def _mask_note_for_prompt(note: Note) -> dict[str, Any]:
    return {
        "title": _short(note.title, 80),
        "content": _short(note.content, 300),
        "time": _relative_date(note.created_at),
    }


def _get_user_trade(db: Session, user_id: int, trade_id: int) -> Trade:
    trade = db.scalar(select(Trade).where(Trade.id == trade_id, Trade.user_id == user_id))
    if not trade:
        raise APIException(code=20002, message="交易记录不存在", status_code=404)
    return trade


def _llm_replay_analysis(
    intent: str,
    route: str,
    current_masked: dict[str, Any],
    matched_trades: list[ReplayMatchedTrade],
    matched_notes: list[ReplayMatchedNote],
) -> tuple[str, list[str]]:
    if not settings.dashscope_api_key or dashscope is None:
        if route == "history_compare":
            msg = "历史存在相似样本：建议优先复盘当时执行纪律与情绪变化，先验证是否重复同类偏差，再决定是否加减仓。"
            return msg, ["先对比当时心得与当前触发点", "把仓位与止损阈值写成规则", "避免在高波动时临时改计划"]
        return (
            "未命中高相似历史样本：本次以原生分析给出中性复盘建议，重点关注仓位、纪律和情绪触发。",
            ["记录本次入场/离场依据", "定义可执行的止盈止损条件", "下一次出现同信号时按规则执行"],
        )

    apply_dashscope_settings(dashscope)
    system_prompt = (
        "你是基金交易复盘助手。必须基于脱敏数据给出对比结论，不承诺收益，不给具体买卖点。"
        "输出 JSON：{\"analysis\": string, \"suggestions\": string[3]}。"
    )
    payload = {
        "intent": intent,
        "route": route,
        "current": current_masked,
        "matched_trades": [m.model_dump() for m in matched_trades[:3]],
        "matched_notes": [m.model_dump() for m in matched_notes[:3]],
    }
    user_prompt = (
        "请基于脱敏数据做复盘：对比“现在”和“历史相似时刻”，说明差异与共性，给出温和且可执行建议。\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )
    try:
        resp = dashscope.Generation.call(
            model=settings.dashscope_finance_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            result_format="message",
            temperature=0.2,
            max_tokens=700,
        )
        content = resp.output.choices[0].message.content
        if isinstance(content, dict):
            analysis = str(content.get("analysis") or "").strip()
            suggestions = [str(x) for x in (content.get("suggestions") or []) if str(x).strip()]
            if analysis:
                return analysis, suggestions[:3]
        parsed = json.loads(content) if isinstance(content, str) else {}
        analysis = str(parsed.get("analysis") or "").strip()
        suggestions = [str(x) for x in (parsed.get("suggestions") or []) if str(x).strip()]
        if analysis:
            return analysis, suggestions[:3]
    except Exception:
        pass
    return (
        "模型未稳定返回结构化复盘，本次采用回退建议：先固定纪律，再观察是否重演历史行为偏差。",
        ["减少情绪驱动操作", "将复盘要点写入下次交易前检查清单", "优先执行预设仓位管理规则"],
    )


def analyze_replay_by_trade(db: Session, user_id: int, trade_id: int) -> ReplayAnalyzeResult:
    trace: list[str] = ["intent=trade", "retriever=sql+curve"]
    trade = _get_user_trade(db, user_id, trade_id)
    try:
        upsert_trade_curve_feature(db, user_id, trade)
    except Exception:
        trace.append("curve_feature=current_trade_upsert_failed")

    candidates = list(
        db.scalars(
            select(Trade)
            .where(
                Trade.user_id == user_id,
                Trade.symbol == trade.symbol,
                Trade.id != trade.id,
            )
            .order_by(Trade.trade_date.desc(), Trade.id.desc())
            .limit(max(6, settings.replay_top_k * 3))
        )
    )
    note_map: dict[int, list[str]] = {}
    if candidates:
        cand_ids = [t.id for t in candidates]
        rows = list(
            db.scalars(
                select(Note)
                .where(Note.user_id == user_id, Note.trade_id.in_(cand_ids))
                .order_by(Note.created_at.desc())
            )
        )
        for n in rows:
            tid = int(n.trade_id or 0)
            if tid > 0:
                note_map.setdefault(tid, []).append(_short(n.content, 120))

    feature_rows = list(
        db.scalars(
            select(TradeCurveFeature).where(
                TradeCurveFeature.user_id == user_id,
                TradeCurveFeature.trade_id.in_([trade.id] + [x.id for x in candidates]),
            )
        )
    )
    by_trade_id = {int(r.trade_id): r for r in feature_rows}
    cur_row = by_trade_id.get(trade.id)
    cur_seq = _parse_embedding_json(cur_row.nav30_json) if cur_row else []

    matched: list[ReplayMatchedTrade] = []
    for t in candidates:
        row = by_trade_id.get(t.id)
        seq = _parse_embedding_json(row.nav30_json) if row else []
        curve_score = _cosine(cur_seq, seq) if cur_seq and seq else 0.0
        score = max(0.0, min(1.0, 0.58 + 0.42 * curve_score))
        matched.append(
            ReplayMatchedTrade(
                trade_id=t.id,
                symbol=t.symbol,
                name=t.name,
                trade_date=t.trade_date.isoformat(),
                amount=_safe_float(t.amount),
                profit=_safe_float(t.profit),
                similarity=round(score, 4),
                notes=(note_map.get(t.id) or [])[:3],
            )
        )
    matched.sort(key=lambda x: x.similarity, reverse=True)
    matched = matched[: settings.replay_top_k]
    top_score = float(matched[0].similarity) if matched else 0.0
    threshold = float(settings.replay_similarity_threshold)
    has_match = bool(matched and top_score >= threshold)
    route = "history_compare" if has_match else "native_analysis"
    trace.append(f"top_score={top_score:.4f}")
    trace.append(f"route={route}")

    analysis, suggestions = _llm_replay_analysis(
        "trade",
        route,
        _mask_trade_for_prompt(trade),
        matched,
        [],
    )
    return ReplayAnalyzeResult(
        intent="trade",
        route=route,
        retrieval_source=("sql" if matched else "none"),
        top_score=round(top_score, 4),
        similarity_threshold=threshold,
        has_match=has_match,
        analysis=analysis,
        suggestions=suggestions,
        matched_trades=matched,
        matched_notes=[],
        trace=trace,
    )


def analyze_replay_by_note(db: Session, user_id: int, payload: ReplayAnalyzeNotePayload) -> ReplayAnalyzeResult:
    trace: list[str] = ["intent=note", "retriever=faiss"]
    active_note: Note | None = None
    query_title = ""
    query_content = ""

    if payload.note_id:
        active_note = db.scalar(select(Note).where(Note.user_id == user_id, Note.id == payload.note_id))
    if active_note:
        query_title = active_note.title
        query_content = active_note.content
    else:
        query_title = (payload.title or "即时复盘").strip()
        query_content = (payload.content or "").strip()
    query_text = f"{query_title}\n{query_content}".strip()
    query_vec, _ = _embed_text(query_text)
    if not query_vec:
        query_vec = _pseudo_embedding(query_text)

    all_notes = list(
        db.scalars(
            select(Note)
            .where(Note.user_id == user_id)
            .order_by(Note.created_at.desc())
            .limit(300)
        )
    )
    if not all_notes:
        analysis, suggestions = _llm_replay_analysis(
            "note",
            "native_analysis",
            {"title": _short(query_title), "content": _short(query_content, 280)},
            [],
            [],
        )
        return ReplayAnalyzeResult(
            intent="note",
            route="native_analysis",
            retrieval_source="none",
            top_score=0.0,
            similarity_threshold=float(settings.replay_similarity_threshold),
            has_match=False,
            analysis=analysis,
            suggestions=suggestions,
            matched_trades=[],
            matched_notes=[],
            trace=trace + ["no_notes_history"],
        )

    note_ids = [n.id for n in all_notes]
    emb_rows = list(
        db.scalars(
            select(ReflectionEmbedding).where(
                ReflectionEmbedding.user_id == user_id,
                ReflectionEmbedding.note_id.in_(note_ids),
            )
        )
    )
    emb_map = {int(r.note_id): r for r in emb_rows}
    for n in all_notes:
        if n.id not in emb_map:
            try:
                upsert_note_embedding(db, user_id, n)
            except Exception:
                trace.append(f"embedding_upsert_fail_note={n.id}")
    emb_rows = list(
        db.scalars(
            select(ReflectionEmbedding).where(
                ReflectionEmbedding.user_id == user_id,
                ReflectionEmbedding.note_id.in_(note_ids),
            )
        )
    )

    cand_notes: list[Note] = []
    cand_vectors: list[list[float]] = []
    for n in all_notes:
        if active_note and n.id == active_note.id:
            continue
        row = next((r for r in emb_rows if int(r.note_id) == n.id), None)
        if not row:
            continue
        vec = _parse_embedding_json(row.embedding_json)
        if vec:
            cand_notes.append(n)
            cand_vectors.append(vec)

    matched_notes: list[ReplayMatchedNote] = []
    if cand_vectors:
        q = _normalize_vec(np.array(query_vec, dtype=np.float32))
        mats = np.array(cand_vectors, dtype=np.float32)
        mats = np.vstack([_normalize_vec(v) for v in mats]).astype(np.float32)
        if settings.replay_enable_faiss and faiss is not None:
            idx = faiss.IndexFlatIP(mats.shape[1])
            idx.add(mats)
            k = min(settings.replay_top_k, mats.shape[0])
            sims, ids = idx.search(q.reshape(1, -1), k)
            ranked = [(int(ids[0][i]), float(sims[0][i])) for i in range(k) if int(ids[0][i]) >= 0]
            trace.append("faiss=on")
        else:
            scores = mats @ q.reshape(-1, 1)
            ranked_idx = np.argsort(scores.reshape(-1))[::-1][: settings.replay_top_k]
            ranked = [(int(i), float(scores[i][0])) for i in ranked_idx]
            trace.append("faiss=off_fallback_numpy")

        trade_ids = [int(n.trade_id) for n in cand_notes if n.trade_id]
        trade_map = {t.id: t for t in db.scalars(select(Trade).where(Trade.id.in_(trade_ids), Trade.user_id == user_id))}
        for idx, ip_score in ranked:
            n = cand_notes[idx]
            t = trade_map.get(int(n.trade_id or 0))
            sim = max(0.0, min(1.0, (ip_score + 1.0) / 2.0))
            matched_notes.append(
                ReplayMatchedNote(
                    note_id=n.id,
                    title=n.title,
                    content_preview=_short(n.content, 140),
                    created_at=n.created_at.isoformat(),
                    similarity=round(sim, 4),
                    trade_id=(t.id if t else None),
                    trade_symbol=(t.symbol if t else None),
                    trade_profit=(_safe_float(t.profit) if t else None),
                )
            )

    top_score = float(matched_notes[0].similarity) if matched_notes else 0.0
    threshold = float(settings.replay_similarity_threshold)
    has_match = bool(matched_notes and top_score >= threshold)
    route = "history_compare" if has_match else "native_analysis"
    trace.append(f"top_score={top_score:.4f}")
    trace.append(f"route={route}")

    analysis, suggestions = _llm_replay_analysis(
        "note",
        route,
        {"title": _short(query_title), "content": _short(query_content, 280)},
        [],
        matched_notes,
    )
    return ReplayAnalyzeResult(
        intent="note",
        route=route,
        retrieval_source=("faiss" if matched_notes else "none"),
        top_score=round(top_score, 4),
        similarity_threshold=threshold,
        has_match=has_match,
        analysis=analysis,
        suggestions=suggestions,
        matched_trades=[],
        matched_notes=matched_notes,
        trace=trace,
    )
