from pathlib import Path
from textwrap import dedent


root = Path(r"d:\FINANO\backend")
files = {
    "requirements.txt": dedent(
        """
        fastapi==0.110.0
        uvicorn==0.29.0
        sqlalchemy==2.0.29
        pymysql==1.1.0
        alembic==1.13.1
        pydantic==2.6.4
        pydantic-settings==2.2.1
        python-jose[cryptography]==3.3.0
        passlib[bcrypt]==1.7.4
        python-multipart==0.0.9
        celery==5.3.6
        redis==5.0.3
        pandas==2.2.1
        dashscope==1.18.0
        baidu-aip==4.16.10
        python-dotenv==1.0.1
        email-validator==2.1.1
        pytest==8.1.1
        httpx==0.27.0
        """
    ).strip()
    + "\n",
    "Dockerfile": dedent(
        """
        FROM python:3.11-slim

        WORKDIR /app

        COPY requirements.txt .
        RUN pip install --no-cache-dir -r requirements.txt

        COPY . .

        CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
        """
    ).strip()
    + "\n",
    "app/__init__.py": "",
    "app/core/__init__.py": "",
    "app/db/__init__.py": "",
    "app/modules/__init__.py": "",
    "app/modules/user/__init__.py": "",
    "app/modules/trade/__init__.py": "",
    "app/modules/note/__init__.py": "",
    "app/modules/ai/__init__.py": "",
    "app/modules/hot/__init__.py": "",
    "app/modules/community/__init__.py": "",
    "app/services/__init__.py": "",
    "app/utils/__init__.py": "",
    "app/core/config.py": dedent(
        """
        import json
        from typing import List

        from pydantic import Field
        from pydantic_settings import BaseSettings, SettingsConfigDict


        class Settings(BaseSettings):
            model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

            project_name: str = "Finano"
            environment: str = "development"
            api_v1_prefix: str = "/api/v1"
            debug: bool = True

            database_url: str = "sqlite:///./finano.db"
            redis_url: str = "redis://localhost:6379/0"

            secret_key: str = "change-me-in-production"
            algorithm: str = "HS256"
            access_token_expire_minutes: int = 1440

            baidu_ocr_app_id: str = ""
            baidu_ocr_api_key: str = ""
            baidu_ocr_secret_key: str = ""
            dashscope_api_key: str = ""

            cors_origins_raw: str = Field(
                default='["http://localhost:5173", "http://127.0.0.1:5173"]',
                alias="CORS_ORIGINS",
            )

            @property
            def cors_origins(self) -> List[str]:
                raw = self.cors_origins_raw.strip()
                if raw.startswith("["):
                    return json.loads(raw)
                return [item.strip() for item in raw.split(",") if item.strip()]


        settings = Settings()
        """
    ).strip()
    + "\n",
    "app/core/responses.py": dedent(
        """
        from typing import Any


        def success_response(data: Any = None, message: str = "操作成功") -> dict:
            return {
                "success": True,
                "data": data if data is not None else {},
                "message": message,
            }
        """
    ).strip()
    + "\n",
    "app/core/exceptions.py": dedent(
        """
        import logging

        from fastapi import FastAPI, Request
        from fastapi.responses import JSONResponse


        logger = logging.getLogger(__name__)


        ERROR_CODES = {
            10001: "用户不存在",
            10002: "密码错误",
            10003: "Token无效",
            20001: "OCR识别失败",
            20002: "交易数据格式错误",
            30001: "AI分析失败",
            40001: "第三方API调用失败",
        }


        class APIException(Exception):
            def __init__(self, code: int, message: str | None = None, status_code: int = 400):
                self.code = code
                self.message = message or ERROR_CODES.get(code, "未知错误")
                self.status_code = status_code
                super().__init__(self.message)


        def register_exception_handlers(app: FastAPI) -> None:
            @app.exception_handler(APIException)
            async def handle_api_exception(_: Request, exc: APIException):
                return JSONResponse(
                    status_code=exc.status_code,
                    content={
                        "success": False,
                        "data": {},
                        "message": exc.message,
                        "code": exc.code,
                    },
                )

            @app.exception_handler(Exception)
            async def handle_unexpected_exception(_: Request, exc: Exception):
                logger.exception("Unhandled server error: %s", exc)
                return JSONResponse(
                    status_code=500,
                    content={
                        "success": False,
                        "data": {},
                        "message": "服务器内部错误",
                        "code": 50000,
                    },
                )
        """
    ).strip()
    + "\n",
    "app/db/base.py": dedent(
        """
        from datetime import datetime

        from sqlalchemy import DateTime, func
        from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


        class Base(DeclarativeBase):
            pass


        class TimestampMixin:
            created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
            updated_at: Mapped[datetime] = mapped_column(
                DateTime,
                server_default=func.now(),
                onupdate=func.now(),
                nullable=False,
            )
        """
    ).strip()
    + "\n",
    "app/db/session.py": dedent(
        """
        from typing import Generator

        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session, sessionmaker

        from app.core.config import settings


        connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

        engine = create_engine(settings.database_url, future=True, pool_pre_ping=True, connect_args=connect_args)
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)


        def get_db() -> Generator[Session, None, None]:
            db = SessionLocal()
            try:
                yield db
            finally:
                db.close()
        """
    ).strip()
    + "\n",
    "app/core/security.py": dedent(
        """
        from datetime import datetime, timedelta, timezone

        from fastapi import Depends
        from fastapi.security import OAuth2PasswordBearer
        from jose import JWTError, jwt
        from passlib.context import CryptContext
        from sqlalchemy.orm import Session

        from app.core.config import settings
        from app.core.exceptions import APIException
        from app.db.session import get_db


        pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.api_v1_prefix}/auth/login")


        def verify_password(plain_password: str, hashed_password: str) -> bool:
            return pwd_context.verify(plain_password, hashed_password)


        def get_password_hash(password: str) -> str:
            return pwd_context.hash(password)


        def create_access_token(subject: str, expires_delta: timedelta | None = None) -> str:
            expire = datetime.now(timezone.utc) + (
                expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
            )
            to_encode = {"sub": subject, "exp": expire}
            return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


        def decode_access_token(token: str) -> dict:
            try:
                return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
            except JWTError as exc:
                raise APIException(code=10003, status_code=401) from exc


        def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
            from app.modules.user.models import User

            payload = decode_access_token(token)
            user_id = payload.get("sub")
            if not user_id:
                raise APIException(code=10003, status_code=401)

            user = db.get(User, int(user_id))
            if not user:
                raise APIException(code=10001, status_code=404)
            return user
        """
    ).strip()
    + "\n",
    "app/modules/user/models.py": dedent(
        """
        from sqlalchemy import String
        from sqlalchemy.orm import Mapped, mapped_column, relationship

        from app.db.base import Base, TimestampMixin


        class User(Base, TimestampMixin):
            __tablename__ = "users"

            id: Mapped[int] = mapped_column(primary_key=True, index=True)
            username: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
            email: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
            hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)

            trades = relationship("Trade", back_populates="user", cascade="all, delete-orphan")
            notes = relationship("Note", back_populates="user", cascade="all, delete-orphan")
            posts = relationship("Post", back_populates="user", cascade="all, delete-orphan")
        """
    ).strip()
    + "\n",
    "app/modules/user/schemas.py": dedent(
        """
        from datetime import datetime

        from pydantic import BaseModel, ConfigDict, EmailStr, Field


        class UserCreate(BaseModel):
            username: str = Field(min_length=3, max_length=50)
            email: EmailStr
            password: str = Field(min_length=6, max_length=50)


        class UserLogin(BaseModel):
            email: EmailStr
            password: str


        class UserRead(BaseModel):
            model_config = ConfigDict(from_attributes=True)

            id: int
            username: str
            email: EmailStr
            created_at: datetime
            updated_at: datetime


        class TokenResponse(BaseModel):
            access_token: str
            token_type: str = "bearer"
            user: UserRead
        """
    ).strip()
    + "\n",
    "app/modules/user/service.py": dedent(
        """
        from sqlalchemy import or_, select
        from sqlalchemy.orm import Session

        from app.core.exceptions import APIException
        from app.core.security import get_password_hash, verify_password
        from app.modules.user.models import User
        from app.modules.user.schemas import UserCreate


        def get_user_by_email(db: Session, email: str) -> User | None:
            return db.scalar(select(User).where(User.email == email))


        def create_user(db: Session, payload: UserCreate) -> User:
            exists = db.scalar(select(User).where(or_(User.email == payload.email, User.username == payload.username)))
            if exists:
                raise APIException(code=40001, message="用户名或邮箱已存在", status_code=409)

            user = User(
                username=payload.username,
                email=payload.email,
                hashed_password=get_password_hash(payload.password),
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            return user


        def authenticate_user(db: Session, email: str, password: str) -> User:
            user = get_user_by_email(db, email)
            if not user:
                raise APIException(code=10001, status_code=404)
            if not verify_password(password, user.hashed_password):
                raise APIException(code=10002, status_code=401)
            return user
        """
    ).strip()
    + "\n",
    "app/modules/user/router.py": dedent(
        """
        from fastapi import APIRouter, Depends
        from sqlalchemy.orm import Session

        from app.core.responses import success_response
        from app.core.security import create_access_token, get_current_user
        from app.db.session import get_db
        from app.modules.user.schemas import TokenResponse, UserCreate, UserLogin, UserRead
        from app.modules.user.service import authenticate_user, create_user


        router = APIRouter(prefix="/auth", tags=["auth"])
        user_router = APIRouter(prefix="/users", tags=["users"])


        @router.post("/register")
        def register(payload: UserCreate, db: Session = Depends(get_db)):
            user = create_user(db, payload)
            token = create_access_token(str(user.id))
            data = TokenResponse(access_token=token, user=user)
            return success_response(data=data.model_dump(), message="注册成功")


        @router.post("/login")
        def login(payload: UserLogin, db: Session = Depends(get_db)):
            user = authenticate_user(db, payload.email, payload.password)
            token = create_access_token(str(user.id))
            data = TokenResponse(access_token=token, user=user)
            return success_response(data=data.model_dump(), message="登录成功")


        @user_router.get("/me")
        def me(current_user=Depends(get_current_user)):
            return success_response(data=UserRead.model_validate(current_user).model_dump())
        """
    ).strip()
    + "\n",
    "app/modules/trade/models.py": dedent(
        """
        import enum
        from datetime import date
        from decimal import Decimal

        from sqlalchemy import Date, Enum, ForeignKey, Numeric, String, Text
        from sqlalchemy.orm import Mapped, mapped_column, relationship

        from app.db.base import Base, TimestampMixin


        class TradeDirection(str, enum.Enum):
            buy = "buy"
            sell = "sell"


        class Trade(Base, TimestampMixin):
            __tablename__ = "trades"

            id: Mapped[int] = mapped_column(primary_key=True, index=True)
            user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
            trade_date: Mapped[date] = mapped_column(Date, nullable=False)
            symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
            name: Mapped[str] = mapped_column(String(50), nullable=False)
            direction: Mapped[TradeDirection] = mapped_column(Enum(TradeDirection), nullable=False)
            quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
            price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
            amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
            fee: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=0)
            profit: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
            platform: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
            notes: Mapped[str | None] = mapped_column(Text)

            user = relationship("User", back_populates="trades")
            review_notes = relationship("Note", back_populates="trade")
        """
    ).strip()
    + "\n",
    "app/modules/trade/schemas.py": dedent(
        """
        from datetime import date, datetime

        from pydantic import BaseModel, ConfigDict, Field

        from app.modules.trade.models import TradeDirection


        class TradeBase(BaseModel):
            trade_date: date
            symbol: str = Field(min_length=1, max_length=20)
            name: str = Field(min_length=1, max_length=50)
            direction: TradeDirection
            quantity: float = Field(gt=0)
            price: float = Field(gt=0)
            amount: float = Field(gt=0)
            fee: float = Field(default=0, ge=0)
            profit: float = 0
            platform: str = "manual"
            notes: str | None = None


        class TradeCreate(TradeBase):
            pass


        class TradeRead(TradeBase):
            model_config = ConfigDict(from_attributes=True)

            id: int
            user_id: int
            created_at: datetime
            updated_at: datetime


        class TradeStats(BaseModel):
            total_trades: int = 0
            win_rate: float = 0
            profit_factor: float = 0
            max_drawdown: float = 0
            total_profit: float = 0
            avg_profit: float = 0
        """
    ).strip()
    + "\n",
    "app/modules/trade/service.py": dedent(
        """
        import pandas as pd
        from sqlalchemy import select
        from sqlalchemy.orm import Session

        from app.core.exceptions import APIException
        from app.modules.trade.models import Trade
        from app.modules.trade.schemas import TradeCreate
        from app.services.ta_lib import calculate_trade_stats


        def create_trade(db: Session, user_id: int, payload: TradeCreate) -> Trade:
            trade = Trade(user_id=user_id, **payload.model_dump())
            db.add(trade)
            db.commit()
            db.refresh(trade)
            return trade


        def create_trades(db: Session, user_id: int, trades: list[dict]) -> list[Trade]:
            created = []
            for item in trades:
                payload = TradeCreate.model_validate(item)
                created.append(create_trade(db, user_id, payload))
            return created


        def list_user_trades(db: Session, user_id: int) -> list[Trade]:
            return list(
                db.scalars(
                    select(Trade).where(Trade.user_id == user_id).order_by(Trade.trade_date.desc(), Trade.id.desc())
                )
            )


        def get_user_trade(db: Session, user_id: int, trade_id: int) -> Trade:
            trade = db.scalar(select(Trade).where(Trade.id == trade_id, Trade.user_id == user_id))
            if not trade:
                raise APIException(code=20002, message="交易记录不存在", status_code=404)
            return trade


        def summarize_trades(db: Session, user_id: int) -> dict:
            trades = list_user_trades(db, user_id)
            if not trades:
                return calculate_trade_stats(pd.DataFrame())

            records = [
                {
                    "profit": float(trade.profit),
                    "trade_date": trade.trade_date.isoformat(),
                    "amount": float(trade.amount),
                }
                for trade in trades
            ]
            return calculate_trade_stats(pd.DataFrame(records))
        """
    ).strip()
    + "\n",
    "app/modules/trade/router.py": dedent(
        """
        from fastapi import APIRouter, Depends, File, UploadFile
        from sqlalchemy.orm import Session

        from app.core.responses import success_response
        from app.core.security import get_current_user
        from app.db.session import get_db
        from app.modules.trade.schemas import TradeCreate, TradeRead
        from app.modules.trade.service import create_trade, create_trades, list_user_trades, summarize_trades
        from app.services.ocr import recognize_statement


        router = APIRouter(prefix="/trades", tags=["trades"])


        @router.get("")
        def get_trades(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
            trades = list_user_trades(db, current_user.id)
            data = [TradeRead.model_validate(trade).model_dump() for trade in trades]
            return success_response(data=data)


        @router.post("")
        def add_trade(payload: TradeCreate, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
            trade = create_trade(db, current_user.id, payload)
            return success_response(data=TradeRead.model_validate(trade).model_dump(), message="交易记录创建成功")


        @router.post("/import/ocr")
        async def import_by_ocr(
            file: UploadFile = File(...),
            current_user=Depends(get_current_user),
            db: Session = Depends(get_db),
        ):
            content = await file.read()
            trades = recognize_statement(content)
            created_trades = create_trades(db, current_user.id, trades)
            data = [TradeRead.model_validate(trade).model_dump() for trade in created_trades]
            return success_response(data=data, message="交割单识别并导入成功")


        @router.get("/stats/summary")
        def stats_summary(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
            return success_response(data=summarize_trades(db, current_user.id))
        """
    ).strip()
    + "\n",
    "app/modules/note/models.py": dedent(
        """
        from sqlalchemy import ForeignKey, String, Text
        from sqlalchemy.orm import Mapped, mapped_column, relationship

        from app.db.base import Base, TimestampMixin


        class Note(Base, TimestampMixin):
            __tablename__ = "notes"

            id: Mapped[int] = mapped_column(primary_key=True, index=True)
            user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
            trade_id: Mapped[int | None] = mapped_column(ForeignKey("trades.id", ondelete="SET NULL"), nullable=True)
            title: Mapped[str] = mapped_column(String(100), nullable=False)
            content: Mapped[str] = mapped_column(Text, nullable=False)
            tags: Mapped[str | None] = mapped_column(String(255))

            user = relationship("User", back_populates="notes")
            trade = relationship("Trade", back_populates="review_notes")
        """
    ).strip()
    + "\n",
    "app/modules/note/schemas.py": dedent(
        """
        from datetime import datetime

        from pydantic import BaseModel, ConfigDict, Field


        class NoteCreate(BaseModel):
            trade_id: int | None = None
            title: str = Field(min_length=1, max_length=100)
            content: str = Field(min_length=1)
            tags: str | None = None


        class NoteRead(NoteCreate):
            model_config = ConfigDict(from_attributes=True)

            id: int
            user_id: int
            created_at: datetime
            updated_at: datetime
        """
    ).strip()
    + "\n",
    "app/modules/note/service.py": dedent(
        """
        from sqlalchemy import select
        from sqlalchemy.orm import Session

        from app.modules.note.models import Note
        from app.modules.note.schemas import NoteCreate


        def create_note(db: Session, user_id: int, payload: NoteCreate) -> Note:
            note = Note(user_id=user_id, **payload.model_dump())
            db.add(note)
            db.commit()
            db.refresh(note)
            return note


        def list_notes(db: Session, user_id: int) -> list[Note]:
            return list(db.scalars(select(Note).where(Note.user_id == user_id).order_by(Note.created_at.desc())))
        """
    ).strip()
    + "\n",
    "app/modules/note/router.py": dedent(
        """
        from fastapi import APIRouter, Depends
        from sqlalchemy.orm import Session

        from app.core.responses import success_response
        from app.core.security import get_current_user
        from app.db.session import get_db
        from app.modules.note.schemas import NoteCreate, NoteRead
        from app.modules.note.service import create_note, list_notes


        router = APIRouter(prefix="/notes", tags=["notes"])


        @router.get("")
        def get_notes(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
            notes = list_notes(db, current_user.id)
            data = [NoteRead.model_validate(note).model_dump() for note in notes]
            return success_response(data=data)


        @router.post("")
        def add_note(payload: NoteCreate, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
            note = create_note(db, current_user.id, payload)
            return success_response(data=NoteRead.model_validate(note).model_dump(), message="复盘笔记创建成功")
        """
    ).strip()
    + "\n",
    "app/modules/community/models.py": dedent(
        """
        from sqlalchemy import ForeignKey, String, Text
        from sqlalchemy.orm import Mapped, mapped_column, relationship

        from app.db.base import Base, TimestampMixin


        class Post(Base, TimestampMixin):
            __tablename__ = "posts"

            id: Mapped[int] = mapped_column(primary_key=True, index=True)
            user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
            title: Mapped[str] = mapped_column(String(100), nullable=False)
            content: Mapped[str] = mapped_column(Text, nullable=False)
            likes: Mapped[int] = mapped_column(default=0, nullable=False)
            comments: Mapped[int] = mapped_column(default=0, nullable=False)

            user = relationship("User", back_populates="posts")
        """
    ).strip()
    + "\n",
    "app/modules/community/schemas.py": dedent(
        """
        from datetime import datetime

        from pydantic import BaseModel, ConfigDict, Field


        class PostCreate(BaseModel):
            title: str = Field(min_length=1, max_length=100)
            content: str = Field(min_length=1)


        class PostRead(PostCreate):
            model_config = ConfigDict(from_attributes=True)

            id: int
            user_id: int
            likes: int
            comments: int
            created_at: datetime
            updated_at: datetime
        """
    ).strip()
    + "\n",
    "app/modules/community/service.py": dedent(
        """
        from sqlalchemy import select
        from sqlalchemy.orm import Session

        from app.core.exceptions import APIException
        from app.modules.community.models import Post
        from app.modules.community.schemas import PostCreate


        def create_post(db: Session, user_id: int, payload: PostCreate) -> Post:
            post = Post(user_id=user_id, **payload.model_dump())
            db.add(post)
            db.commit()
            db.refresh(post)
            return post


        def list_posts(db: Session) -> list[Post]:
            return list(db.scalars(select(Post).order_by(Post.created_at.desc())))


        def like_post(db: Session, post_id: int) -> Post:
            post = db.get(Post, post_id)
            if not post:
                raise APIException(code=40001, message="帖子不存在", status_code=404)
            post.likes += 1
            db.commit()
            db.refresh(post)
            return post
        """
    ).strip()
    + "\n",
    "app/modules/community/router.py": dedent(
        """
        from fastapi import APIRouter, Depends
        from sqlalchemy.orm import Session

        from app.core.responses import success_response
        from app.core.security import get_current_user
        from app.db.session import get_db
        from app.modules.community.schemas import PostCreate, PostRead
        from app.modules.community.service import create_post, like_post, list_posts


        router = APIRouter(prefix="/community/posts", tags=["community"])


        @router.get("")
        def get_posts(db: Session = Depends(get_db)):
            posts = list_posts(db)
            data = [PostRead.model_validate(post).model_dump() for post in posts]
            return success_response(data=data)


        @router.post("")
        def add_post(payload: PostCreate, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
            post = create_post(db, current_user.id, payload)
            return success_response(data=PostRead.model_validate(post).model_dump(), message="帖子发布成功")


        @router.post("/{post_id}/like")
        def add_like(post_id: int, db: Session = Depends(get_db)):
            post = like_post(db, post_id)
            return success_response(data=PostRead.model_validate(post).model_dump(), message="点赞成功")
        """
    ).strip()
    + "\n",
    "app/modules/hot/models.py": dedent(
        """
        from datetime import datetime

        from sqlalchemy import DateTime, String, Text
        from sqlalchemy.orm import Mapped, mapped_column

        from app.db.base import Base


        class HotNews(Base):
            __tablename__ = "hot_news"

            id: Mapped[int] = mapped_column(primary_key=True, index=True)
            title: Mapped[str] = mapped_column(String(200), nullable=False)
            summary: Mapped[str] = mapped_column(Text, nullable=False)
            source: Mapped[str] = mapped_column(String(50), nullable=False)
            publish_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
            created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
        """
    ).strip()
    + "\n",
    "app/modules/hot/schemas.py": dedent(
        """
        from datetime import datetime

        from pydantic import BaseModel, ConfigDict


        class HotNewsRead(BaseModel):
            model_config = ConfigDict(from_attributes=True)

            id: int
            title: str
            summary: str
            source: str
            publish_time: datetime
            created_at: datetime
        """
    ).strip()
    + "\n",
    "app/modules/hot/service.py": dedent(
        """
        from datetime import datetime, timedelta

        from sqlalchemy import select
        from sqlalchemy.orm import Session

        from app.modules.hot.models import HotNews


        SAMPLE_NEWS = [
            {
                "title": "美联储维持利率不变，市场关注后续降息路径",
                "summary": "利率决议保持稳定，成长和高股息板块情绪分化，适合在复盘中观察仓位与风险暴露。",
                "source": "Finano Demo Feed",
            },
            {
                "title": "AI 算力板块波动加剧，龙头成交显著放大",
                "summary": "热点延续但日内分歧增强，适合结合交易纪律与止盈规则复盘执行是否到位。",
                "source": "Finano Demo Feed",
            },
        ]


        def bootstrap_hot_news(db: Session) -> None:
            existing = db.scalar(select(HotNews.id).limit(1))
            if existing:
                return

            now = datetime.utcnow()
            for index, item in enumerate(SAMPLE_NEWS):
                db.add(
                    HotNews(
                        title=item["title"],
                        summary=item["summary"],
                        source=item["source"],
                        publish_time=now - timedelta(hours=index),
                        created_at=now,
                    )
                )
            db.commit()


        def list_hot_news(db: Session) -> list[HotNews]:
            return list(db.scalars(select(HotNews).order_by(HotNews.publish_time.desc())))
        """
    ).strip()
    + "\n",
    "app/modules/hot/router.py": dedent(
        """
        from fastapi import APIRouter, Depends
        from sqlalchemy.orm import Session

        from app.core.responses import success_response
        from app.db.session import get_db
        from app.modules.hot.schemas import HotNewsRead
        from app.modules.hot.service import list_hot_news


        router = APIRouter(prefix="/hot", tags=["hot"])


        @router.get("")
        def get_hot_news(db: Session = Depends(get_db)):
            items = list_hot_news(db)
            data = [HotNewsRead.model_validate(item).model_dump() for item in items]
            return success_response(data=data)
        """
    ).strip()
    + "\n",
    "app/modules/hot/tasks.py": dedent(
        """
        from app.utils.celery_app import celery


        @celery.task
        def fetch_hot_news() -> dict:
            return {"status": "ok", "message": "热点任务已预留，可接入真实源"}
        """
    ).strip()
    + "\n",
    "app/modules/ai/router.py": dedent(
        """
        from fastapi import APIRouter, Depends
        from sqlalchemy.orm import Session

        from app.core.responses import success_response
        from app.core.security import get_current_user
        from app.db.session import get_db
        from app.modules.trade.service import get_user_trade, summarize_trades
        from app.services.qwen_finance import analyze_trade


        router = APIRouter(prefix="/ai", tags=["ai"])


        @router.post("/analyze/{trade_id}")
        def analyze(trade_id: int, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
            trade = get_user_trade(db, current_user.id, trade_id)
            stats = summarize_trades(db, current_user.id)
            result = analyze_trade(
                {
                    "symbol": trade.symbol,
                    "name": trade.name,
                    "direction": trade.direction.value,
                    "trade_date": trade.trade_date.isoformat(),
                    "amount": float(trade.amount),
                    "fee": float(trade.fee),
                    "profit": float(trade.profit),
                    "notes": trade.notes,
                },
                stats,
            )
            return success_response(data=result, message="AI 分析完成")
        """
    ).strip()
    + "\n",
    "app/services/ocr.py": dedent(
        """
        from datetime import date

        from app.core.config import settings
        from app.core.exceptions import APIException

        try:
            from aip import AipOcr
        except ImportError:
            AipOcr = None


        def _to_float(value, default: float = 0) -> float:
            try:
                return float(str(value).replace(",", "").strip())
            except (TypeError, ValueError):
                return default


        def _fallback_trade() -> list[dict]:
            today = date.today().isoformat()
            return [
                {
                    "trade_date": today,
                    "symbol": "600519",
                    "name": "贵州茅台",
                    "direction": "buy",
                    "quantity": 100,
                    "price": 1800,
                    "amount": 180000,
                    "fee": 15,
                    "profit": 3200,
                    "platform": "ocr_demo",
                    "notes": "未配置百度 OCR，已回退到演示样例数据",
                }
            ]


        def recognize_statement(image_content: bytes):
            if not image_content:
                raise APIException(code=20001, message="上传文件为空", status_code=400)

            if not all(
                [
                    settings.baidu_ocr_app_id,
                    settings.baidu_ocr_api_key,
                    settings.baidu_ocr_secret_key,
                    AipOcr,
                ]
            ):
                return _fallback_trade()

            client = AipOcr(
                settings.baidu_ocr_app_id,
                settings.baidu_ocr_api_key,
                settings.baidu_ocr_secret_key,
            )
            result = client.financeBill(image_content)
            words_result = result.get("words_result")
            if not words_result:
                raise APIException(code=20001, message="OCR 未识别出有效字段", status_code=400)

            items = words_result if isinstance(words_result, list) else [words_result]
            trades = []
            for item in items:
                trades.append(
                    {
                        "trade_date": item.get("交易日期", {}).get("word") or date.today().isoformat(),
                        "symbol": item.get("证券代码", {}).get("word", "UNKNOWN"),
                        "name": item.get("证券名称", {}).get("word", "未知标的"),
                        "direction": "buy" if "买" in item.get("买卖方向", {}).get("word", "") else "sell",
                        "quantity": _to_float(item.get("成交数量", {}).get("word", 0), 1),
                        "price": _to_float(item.get("成交价格", {}).get("word", 0), 1),
                        "amount": _to_float(item.get("成交金额", {}).get("word", 0), 1),
                        "fee": _to_float(item.get("手续费", {}).get("word", 0), 0),
                        "profit": 0,
                        "platform": "ocr_baidu",
                        "notes": "由百度 OCR 自动识别导入",
                    }
                )

            return trades
        """
    ).strip()
    + "\n",
    "app/services/qwen_finance.py": dedent(
        """
        import json

        from app.core.config import settings

        try:
            import dashscope
        except ImportError:
            dashscope = None


        def _local_analysis(trade_data: dict, stats: dict) -> dict:
            profit = float(trade_data.get("profit", 0) or 0)
            fee = float(trade_data.get("fee", 0) or 0)
            win_rate = float(stats.get("win_rate", 0) or 0)
            strengths = []
            problems = []
            suggestions = []

            if profit > 0:
                strengths.append("该笔交易实现正收益，说明离场结果优于亏损样本。")
            else:
                problems.append("该笔交易未形成正收益，需要复盘入场依据与止损执行。")

            if fee <= max(abs(profit) * 0.05, 20):
                strengths.append("手续费占比可控，交易成本没有明显侵蚀结果。")
            else:
                problems.append("手续费占比较高，可能削弱策略净收益。")

            if win_rate >= 50:
                strengths.append("当前历史胜率不低于 50%，说明策略具备一定稳定性。")
            else:
                problems.append("当前历史胜率偏低，策略一致性仍需加强。")

            suggestions.append("补充当时的入场逻辑、止损条件和离场触发点，形成可复用复盘模板。")
            suggestions.append("将本笔交易与同类标的放在一起比较，验证是否存在重复性执行偏差。")

            return {
                "strengths": strengths[:2] or ["交易记录已完整保存，可继续沉淀为样本。"],
                "problems": problems[:2] or ["暂未发现明显结构性问题，但仍应关注样本量是否足够。"],
                "suggestions": suggestions[:2],
            }


        def analyze_trade(trade_data: dict, stats: dict):
            if not settings.dashscope_api_key or dashscope is None:
                return _local_analysis(trade_data, stats)

            dashscope.api_key = settings.dashscope_api_key
            system_prompt = (
                "你是 Finano 专业交易复盘助手，只基于用户提供的交易数据做事实性分析，"
                "不预测市场，不给出投资建议。严格输出 JSON，字段为 strengths、problems、suggestions。"
            )
            user_prompt = f"交易数据：{trade_data}\\n历史统计：{stats}\\n请分析这笔交易的优缺点和改进建议。"
            response = dashscope.Generation.call(
                model="qwen-plus",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                result_format="message",
                temperature=0.1,
                max_tokens=512,
            )
            content = response.output.choices[0].message.content
            if isinstance(content, dict):
                return content
            try:
                return json.loads(content)
            except Exception:
                return _local_analysis(trade_data, stats)
        """
    ).strip()
    + "\n",
    "app/services/ta_lib.py": dedent(
        """
        import pandas as pd


        def calculate_trade_stats(trades_df: pd.DataFrame):
            if trades_df.empty or "profit" not in trades_df.columns:
                return {
                    "total_trades": 0,
                    "win_rate": 0,
                    "profit_factor": 0,
                    "max_drawdown": 0,
                    "total_profit": 0,
                    "avg_profit": 0,
                }

            profit_series = pd.to_numeric(trades_df["profit"], errors="coerce").fillna(0)
            total_trades = int(len(profit_series))
            win_trades = int((profit_series > 0).sum())
            loss_trades = int((profit_series < 0).sum())
            win_rate = (win_trades / total_trades) * 100 if total_trades else 0

            total_profit = float(profit_series[profit_series > 0].sum())
            total_loss = abs(float(profit_series[profit_series < 0].sum()))
            profit_factor = (total_profit / total_loss) if total_loss > 0 else (float("inf") if total_profit > 0 else 0)

            cumulative = profit_series.cumsum()
            running_max = cumulative.cummax().replace(0, pd.NA)
            drawdown = ((cumulative - running_max) / running_max * 100).fillna(0)
            max_drawdown = float(drawdown.min()) if not drawdown.empty else 0
            avg_profit = float(profit_series.mean()) if total_trades else 0

            return {
                "total_trades": total_trades,
                "win_rate": round(win_rate, 2),
                "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else 999999.0,
                "max_drawdown": round(max_drawdown, 2),
                "total_profit": round(float(profit_series.sum()), 2),
                "avg_profit": round(avg_profit, 2),
                "loss_trades": loss_trades,
            }
        """
    ).strip()
    + "\n",
    "app/utils/chroma_client.py": dedent(
        """
        import json
        from pathlib import Path


        DATA_FILE = Path("data/vector_store.jsonl")


        def add_trade_to_vector(user_id: int, trade: dict) -> None:
            DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
            with DATA_FILE.open("a", encoding="utf-8") as file:
                file.write(json.dumps({"user_id": user_id, "trade": trade}, ensure_ascii=False) + "\\n")
        """
    ).strip()
    + "\n",
    "app/utils/celery_app.py": dedent(
        """
        from celery import Celery

        from app.core.config import settings


        celery = Celery("finano_tasks", broker=settings.redis_url, backend=settings.redis_url)
        celery.conf.task_serializer = "json"
        celery.conf.result_serializer = "json"
        celery.conf.accept_content = ["json"]
        celery.conf.timezone = "Asia/Shanghai"
        celery.conf.task_always_eager = settings.environment == "test"
        """
    ).strip()
    + "\n",
    "app/modules/trade/tasks.py": dedent(
        """
        import pandas as pd

        from app.services.ta_lib import calculate_trade_stats
        from app.utils.celery_app import celery
        from app.utils.chroma_client import add_trade_to_vector


        @celery.task
        def process_imported_trades(user_id: int, trades: list):
            stats = calculate_trade_stats(pd.DataFrame(trades))
            for trade in trades:
                add_trade_to_vector(user_id, trade)
            return stats
        """
    ).strip()
    + "\n",
    "app/main.py": dedent(
        """
        from contextlib import asynccontextmanager

        from fastapi import FastAPI
        from fastapi.middleware.cors import CORSMiddleware

        from app.core.config import settings
        from app.core.exceptions import register_exception_handlers
        from app.core.responses import success_response
        from app.db.base import Base
        from app.db.session import SessionLocal, engine
        from app.modules.ai.router import router as ai_router
        from app.modules.community.router import router as community_router
        from app.modules.hot.router import router as hot_router
        from app.modules.hot.service import bootstrap_hot_news
        from app.modules.note.router import router as note_router
        from app.modules.trade.router import router as trade_router
        from app.modules.user.router import router as auth_router
        from app.modules.user.router import user_router

        from app.modules.community import models as _community_models  # noqa: F401
        from app.modules.hot import models as _hot_models  # noqa: F401
        from app.modules.note import models as _note_models  # noqa: F401
        from app.modules.trade import models as _trade_models  # noqa: F401
        from app.modules.user import models as _user_models  # noqa: F401


        @asynccontextmanager
        async def lifespan(_: FastAPI):
            Base.metadata.create_all(bind=engine)
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
        app.include_router(trade_router, prefix=settings.api_v1_prefix)
        app.include_router(note_router, prefix=settings.api_v1_prefix)
        app.include_router(ai_router, prefix=settings.api_v1_prefix)
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
        """
    ).strip()
    + "\n",
    "tests/test_ta_lib.py": dedent(
        """
        import pandas as pd

        from app.services.ta_lib import calculate_trade_stats


        def test_calculate_trade_stats():
            trades_df = pd.DataFrame(
                [
                    {"profit": 100},
                    {"profit": -50},
                    {"profit": 200},
                    {"profit": -30},
                ]
            )

            stats = calculate_trade_stats(trades_df)

            assert stats["total_trades"] == 4
            assert stats["win_rate"] == 50.0
            assert stats["profit_factor"] == round(300 / 80, 2)
            assert stats["total_profit"] == 220.0
        """
    ).strip()
    + "\n",
    "tests/test_api_smoke.py": dedent(
        """
        import os
        from pathlib import Path

        os.environ["DATABASE_URL"] = "sqlite:///./test_finano.db"
        os.environ["CORS_ORIGINS"] = '["http://localhost:5173"]'

        from fastapi.testclient import TestClient

        from app.main import app


        client = TestClient(app)
        DB_FILE = Path("test_finano.db")


        def _auth_headers():
            response = client.post(
                "/api/v1/auth/register",
                json={
                    "username": "apitest",
                    "email": "apitest@example.com",
                    "password": "secret123",
                },
            )
            token = response.json()["data"]["access_token"]
            return {"Authorization": f"Bearer {token}"}


        def test_trade_flow():
            headers = _auth_headers()
            create_response = client.post(
                "/api/v1/trades",
                headers=headers,
                json={
                    "trade_date": "2024-01-05",
                    "symbol": "600519",
                    "name": "贵州茅台",
                    "direction": "buy",
                    "quantity": 100,
                    "price": 1800,
                    "amount": 180000,
                    "fee": 15,
                    "profit": 3200,
                    "platform": "manual",
                    "notes": "smoke",
                },
            )
            assert create_response.status_code == 200
            summary_response = client.get("/api/v1/trades/stats/summary", headers=headers)
            assert summary_response.status_code == 200
            assert summary_response.json()["data"]["total_trades"] >= 1


        def teardown_module():
            if DB_FILE.exists():
                DB_FILE.unlink()
        """
    ).strip()
    + "\n",
    "scripts/seed_data.py": dedent(
        """
        import sys
        from pathlib import Path

        sys.path.append(str(Path(__file__).resolve().parents[1]))

        from app.db.base import Base
        from app.db.session import SessionLocal, engine
        from app.modules.trade.schemas import TradeCreate
        from app.modules.trade.service import create_trade
        from app.modules.user.schemas import UserCreate
        from app.modules.user.service import create_user, get_user_by_email


        def main():
            Base.metadata.create_all(bind=engine)
            db = SessionLocal()
            try:
                user = get_user_by_email(db, "test@example.com")
                if not user:
                    user = create_user(
                        db,
                        UserCreate(username="testuser", email="test@example.com", password="test123"),
                    )

                trades = [
                    TradeCreate(
                        trade_date="2024-01-05",
                        symbol="600519",
                        name="贵州茅台",
                        direction="buy",
                        quantity=100,
                        price=1800,
                        amount=180000,
                        fee=15,
                        profit=18000,
                    ),
                    TradeCreate(
                        trade_date="2024-01-15",
                        symbol="000858",
                        name="五粮液",
                        direction="buy",
                        quantity=200,
                        price=150,
                        amount=30000,
                        fee=10,
                        profit=-3000,
                    ),
                ]
                for trade in trades:
                    create_trade(db, user.id, trade)
                print("Seed data created successfully.")
            finally:
                db.close()


        if __name__ == "__main__":
            main()
        """
    ).strip()
    + "\n",
}

for relative_path, content in files.items():
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
