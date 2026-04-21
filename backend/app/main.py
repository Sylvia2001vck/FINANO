from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware

from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.responses import success_response
from app.db.base import Base
from app.db.legacy_cleanup import drop_legacy_comments_table
from app.db.trade_columns import ensure_trade_lifecycle_columns
from app.db.session import SessionLocal, engine
from app.modules.agent.router import router as mafb_router
from app.modules.ai.router import router as ai_router
from app.modules.community.router import router as community_router
from app.modules.fund_nav.router import router as fund_nav_router
from app.modules.hot.router import router as hot_router
from app.modules.hot.service import bootstrap_hot_news, start_hot_scheduler
from app.modules.note.router import router as note_router
from app.modules.ocr.router import router as ocr_router
from app.modules.trade.router import router as trade_router
from app.modules.user.router import router as auth_router
from app.modules.user.router import user_router
from app.modules.user.router_fbti import router as fbti_user_router

from app.modules.community import models as _community_models  # noqa: F401
from app.modules.hot import models as _hot_models  # noqa: F401
from app.modules.note import models as _note_models  # noqa: F401
from app.modules.trade import models as _trade_models  # noqa: F401
from app.modules.user import models as _user_models  # noqa: F401


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_trade_lifecycle_columns(engine)
    drop_legacy_comments_table(engine)
    db = SessionLocal()
    try:
        bootstrap_hot_news(db)
    finally:
        db.close()
    stop_event, scheduler_thread = start_hot_scheduler(SessionLocal)
    yield
    if stop_event is not None:
        stop_event.set()
    if scheduler_thread is not None:
        scheduler_thread.join(timeout=2.0)


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
app.include_router(mafb_router, prefix=settings.api_v1_prefix)
app.include_router(ocr_router, prefix=settings.api_v1_prefix)
app.include_router(hot_router, prefix=settings.api_v1_prefix)
app.include_router(community_router, prefix=settings.api_v1_prefix)
app.include_router(fund_nav_router, prefix=settings.api_v1_prefix)


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
