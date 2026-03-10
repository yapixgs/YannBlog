"""
Authentification — trois méthodes :
  1. YubiKey (WebAuthn/FIDO2) — pour l'admin
  2. Login mot de passe        — pour l'admin (fallback)
  3. Signup mot de passe       — création de compte admin avec ADMIN_KEY

Endpoints :
  POST /api/v1/auth/signup              → créer compte (nécessite admin_key)
  POST /api/v1/auth/login-password      → connexion identifiant + mdp
  POST /api/v1/auth/register/begin      → WebAuthn step 1
  POST /api/v1/auth/register/complete   → WebAuthn step 2
  POST /api/v1/auth/login/begin         → WebAuthn step 1
  POST /api/v1/auth/login/complete      → WebAuthn step 2
  POST /api/v1/auth/logout
  GET  /api/v1/auth/me
  GET  /api/v1/auth/status              → indique si un admin existe déjà
"""
import re
from fastapi import APIRouter, Depends, HTTPException, Response, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from passlib.context import CryptContext

from app.models.db import get_db, User, WebAuthnCredential
from app.services import webauthn_service
from app.core.sessions import create_session, get_session, clear_session
from app.core.config import settings

router = APIRouter()
pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ── Schemas ───────────────────────────────────────────────

class SignupRequest(BaseModel):
    username: str
    display_name: str = ""
    password: str
    admin_key: str          # clé secrète définie dans .env

class LoginPasswordRequest(BaseModel):
    username: str
    password: str

class RegisterBeginRequest(BaseModel):
    username: str
    display_name: str = ""
    admin_key: str = ""     # requis si aucun admin n'existe encore

class RegisterCompleteRequest(BaseModel):
    username: str
    credential: str

class LoginBeginRequest(BaseModel):
    username: str = ""

class LoginCompleteRequest(BaseModel):
    username: str = ""
    credential: str


# ── Helpers ───────────────────────────────────────────────

def _validate_password(password: str):
    """Mot de passe : 8 chars min, 1 majuscule, 1 chiffre."""
    if len(password) < 8:
        raise HTTPException(400, "Le mot de passe doit faire au moins 8 caractères.")
    if not re.search(r"[A-Z]", password):
        raise HTTPException(400, "Le mot de passe doit contenir au moins une majuscule.")
    if not re.search(r"\d", password):
        raise HTTPException(400, "Le mot de passe doit contenir au moins un chiffre.")

def _validate_admin_key(admin_key: str):
    if admin_key != settings.ADMIN_KEY:
        raise HTTPException(403, "Clé admin incorrecte.")

async def _admin_exists(db: AsyncSession) -> bool:
    result = await db.execute(select(func.count()).select_from(User).where(User.is_admin == True))
    return result.scalar() > 0


# ── Status (public) ───────────────────────────────────────

@router.get("/status")
async def auth_status(db: AsyncSession = Depends(get_db)):
    """Indique si un admin existe — utilisé par le front pour afficher/masquer les onglets."""
    return {"admin_exists": await _admin_exists(db)}


# ── Signup mot de passe ───────────────────────────────────

@router.post("/signup")
async def signup(body: SignupRequest, response: Response, db: AsyncSession = Depends(get_db)):
    """Créer un compte admin avec identifiant + mot de passe + clé admin secrète."""
    _validate_admin_key(body.admin_key)
    _validate_password(body.password)

    username = body.username.strip()[:80]
    if not username:
        raise HTTPException(400, "Nom d'utilisateur requis.")

    existing = await db.execute(select(User).where(User.username == username))
    if existing.scalar_one_or_none():
        raise HTTPException(409, "Ce nom d'utilisateur est déjà pris.")

    user = User(
        username=username,
        display_name=body.display_name.strip() or username,
        password_hash=pwd_ctx.hash(body.password),
        is_admin=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    create_session(response, user.id, user.username)
    return {"ok": True, "username": user.username, "is_admin": True}


# ── Login mot de passe ────────────────────────────────────

@router.post("/login-password")
async def login_password(body: LoginPasswordRequest, response: Response, db: AsyncSession = Depends(get_db)):
    """Connexion classique identifiant + mot de passe."""
    result = await db.execute(select(User).where(User.username == body.username))
    user = result.scalar_one_or_none()

    if not user or not user.password_hash:
        raise HTTPException(401, "Identifiant ou mot de passe incorrect.")
    if not pwd_ctx.verify(body.password, user.password_hash):
        raise HTTPException(401, "Identifiant ou mot de passe incorrect.")

    create_session(response, user.id, user.username)
    return {"ok": True, "username": user.username, "is_admin": user.is_admin}


# ── WebAuthn Registration ─────────────────────────────────

@router.post("/register/begin")
async def register_begin(body: RegisterBeginRequest, db: AsyncSession = Depends(get_db)):
    """Step 1 : créer l'utilisateur et retourner les options WebAuthn."""
    # Vérifier la clé admin
    _validate_admin_key(body.admin_key)

    username = body.username.strip()[:80]
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()

    if user:
        raise HTTPException(409, "Ce nom d'utilisateur est déjà pris. Utilisez la connexion.")

    user = User(
        username=username,
        display_name=body.display_name.strip() or username,
        is_admin=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    options_json = webauthn_service.generate_registration_options(user)
    return {"options": options_json}


@router.post("/register/complete")
async def register_complete(body: RegisterCompleteRequest, response: Response, db: AsyncSession = Depends(get_db)):
    """Step 2 : vérifier l'attestation et sauvegarder la clé."""
    try:
        cred = await webauthn_service.verify_registration(
            username=body.username,
            credential_json=body.credential,
            db=db,
        )
    except Exception as e:
        raise HTTPException(400, f"Enregistrement échoué : {e}")

    result = await db.execute(select(User).where(User.username == body.username))
    user = result.scalar_one()
    create_session(response, user.id, user.username)
    return {"ok": True, "device": cred.device_name}


# ── WebAuthn Authentication ───────────────────────────────

@router.post("/login/begin")
async def login_begin(body: LoginBeginRequest, db: AsyncSession = Depends(get_db)):
    options_json = await webauthn_service.generate_authentication_options(
        db=db, username=body.username or None
    )
    return {"options": options_json}


@router.post("/login/complete")
async def login_complete(body: LoginCompleteRequest, response: Response, db: AsyncSession = Depends(get_db)):
    try:
        user = await webauthn_service.verify_authentication(
            credential_json=body.credential,
            username=body.username or None,
            db=db,
        )
    except Exception as e:
        raise HTTPException(401, f"Authentification échouée : {e}")

    create_session(response, user.id, user.username)
    return {"ok": True, "username": user.username, "is_admin": user.is_admin}


# ── Session ───────────────────────────────────────────────

@router.post("/logout")
async def logout(response: Response):
    clear_session(response)
    return {"ok": True}


@router.get("/me")
async def me(request: Request, db: AsyncSession = Depends(get_db)):
    sess = get_session(request)
    if not sess:
        raise HTTPException(401, "Non authentifié")
    result = await db.execute(select(User).where(User.id == sess["user_id"]))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(401, "Utilisateur introuvable")
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "is_admin": user.is_admin,
    }
