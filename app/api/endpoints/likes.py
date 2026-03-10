"""
Likes endpoints:
  GET    /api/v1/likes/{slug}   → get like count + whether current user liked
  POST   /api/v1/likes/{slug}   → toggle like (requires authentication)
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models.db import get_db, Like, Post, User
from app.core.sessions import get_session

router = APIRouter()


async def require_user(request: Request, db: AsyncSession) -> User:
    sess = get_session(request)
    if not sess:
        raise HTTPException(status_code=401, detail="Connexion requise pour liker.")
    result = await db.execute(select(User).where(User.id == sess["user_id"]))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="Utilisateur introuvable.")
    return user


@router.get("/{slug}")
async def get_likes(slug: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Retourne le nombre de likes et si l'utilisateur courant a liké."""
    result = await db.execute(select(Post).where(Post.slug == slug))
    post = result.scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="Article introuvable")

    count_result = await db.execute(
        select(func.count()).select_from(Like).where(Like.post_id == post.id)
    )
    count = count_result.scalar()

    user_liked = False
    sess = get_session(request)
    if sess:
        liked_result = await db.execute(
            select(Like).where(Like.post_id == post.id, Like.user_id == sess["user_id"])
        )
        user_liked = liked_result.scalar_one_or_none() is not None

    return {"count": count, "user_liked": user_liked}


@router.post("/{slug}")
async def toggle_like(slug: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Toggle like sur un article — nécessite d'être connecté."""
    user = await require_user(request, db)

    result = await db.execute(select(Post).where(Post.slug == slug, Post.published == True))
    post = result.scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="Article introuvable")

    existing = await db.execute(
        select(Like).where(Like.post_id == post.id, Like.user_id == user.id)
    )
    like = existing.scalar_one_or_none()

    if like:
        await db.delete(like)
        await db.commit()
        liked = False
    else:
        db.add(Like(post_id=post.id, user_id=user.id))
        await db.commit()
        liked = True

    count_result = await db.execute(
        select(func.count()).select_from(Like).where(Like.post_id == post.id)
    )
    return {"count": count_result.scalar(), "user_liked": liked}
