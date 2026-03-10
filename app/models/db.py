"""
SQLAlchemy async models for the blog application.
"""
from datetime import datetime
from typing import Optional
import json

from sqlalchemy import (
    Column, Integer, String, Text, Boolean,
    DateTime, ForeignKey, LargeBinary
)
from sqlalchemy.ext.asyncio import (
    AsyncSession, create_async_engine, async_sessionmaker
)
from sqlalchemy.orm import DeclarativeBase, relationship

from app.core.config import settings


class Base(DeclarativeBase):
    pass


# ── User ──────────────────────────────────────────────────
class User(Base):
    __tablename__ = "users"

    id            = Column(Integer, primary_key=True, index=True)
    username      = Column(String(80), unique=True, nullable=False, index=True)
    display_name  = Column(String(120), nullable=False)
    email         = Column(String(200), unique=True, nullable=True)
    password_hash = Column(String(256), nullable=True)   # None = YubiKey only
    google_id     = Column(String(200), unique=True, nullable=True)  # Google OAuth
    is_admin      = Column(Boolean, default=False)
    created_at    = Column(DateTime, default=datetime.utcnow)

    credentials = relationship("WebAuthnCredential", back_populates="user", cascade="all, delete-orphan")
    posts       = relationship("Post", back_populates="author", cascade="all, delete-orphan")
    likes       = relationship("Like", back_populates="user", cascade="all, delete-orphan")


# ── WebAuthn Credential (YubiKey / passkey) ───────────────
class WebAuthnCredential(Base):
    __tablename__ = "webauthn_credentials"

    id                   = Column(Integer, primary_key=True)
    user_id              = Column(Integer, ForeignKey("users.id"), nullable=False)
    credential_id        = Column(String(512), unique=True, nullable=False, index=True)
    public_key           = Column(Text, nullable=False)          # COSE key, base64url
    sign_count           = Column(Integer, default=0)
    transports           = Column(String(200), default="[]")     # JSON list
    aaguid               = Column(String(100), default="")
    device_name          = Column(String(100), default="YubiKey")
    created_at           = Column(DateTime, default=datetime.utcnow)
    last_used_at         = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="credentials")

    @property
    def transports_list(self):
        return json.loads(self.transports or "[]")


# ── Blog Post ─────────────────────────────────────────────
class Post(Base):
    __tablename__ = "posts"

    id          = Column(Integer, primary_key=True, index=True)
    slug        = Column(String(200), unique=True, nullable=False, index=True)
    title       = Column(String(300), nullable=False)
    summary     = Column(String(500), nullable=True)
    content     = Column(Text, nullable=False)   # Markdown
    cover_image = Column(String(500), nullable=True)
    tags        = Column(String(300), default="[]")   # JSON list
    published   = Column(Boolean, default=False)
    created_at  = Column(DateTime, default=datetime.utcnow)
    updated_at  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    author_id   = Column(Integer, ForeignKey("users.id"), nullable=False)

    author   = relationship("User", back_populates="posts")
    comments = relationship("Comment", back_populates="post", cascade="all, delete-orphan")
    likes    = relationship("Like", back_populates="post", cascade="all, delete-orphan")

    @property
    def tags_list(self):
        return json.loads(self.tags or "[]")


# ── Comment ───────────────────────────────────────────────
class Comment(Base):
    __tablename__ = "comments"

    id         = Column(Integer, primary_key=True, index=True)
    post_id    = Column(Integer, ForeignKey("posts.id"), nullable=False)
    author     = Column(String(80), nullable=False)   # pseudo libre, pas de compte
    content    = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    post = relationship("Post", back_populates="comments")


# ── Like ──────────────────────────────────────────────────
class Like(Base):
    __tablename__ = "likes"

    id         = Column(Integer, primary_key=True, index=True)
    post_id    = Column(Integer, ForeignKey("posts.id"), nullable=False)
    user_id    = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    post = relationship("Post", back_populates="likes")
    user = relationship("User", back_populates="likes")


# ── WebAuthn challenge store (in-memory / Redis in prod) ──
_challenge_store: dict[str, bytes] = {}

def store_challenge(session_id: str, challenge: bytes):
    _challenge_store[session_id] = challenge

def get_challenge(session_id: str) -> Optional[bytes]:
    return _challenge_store.pop(session_id, None)


# ── DB Engine ─────────────────────────────────────────────
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.ENVIRONMENT == "development",
)

AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
