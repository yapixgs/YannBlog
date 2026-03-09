from fastapi import APIRouter
from app.api.endpoints import auth, posts, comments

api_router = APIRouter()
api_router.include_router(auth.router,     prefix="/auth",     tags=["auth"])
api_router.include_router(posts.router,    prefix="/posts",    tags=["posts"])
api_router.include_router(comments.router, prefix="/comments", tags=["comments"])
