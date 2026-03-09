"""
Simple signed-cookie session manager using itsdangerous.
Replace with Redis-backed sessions for high-scale production.
"""
from typing import Optional
from fastapi import Request, Response
from itsdangerous import TimestampSigner, BadSignature, SignatureExpired

from app.core.config import settings

_signer = TimestampSigner(settings.SECRET_KEY)


def create_session(response: Response, user_id: int, username: str):
    payload = f"{user_id}:{username}"
    token = _signer.sign(payload).decode()
    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=token,
        max_age=settings.SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=settings.ENVIRONMENT == "production",
    )


def get_session(request: Request) -> Optional[dict]:
    token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not token:
        return None
    try:
        payload = _signer.unsign(
            token.encode(), max_age=settings.SESSION_MAX_AGE
        ).decode()
        user_id, username = payload.split(":", 1)
        return {"user_id": int(user_id), "username": username}
    except (BadSignature, SignatureExpired, ValueError):
        return None


def clear_session(response: Response):
    response.delete_cookie(settings.SESSION_COOKIE_NAME)
