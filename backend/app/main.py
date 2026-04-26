from contextlib import asynccontextmanager
import json
from pathlib import Path
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware

from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.responses import success_response
from app.db.base import Base
from app.db.legacy_cleanup import drop_legacy_comments_table
from app.db.trade_columns import ensure_trade_lifecycle_columns
from app.db.user_columns import ensure_user_birth_time_slot_column
from app.db.session import SessionLocal, engine
from app.modules.agent.router import router as mafb_router
from app.modules.ai.router import router as ai_router
from app.modules.community.router import router as community_router
from app.modules.fund_nav.router import router as fund_nav_router
from app.modules.fund_nav.service import start_fund_snapshot_scheduler
from app.modules.fund_offline.router import router as fund_offline_router
from app.modules.fund_offline.service import start_offline_sync_scheduler
from app.modules.hot.router import router as hot_router
from app.modules.hot.service import bootstrap_hot_news, start_hot_scheduler
from app.modules.note.router import router as note_router
from app.modules.ocr.router import router as ocr_router
from app.modules.replay.router import router as replay_router
from app.modules.trade.router import router as trade_router
from app.modules.user.router import router as auth_router
from app.modules.user.router import user_router
from app.modules.user.router_fbti import router as fbti_user_router
from app.agent.kline_faiss_store import load_index_from_disk

from app.modules.community import models as _community_models  # noqa: F401
from app.modules.agent import models as _agent_models  # noqa: F401
from app.modules.hot import models as _hot_models  # noqa: F401
from app.modules.note import models as _note_models  # noqa: F401
from app.modules.replay import models as _replay_models  # noqa: F401
from app.modules.fund_nav import models as _fund_nav_models  # noqa: F401
from app.modules.trade import models as _trade_models  # noqa: F401
from app.modules.user import models as _user_models  # noqa: F401


_DEBUG_LOG_PATH = Path(__file__).resolve().parents[2] / "debug-464a77.log"


def _debug_log(hypothesis_id: str, location: str, message: str, data: dict | None = None, run_id: str = "pre-fix") -> None:
    rec = {
        "sessionId": "464a77",
        "runId": run_id,
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data or {},
        "timestamp": int(time.time() * 1000),
    }
    try:
        with _DEBUG_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


@asynccontextmanager
async def lifespan(_: FastAPI):
    # region agent log
    _debug_log(
        "H1",
        "backend/app/main.py:58",
        "lifespan_start",
        {"database_url_prefix": settings.database_url.split("://", 1)[0], "catalog_mode": settings.fund_catalog_mode},
    )
    # endregion
    Base.metadata.create_all(bind=engine)
    # region agent log
    _debug_log("H2", "backend/app/main.py:67", "metadata_create_all_done")
    # endregion
    ensure_trade_lifecycle_columns(engine)
    ensure_user_birth_time_slot_column(engine)
    drop_legacy_comments_table(engine)
    db = SessionLocal()
    try:
        # region agent log
        _debug_log("H1", "backend/app/main.py:73", "bootstrap_hot_news_start")
        # endregion
        bootstrap_hot_news(db)
        # region agent log
        _debug_log("H1", "backend/app/main.py:77", "bootstrap_hot_news_done")
        # endregion
        # region agent log
        _debug_log("H1", "backend/app/main.py:80", "bootstrap_fund_snapshot_start")
        # endregion
        # Startup must not block on full snapshot refresh (can take minutes with network I/O).
        # Scheduler thread will perform refresh asynchronously after app is ready.
        # region agent log
        _debug_log("H1", "backend/app/main.py:84", "bootstrap_fund_snapshot_skipped_sync")
        # endregion
    except Exception as e:
        # region agent log
        _debug_log("H2", "backend/app/main.py:88", "startup_bootstrap_exception", {"error": str(e)})
        # endregion
        raise
    finally:
        db.close()
    stop_event, scheduler_thread = start_hot_scheduler(SessionLocal)
    fund_stop_event, fund_scheduler_thread = start_fund_snapshot_scheduler(SessionLocal)
    offline_stop_event, offline_scheduler_thread = start_offline_sync_scheduler()
    try:
        load_index_from_disk(force=False)
    except Exception:
        _debug_log("H2", "backend/app/main.py:faiss_load", "kline_faiss_load_failed")
    # region agent log
    _debug_log(
        "H1",
        "backend/app/main.py:97",
        "lifespan_ready_before_yield",
        {"hot_scheduler": bool(scheduler_thread), "fund_scheduler": bool(fund_scheduler_thread)},
    )
    # endregion
    yield
    # region agent log
    _debug_log("H3", "backend/app/main.py:104", "lifespan_shutdown_start")
    # endregion
    if stop_event is not None:
        stop_event.set()
    if scheduler_thread is not None:
        scheduler_thread.join(timeout=2.0)
    if fund_stop_event is not None:
        fund_stop_event.set()
    if fund_scheduler_thread is not None:
        fund_scheduler_thread.join(timeout=2.0)
    if offline_stop_event is not None:
        offline_stop_event.set()
    if offline_scheduler_thread is not None:
        offline_scheduler_thread.join(timeout=2.0)


app = FastAPI(
    title=settings.project_name,
    version="1.0.0",
    lifespan=lifespan,
    # 显式固定文档路径（避免个别环境/代理下默认路由未挂载的困惑）
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# 大 JSON（净值列表）gzip 后显著减小体积；Protobuf 可作为后续二进制协议再加
app.add_middleware(GZipMiddleware, minimum_size=800)
register_exception_handlers(app)

app.include_router(auth_router, prefix=settings.api_v1_prefix)
app.include_router(user_router, prefix=settings.api_v1_prefix)
app.include_router(fbti_user_router, prefix=settings.api_v1_prefix)
app.include_router(trade_router, prefix=settings.api_v1_prefix)
app.include_router(note_router, prefix=settings.api_v1_prefix)
app.include_router(ai_router, prefix=settings.api_v1_prefix)
app.include_router(replay_router, prefix=settings.api_v1_prefix)
app.include_router(mafb_router, prefix=settings.api_v1_prefix)
app.include_router(ocr_router, prefix=settings.api_v1_prefix)
app.include_router(hot_router, prefix=settings.api_v1_prefix)
app.include_router(community_router, prefix=settings.api_v1_prefix)
app.include_router(fund_nav_router, prefix=settings.api_v1_prefix)
app.include_router(fund_offline_router, prefix=settings.api_v1_prefix)


@app.get("/")
def root():
    return success_response(
        data={
            "project": settings.project_name,
            "docs": "/docs",
            "api_prefix": settings.api_v1_prefix,
        },
        message="Finano backend is running",
    )
