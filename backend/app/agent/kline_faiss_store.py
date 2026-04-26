from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any

import numpy as np
import pandas as pd

from app.agent.kline_feature_builder import (
    KlineWindowFeature,
    build_latest_query_feature,
    build_latest_query_feature_from_nav_rows,
    load_window_features_from_offline_db,
)
from app.core.config import settings
from app.modules.fund_offline.query_queue import run_serial_db_task
from app.modules.fund_offline.session import OfflineSessionLocal

logger = logging.getLogger(__name__)

try:
    import faiss  # type: ignore
except Exception:  # pragma: no cover
    faiss = None

_INDEX = None
_META: list[dict[str, Any]] = []
_VERSION: dict[str, Any] = {}
_LOCK = Lock()
def _is_sqlite_locked_error(exc: Exception) -> bool:
    msg = str(exc or "").lower()
    return "database is locked" in msg or "sqlite3.operationalerror" in msg




def _path(p: str) -> Path:
    x = Path(p)
    if not x.is_absolute():
        x = Path.cwd() / x
    x.parent.mkdir(parents=True, exist_ok=True)
    return x


def _index_path() -> Path:
    return _path(settings.kline_faiss_index_path)


def _meta_path() -> Path:
    return _path(settings.kline_faiss_meta_path)


def _version_path() -> Path:
    return _path(settings.kline_faiss_version_path)


