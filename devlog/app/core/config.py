"""Centralized configuration."""
from functools import lru_cache
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False)

    APP_NAME: str = "DevLog"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"
    SECRET_KEY: str = "change-me-in-production-min-32-chars!!"
    DEBUG: bool = False

    HOST: str = "0.0.0.0"
    PORT: int = 8000
    WORKERS: int = 4
    ALLOWED_HOSTS: List[str] = ["*"]
    CORS_ORIGINS: List[str] = ["*"]

    DATABASE_URL: str = "sqlite+aiosqlite:///./blog.db"
    REDIS_URL: str = "redis://localhost:6379/0"

    # WebAuthn / YubiKey
    WEBAUTHN_RP_ID: str = "localhost"
    WEBAUTHN_RP_NAME: str = "DevLog Blog"
    WEBAUTHN_ORIGIN: str = "http://localhost:8000"

    SESSION_COOKIE_NAME: str = "blog_session"
    SESSION_MAX_AGE: int = 86400 * 7

    # Clé secrète requise pour créer un compte admin
    # Changez cette valeur dans .env avant de déployer !
    ADMIN_KEY: str = "changez-moi-clé-admin-secrète"

    LOG_LEVEL: str = "INFO"


@lru_cache()
def get_settings() -> Settings:
    return Settings()

settings = get_settings()
