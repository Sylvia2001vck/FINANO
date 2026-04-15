"""Pandas 相似基金（演示基金池）：基于多维风险收益特征余弦相似度。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.agent.fund_catalog import get_fund_by_code, list_funds_catalog_only


def similar_funds(code: str, top_k: int = 5) -> list[dict]:
    target = get_fund_by_code(code.strip(), include_live=False)
    if not target:
        return []
    others = [dict(f) for f in list_funds_catalog_only() if f["code"] != target["code"]]
    if not others:
        return []

    df = pd.DataFrame(others)
    df["inv_dd"] = 1.0 - df["max_drawdown_3y"].astype(float)
    df["log_aum"] = np.log1p(df["aum_billion"].astype(float))

    cols = ["sharpe_3y", "momentum_60d", "inv_dd", "risk_rating", "log_aum"]
    mat = df[cols].to_numpy(dtype=float)
    tvec = np.array(
        [
            float(target["sharpe_3y"]),
            float(target["momentum_60d"]),
            1.0 - float(target["max_drawdown_3y"]),
            float(target["risk_rating"]),
            np.log1p(float(target["aum_billion"])),
        ],
        dtype=float,
    ).reshape(1, -1)

    stacked = np.vstack([tvec, mat])
    mean = stacked.mean(axis=0)
    std = stacked.std(axis=0) + 1e-9
    t_norm = (tvec - mean) / std
    m_norm = (mat - mean) / std
    denom = np.linalg.norm(m_norm, axis=1) * np.linalg.norm(t_norm) + 1e-9
    sims = (m_norm * t_norm).sum(axis=1) / denom
    df["_sim"] = sims

    top = df.nlargest(min(top_k, len(df)), "_sim")
    out: list[dict] = []
    for _, row in top.iterrows():
        out.append(
            {
                "code": row["code"],
                "name": row["name"],
                "track": row["track"],
                "similarity": round(float(row["_sim"]), 4),
                "rationale": (
                    f"与「{target['name']}」在夏普、60 日动量、回撤、风险等级与规模（对数）"
                    "归一化后的统计距离较近（演示池，非行情序列拟合）。"
                ),
            }
        )
    return out