def _write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def _write_text_atomic(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _features_to_matrix(features: list[KlineWindowFeature]) -> tuple[np.ndarray, list[dict[str, Any]]]:
    if not features:
        return np.zeros((0, int(settings.kline_paa_dims)), dtype=np.float32), []
    mat = np.vstack([f.vector for f in features]).astype(np.float32)
    meta = [
        {
            "code": f.code,
            "start_date": f.start_date,
            "end_date": f.end_date,
            "fwd_return_5d": f.fwd_return_5d,
            "fwd_return_10d": f.fwd_return_10d,
            "fwd_return_20d": f.fwd_return_20d,
        }
        for f in features
    ]
    return mat, meta


def _write_meta(meta_path: Path, meta: list[dict[str, Any]]) -> str:
    """
    优先 parquet，失败回退 jsonl（超低配环境未装 pyarrow 也可运行）。
    返回实际落盘格式。
    """
    df = pd.DataFrame(meta)
    if meta_path.suffix.lower() == ".parquet":
        try:
            tmp = meta_path.with_suffix(meta_path.suffix + ".tmp")
            df.to_parquet(tmp, index=False)
            tmp.replace(meta_path)
            return "parquet"
        except Exception:
            jsonl_path = meta_path.with_suffix(".jsonl")
            _write_text_atomic(jsonl_path, "\n".join(json.dumps(m, ensure_ascii=False) for m in meta))
            return "jsonl_fallback"
    _write_text_atomic(meta_path, "\n".join(json.dumps(m, ensure_ascii=False) for m in meta))
    return "jsonl"


def build_and_persist_index(*, max_codes: int | None = None) -> dict[str, Any]:
    if faiss is None:
        return {"ok": False, "error": "faiss_not_installed"}
    features = load_window_features_from_offline_db(max_codes=max_codes)
    mat, meta = _features_to_matrix(features)
    dim = int(settings.kline_paa_dims)
    idx = faiss.IndexFlatIP(dim)
    if len(mat):
        idx.add(mat)

    index_path = _index_path()
    meta_path = _meta_path()
    version_path = _version_path()
    faiss.write_index(idx, str(index_path) + ".tmp")
    Path(str(index_path) + ".tmp").replace(index_path)

    meta_format = _write_meta(meta_path, meta)
    version = {
        "built_at": datetime.utcnow().isoformat(),
        "vector_count": int(len(meta)),
        "dim": dim,
        "window_size_days": int(settings.kline_window_size_days),
        "meta_path": str(meta_path),
        "meta_format": meta_format,
        "index_path": str(index_path),
    }
    _write_text_atomic(version_path, json.dumps(version, ensure_ascii=False, indent=2))

    with _LOCK:
        global _INDEX, _META, _VERSION
        _INDEX = idx
        _META = meta
        _VERSION = version
    return {"ok": True, **version}


def _load_meta_file(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        alt = path.with_suffix(".jsonl")
        if not alt.exists():
            return []
        path = alt
    if path.suffix.lower() == ".parquet":
        try:
            df = pd.read_parquet(path)
            rows = df.to_dict(orient="records")
            return [dict(r) for r in rows if isinstance(r, dict)]
        except Exception:
            alt = path.with_suffix(".jsonl")
            if alt.exists():
                path = alt
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            obj = json.loads(s)
        except Exception:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def load_index_from_disk(force: bool = False) -> bool:
    if faiss is None:
        return False
    with _LOCK:
        global _INDEX, _META, _VERSION
        if _INDEX is not None and not force:
            return True
        index_path = _index_path()
        meta_path = _meta_path()
        version_path = _version_path()
        meta_exists = meta_path.exists() or meta_path.with_suffix(".jsonl").exists()
        if not index_path.exists() or not meta_exists:
            return False
        _INDEX = faiss.read_index(str(index_path))
        _META = _load_meta_file(meta_path)
        if version_path.exists():
            try:
                _VERSION = json.loads(version_path.read_text(encoding="utf-8"))
            except Exception:
                _VERSION = {}
        else:
            _VERSION = {}
        return True


def get_index_version() -> dict[str, Any]:
    with _LOCK:
        if _VERSION:
            return dict(_VERSION)
    version_path = _version_path()
    if version_path.exists():
        try:
            return json.loads(version_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def search_similar(query_vec: np.ndarray, top_k: int = 5) -> list[dict[str, Any]]:
    if not load_index_from_disk():
        return []
    with _LOCK:
        idx = _INDEX
        meta = list(_META)
    if idx is None:
        return []
    q = np.array(query_vec, dtype=np.float32).reshape(1, -1)
    sims, ids = idx.search(q, max(1, int(top_k)))
    out: list[dict[str, Any]] = []
    for i in range(min(len(ids[0]), top_k)):
        pos = int(ids[0][i])
        if pos < 0 or pos >= len(meta):
            continue
        row = dict(meta[pos])
        row["similarity"] = float(sims[0][i])
        out.append(row)
    return out


def query_latest_fund_windows(code: str, top_k: int = 5, nav_rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    if nav_rows:
        query_vec, qmeta = build_latest_query_feature_from_nav_rows(code, nav_rows)
    else:
        query_vec, qmeta = None, None
        last_err: Exception | None = None

        def _read_latest_feature_from_db() -> tuple[np.ndarray | None, dict[str, Any] | None]:
            db = OfflineSessionLocal()
            try:
                return build_latest_query_feature(db, code)
            finally:
                db.close()

        for i in range(3):
            try:
                query_vec, qmeta = run_serial_db_task(
                    _read_latest_feature_from_db,
                    task_name=f"query_latest_fund_windows:{code}",
                    timeout_sec=35.0,
                )
                last_err = None
                break
            except Exception as e:  # noqa: BLE001
                last_err = e
                if not _is_sqlite_locked_error(e):
                    logger.debug("build_latest_query_feature failed: code=%s", code, exc_info=True)
                    break
                time.sleep(0.08 * (2**i))
        if last_err is not None and _is_sqlite_locked_error(last_err):
            return {"ok": False, "error": "sqlite_locked", "matches": [], "query": None}
    if query_vec is None or qmeta is None:
        return {"ok": False, "error": "data_not_ready", "matches": [], "query": None}
    matches = search_similar(query_vec, top_k=top_k + 2)
    filtered = [m for m in matches if str(m.get("code") or "") != code][:top_k]
    return {"ok": bool(filtered), "error": None if filtered else "no_matches", "matches": filtered, "query": qmeta}
