"""
Blog post endpoints:
  GET    /api/v1/posts              → list published posts
  GET    /api/v1/posts/{slug}       → single post
  POST   /api/v1/posts              → create (admin)
  PUT    /api/v1/posts/{slug}       → update (admin)
  DELETE /api/v1/posts/{slug}       → delete (admin)
"""
from datetime import datetime
from typing import List, Optional
import re
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.models.db import get_db, Post, User
from app.core.sessions import get_session

router = APIRouter()


# ── Helpers ───────────────────────────────────────────────

def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return text[:120]


async def require_admin(request: Request, db: AsyncSession) -> User:
    sess = get_session(request)
    if not sess:
        raise HTTPException(status_code=401, detail="Authentication required")
    result = await db.execute(select(User).where(User.id == sess["user_id"]))
    user = result.scalar_one_or_none()
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin required")
    return user


# ── Schemas ───────────────────────────────────────────────

class PostCreate(BaseModel):
    title: str
    summary: str = ""
    content: str
    tags: List[str] = []
    published: bool = False
    cover_image: Optional[str] = None

class PostUpdate(PostCreate):
    pass

class PostOut(BaseModel):
    slug: str
    title: str
    summary: str
    content: str
    tags: List[str]
    published: bool
    cover_image: Optional[str]
    created_at: datetime
    updated_at: datetime
    author_username: str

    model_config = {"from_attributes": True}


def post_to_dict(post: Post) -> dict:
    return {
        "slug": post.slug,
        "title": post.title,
        "summary": post.summary or "",
        "content": post.content,
        "tags": json.loads(post.tags or "[]"),
        "published": post.published,
        "cover_image": post.cover_image,
        "created_at": post.created_at.isoformat(),
        "updated_at": post.updated_at.isoformat(),
        "author_username": post.author.username if post.author else "",
    }


# ── Endpoints ─────────────────────────────────────────────

@router.get("/")
async def list_posts(request: Request, db: AsyncSession = Depends(get_db)):
    sess = get_session(request)
    is_admin = False
    if sess:
        result = await db.execute(select(User).where(User.id == sess["user_id"]))
        u = result.scalar_one_or_none()
        is_admin = bool(u and u.is_admin)

    query = select(Post).order_by(desc(Post.created_at))
    if not is_admin:
        query = query.where(Post.published == True)

    result = await db.execute(query)
    posts = result.scalars().all()
    # Eager-load authors
    for p in posts:
        await db.refresh(p, ["author"])
    return [post_to_dict(p) for p in posts]


@router.get("/{slug}")
async def get_post(slug: str, request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Post).where(Post.slug == slug))
    post = result.scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    sess = get_session(request)
    if not post.published:
        if not sess:
            raise HTTPException(status_code=404)
        ur = await db.execute(select(User).where(User.id == sess["user_id"]))
        u = ur.scalar_one_or_none()
        if not u or not u.is_admin:
            raise HTTPException(status_code=404)

    await db.refresh(post, ["author"])
    return post_to_dict(post)


@router.post("/", status_code=201)
async def create_post(body: PostCreate, request: Request, db: AsyncSession = Depends(get_db)):
    user = await require_admin(request, db)
    slug = slugify(body.title)

    # Ensure unique slug
    base_slug = slug
    i = 1
    while True:
        r = await db.execute(select(Post).where(Post.slug == slug))
        if not r.scalar_one_or_none():
            break
        slug = f"{base_slug}-{i}"
        i += 1

    post = Post(
        slug=slug,
        title=body.title,
        summary=body.summary,
        content=body.content,
        tags=json.dumps(body.tags),
        published=body.published,
        cover_image=body.cover_image,
        author_id=user.id,
    )
    db.add(post)
    await db.commit()
    await db.refresh(post, ["author"])
    return post_to_dict(post)


@router.put("/{slug}")
async def update_post(slug: str, body: PostUpdate, request: Request, db: AsyncSession = Depends(get_db)):
    await require_admin(request, db)
    result = await db.execute(select(Post).where(Post.slug == slug))
    post = result.scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404)

    post.title = body.title
    post.summary = body.summary
    post.content = body.content
    post.tags = json.dumps(body.tags)
    post.published = body.published
    post.cover_image = body.cover_image
    post.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(post, ["author"])
    return post_to_dict(post)


@router.delete("/{slug}", status_code=204)
async def delete_post(slug: str, request: Request, db: AsyncSession = Depends(get_db)):
    await require_admin(request, db)
    result = await db.execute(select(Post).where(Post.slug == slug))
    post = result.scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404)
    await db.delete(post)
    await db.commit()
