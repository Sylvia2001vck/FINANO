from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.responses import success_response
from app.db.base import Base
from app.db.legacy_cleanup import drop_legacy_comments_table
from app.db.session import SessionLocal, engine
from app.modules.agent.router import router as mafb_router
from app.modules.ai.router import router as ai_router
from app.modules.community.router import router as community_router
from app.modules.hot.router import router as hot_router
from app.modules.hot.service import bootstrap_hot_news
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
    drop_legacy_comments_table(engine)
    db = SessionLocal()
    try:
        bootstrap_hot_news(db)
    finally:
        db.close()
    yield


app = FastAPI(title=settings.project_name, version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
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
