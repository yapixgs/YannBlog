"""
WebAuthn / FIDO2 service — handles YubiKey registration and authentication.
Uses the `webauthn` library (py_webauthn 2.x).
"""
import base64
import json
import secrets
from datetime import datetime
from typing import Optional

import webauthn
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    UserVerificationRequirement,
    ResidentKeyRequirement,
    AuthenticatorAttachment,
)
from webauthn.helpers.cose import COSEAlgorithmIdentifier
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.models.db import User, WebAuthnCredential, store_challenge, get_challenge


RP_ID   = settings.WEBAUTHN_RP_ID
RP_NAME = settings.WEBAUTHN_RP_NAME
ORIGIN  = settings.WEBAUTHN_ORIGIN


# ── Registration ──────────────────────────────────────────

def generate_registration_options(user: User) -> dict:
    """Generate WebAuthn registration options (sent to browser)."""
    challenge = secrets.token_bytes(32)
    store_challenge(f"reg:{user.username}", challenge)

    opts = webauthn.generate_registration_options(
        rp_id=RP_ID,
        rp_name=RP_NAME,
        user_id=str(user.id).encode(),
        user_name=user.username,
        user_display_name=user.display_name,
        challenge=challenge,
        supported_pub_key_algs=[
            COSEAlgorithmIdentifier.ECDSA_SHA_256,
            COSEAlgorithmIdentifier.RSASSA_PKCS1_v1_5_SHA_256,
        ],
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
        timeout=60000,
    )

    return webauthn.options_to_json(opts)


async def verify_registration(
    username: str,
    credential_json: str,
    db: AsyncSession,
) -> WebAuthnCredential:
    """Verify registration response and save credential."""
    challenge = get_challenge(f"reg:{username}")
    if not challenge:
        raise ValueError("Challenge expired or not found")

    credential = webauthn.helpers.parse_cbor(
        base64.b64decode(credential_json + "==")
    ) if False else None  # placeholder

    # Parse the JSON credential from browser
    import json as _json
    cred_data = _json.loads(credential_json)

    verification = webauthn.verify_registration_response(
        credential=cred_data,
        expected_challenge=challenge,
        expected_rp_id=RP_ID,
        expected_origin=ORIGIN,
        require_user_verification=False,
    )

    # Load user
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one()

    # Save credential
    cred = WebAuthnCredential(
        user_id=user.id,
        credential_id=base64.urlsafe_b64encode(
            verification.credential_id
        ).decode().rstrip("="),
        public_key=base64.urlsafe_b64encode(
            verification.credential_public_key
        ).decode().rstrip("="),
        sign_count=verification.sign_count,
        aaguid=str(verification.aaguid) if verification.aaguid else "",
        device_name=_detect_device_name(str(verification.aaguid) if verification.aaguid else ""),
    )
    db.add(cred)
    await db.commit()
    await db.refresh(cred)
    return cred


# ── Authentication ────────────────────────────────────────

async def generate_authentication_options(db: AsyncSession, username: Optional[str] = None) -> str:
    """Generate WebAuthn authentication options."""
    challenge = secrets.token_bytes(32)
    session_key = f"auth:{username or 'anon'}"
    store_challenge(session_key, challenge)

    allow_credentials = []
    if username:
        result = await db.execute(
            select(WebAuthnCredential).join(User).where(User.username == username)
        )
        for cred in result.scalars().all():
            from webauthn.helpers.structs import PublicKeyCredentialDescriptor
            cred_id = base64.urlsafe_b64decode(cred.credential_id + "==")
            allow_credentials.append(
                PublicKeyCredentialDescriptor(id=cred_id)
            )

    opts = webauthn.generate_authentication_options(
        rp_id=RP_ID,
        challenge=challenge,
        allow_credentials=allow_credentials,
        user_verification=UserVerificationRequirement.PREFERRED,
        timeout=60000,
    )

    return webauthn.options_to_json(opts)


async def verify_authentication(
    credential_json: str,
    username: Optional[str],
    db: AsyncSession,
) -> User:
    """Verify authentication assertion — returns authenticated user."""
    import json as _json
    cred_data = _json.loads(credential_json)

    # Find credential by ID
    raw_id = cred_data.get("rawId") or cred_data.get("id", "")
    # Normalize to base64url without padding
    cred_id_lookup = raw_id.rstrip("=")

    result = await db.execute(
        select(WebAuthnCredential).where(
            WebAuthnCredential.credential_id == cred_id_lookup
        )
    )
    stored_cred = result.scalar_one_or_none()
    if not stored_cred:
        raise ValueError("Credential not found")

    challenge = get_challenge(f"auth:{username or 'anon'}")
    if not challenge:
        # Fallback: try without username
        challenge = get_challenge("auth:anon")
    if not challenge:
        raise ValueError("Challenge expired")

    pub_key_bytes = base64.urlsafe_b64decode(stored_cred.public_key + "==")
    cred_id_bytes = base64.urlsafe_b64decode(stored_cred.credential_id + "==")

    verification = webauthn.verify_authentication_response(
        credential=cred_data,
        expected_challenge=challenge,
        expected_rp_id=RP_ID,
        expected_origin=ORIGIN,
        credential_public_key=pub_key_bytes,
        credential_current_sign_count=stored_cred.sign_count,
        require_user_verification=False,
    )

    # Update sign count and last used
    stored_cred.sign_count = verification.new_sign_count
    stored_cred.last_used_at = datetime.utcnow()
    await db.commit()

    # Return user
    result = await db.execute(select(User).where(User.id == stored_cred.user_id))
    return result.scalar_one()


# ── Helpers ───────────────────────────────────────────────

# Known YubiKey AAGUIDs (partial list)
_YUBIKEY_AAGUIDS = {
    "2fc0579f-8113-47ea-b116-bb5a8db9202a": "YubiKey 5 NFC",
    "6d44ba9b-f6ec-2e49-b930-0c8fe920cb73": "YubiKey 5C NFC",
    "c1f9a0bc-1dd2-404a-b27f-8e29047a43fd": "YubiKey 5 Nano",
    "73bb0cd4-e502-49b8-9c6f-b59445bf720b": "YubiKey 5C",
    "85203421-48f9-4355-9bc8-8a53846e5083": "YubiKey 5Ci",
}

def _detect_device_name(aaguid: str) -> str:
    return _YUBIKEY_AAGUIDS.get(aaguid.lower(), "Security Key")
