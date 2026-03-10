"""
Comments endpoints:
  GET  /api/v1/comments/{slug}   → list comments for a post
  POST /api/v1/comments/{slug}   → add a comment (no account needed)
  DELETE /api/v1/comments/{id}   → delete a comment (admin only)
"""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.models.db import get_db, Comment, Post, User
from app.core.sessions import get_session

router = APIRouter()


class CommentCreate(BaseModel):
    author: str      # pseudo libre, pas de compte requis
    content: str


def comment_to_dict(c: Comment) -> dict:
    return {
        "id": c.id,
        "author": c.author,
        "content": c.content,
        "created_at": c.created_at.isoformat(),
    }


@router.get("/{slug}")
async def list_comments(slug: str, db: AsyncSession = Depends(get_db)):
    """Retourne tous les commentaires d'un article."""
    result = await db.execute(select(Post).where(Post.slug == slug))
    post = result.scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="Article introuvable")

    result = await db.execute(
        select(Comment)
        .where(Comment.post_id == post.id)
        .order_by(Comment.created_at)
    )
    return [comment_to_dict(c) for c in result.scalars().all()]


@router.post("/{slug}", status_code=201)
async def add_comment(slug: str, body: CommentCreate, db: AsyncSession = Depends(get_db)):
    """Ajouter un commentaire — aucun compte nécessaire."""
    # Validation basique
    author = body.author.strip()[:80]
    content = body.content.strip()[:2000]
    if not author:
        raise HTTPException(status_code=422, detail="Le pseudo est requis")
    if not content:
        raise HTTPException(status_code=422, detail="Le commentaire ne peut pas être vide")

    result = await db.execute(select(Post).where(Post.slug == slug, Post.published == True))
    post = result.scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="Article introuvable")

    comment = Comment(post_id=post.id, author=author, content=content)
    db.add(comment)
    await db.commit()
    await db.refresh(comment)
    return comment_to_dict(comment)


@router.delete("/{comment_id}", status_code=204)
async def delete_comment(comment_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    """Supprimer un commentaire — admin uniquement."""
    sess = get_session(request)
    if not sess:
        raise HTTPException(status_code=401, detail="Non authentifié")
    result = await db.execute(select(User).where(User.id == sess["user_id"]))
    user = result.scalar_one_or_none()
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin requis")

    result = await db.execute(select(Comment).where(Comment.id == comment_id))
    comment = result.scalar_one_or_none()
    if not comment:
        raise HTTPException(status_code=404, detail="Commentaire introuvable")
    await db.delete(comment)
    await db.commit()
