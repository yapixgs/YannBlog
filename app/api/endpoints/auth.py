"""
Authentification — quatre méthodes :
  1. YubiKey (WebAuthn/FIDO2) — admin ou utilisateur
  2. Login mot de passe        — admin ou utilisateur
  3. Signup mot de passe       — création compte admin (ADMIN_KEY) ou utilisateur normal
  4. Google OAuth              — connexion/inscription via Google

Endpoints :
  POST /api/v1/auth/signup              → créer compte admin (nécessite admin_key) ou user normal
  POST /api/v1/auth/user-signup         → créer compte utilisateur normal (mdp)
  POST /api/v1/auth/login-password      → connexion identifiant + mdp
  POST /api/v1/auth/register/begin      → WebAuthn step 1
  POST /api/v1/auth/register/complete   → WebAuthn step 2
  POST /api/v1/auth/user-register/begin    → WebAuthn user non-admin step 1
  POST /api/v1/auth/user-register/complete → WebAuthn user non-admin step 2
  POST /api/v1/auth/login/begin         → WebAuthn step 1
  POST /api/v1/auth/login/complete      → WebAuthn step 2
  GET  /api/v1/auth/google              → Redirect vers Google OAuth
  GET  /api/v1/auth/google/callback     → Callback Google OAuth
  POST /api/v1/auth/logout
  GET  /api/v1/auth/me
  GET  /api/v1/auth/status              → indique si un admin existe déjà
"""
import re
import httpx
from fastapi import APIRouter, Depends, HTTPException, Response, Request
from fastapi.responses import RedirectResponse
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

class UserSignupRequest(BaseModel):
    username: str
    display_name: str = ""
    password: str

class LoginPasswordRequest(BaseModel):
    username: str
    password: str

class RegisterBeginRequest(BaseModel):
    username: str
    display_name: str = ""
    admin_key: str = ""     # requis si aucun admin n'existe encore
    is_admin: bool = False  # False = compte utilisateur normal

class RegisterCompleteRequest(BaseModel):
    username: str
    credential: str

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


# ── Signup utilisateur normal ─────────────────────────────

@router.post("/user-signup")
async def user_signup(body: UserSignupRequest, response: Response, db: AsyncSession = Depends(get_db)):
    """Créer un compte utilisateur normal (sans clé admin)."""
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
        is_admin=False,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    create_session(response, user.id, user.username)
    return {"ok": True, "username": user.username, "is_admin": False}


# ── Google OAuth ──────────────────────────────────────────

@router.get("/google")
async def google_login():
    """Redirige vers la page de connexion Google."""
    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(501, "Google OAuth non configuré.")
    params = (
        f"client_id={settings.GOOGLE_CLIENT_ID}"
        f"&redirect_uri={settings.GOOGLE_REDIRECT_URI}"
        f"&response_type=code"
        f"&scope=openid%20email%20profile"
        f"&access_type=offline"
    )
    return RedirectResponse(f"https://accounts.google.com/o/oauth2/v2/auth?{params}")


@router.get("/google/callback")
async def google_callback(code: str, response: Response, db: AsyncSession = Depends(get_db)):
    """Callback après authentification Google."""
    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(501, "Google OAuth non configuré.")

    async with httpx.AsyncClient() as client:
        # Échanger le code contre un token
        token_resp = await client.post("https://oauth2.googleapis.com/token", data={
            "code": code,
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "redirect_uri": settings.GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code",
        })
        if token_resp.status_code != 200:
            raise HTTPException(400, "Erreur lors de l'échange du code Google.")
        tokens = token_resp.json()

        # Récupérer les infos utilisateur
        userinfo_resp = await client.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {tokens['access_token']}"}
        )
        if userinfo_resp.status_code != 200:
            raise HTTPException(400, "Impossible de récupérer les informations Google.")
        info = userinfo_resp.json()

    google_id = info.get("sub")
    email = info.get("email", "")
    name = info.get("name", email.split("@")[0] if email else "user")

    # Trouver ou créer l'utilisateur
    result = await db.execute(select(User).where(User.google_id == google_id))
    user = result.scalar_one_or_none()

    if not user:
        # Vérifier si l'email existe déjà
        if email:
            result2 = await db.execute(select(User).where(User.email == email))
            user = result2.scalar_one_or_none()

        if user:
            # Lier le compte Google au compte existant
            user.google_id = google_id
        else:
            # Créer un nouveau compte
            base_username = re.sub(r"[^\w]", "", name.lower())[:30] or "user"
            username = base_username
            i = 1
            while True:
                r = await db.execute(select(User).where(User.username == username))
                if not r.scalar_one_or_none():
                    break
                username = f"{base_username}{i}"
                i += 1

            user = User(
                username=username,
                display_name=name,
                email=email,
                google_id=google_id,
                is_admin=False,
            )
            db.add(user)

        await db.commit()
        await db.refresh(user)

    redirect = RedirectResponse(url="/")
    create_session(redirect, user.id, user.username)
    return redirect


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
    if body.is_admin:
        _validate_admin_key(body.admin_key)

    username = body.username.strip()[:80]
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()

    if user:
        raise HTTPException(409, "Ce nom d'utilisateur est déjà pris. Utilisez la connexion.")

    user = User(
        username=username,
        display_name=body.display_name.strip() or username,
        is_admin=body.is_admin,
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
