"""Application configuration for RxSpark.

Secrets are read from environment variables or stored in the private
instance folder — never in frontend code.
"""
import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
INSTANCE_DIR = BASE_DIR / "instance"


def _load_secret_key() -> str:
    env_key = os.environ.get("RXSPARK_SECRET_KEY")
    if env_key:
        return env_key
    key_file = INSTANCE_DIR / "secret_key"
    if key_file.exists():
        return key_file.read_text(encoding="utf-8").strip()
    INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
    key = secrets.token_hex(32)
    key_file.write_text(key, encoding="utf-8")
    try:  # best-effort restriction on POSIX systems
        os.chmod(key_file, 0o600)
    except OSError:
        pass
    return key


def _load_ai_api_key() -> str:
    """AI provider key: environment variable first, else private instance folder."""
    env_key = os.environ.get("RXSPARK_AI_API_KEY")
    if env_key:
        return env_key
    key_file = INSTANCE_DIR / "ai_api_key"
    if key_file.exists():
        return key_file.read_text(encoding="utf-8").strip()
    return ""


class Config:
    DEBUG = os.environ.get("RXSPARK_DEBUG", "1") == "1"
    SECRET_KEY = _load_secret_key()
    DATABASE = str(INSTANCE_DIR / "rxspark.db")
    UPLOAD_FOLDER = str(INSTANCE_DIR / "uploads")
    MAX_CONTENT_LENGTH = 6 * 1024 * 1024  # 6 MB upload cap

    # Session security
    SESSION_IDLE_TIMEOUT = int(os.environ.get("RXSPARK_IDLE_TIMEOUT", 30 * 60))
    SESSION_ABSOLUTE_TIMEOUT = int(os.environ.get("RXSPARK_ABS_TIMEOUT", 12 * 3600))
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    # Demo / development mode (fictional data only)
    DEMO_MODE = os.environ.get("RXSPARK_DEMO_MODE", "1") == "1"

    # Email delivery (forgot-password). Not configured by default.
    MAIL_SERVER = os.environ.get("RXSPARK_MAIL_SERVER", "")
    MAIL_PORT = int(os.environ.get("RXSPARK_MAIL_PORT", "587"))
    MAIL_USERNAME = os.environ.get("RXSPARK_MAIL_USERNAME", "")
    MAIL_PASSWORD = os.environ.get("RXSPARK_MAIL_PASSWORD", "")
    MAIL_FROM = os.environ.get("RXSPARK_MAIL_FROM", "no-reply@rxspark.local")

    # Optional AI assistant (RxSpark AI Assistant) — assistive only.
    # Groq is OpenAI-compatible: any OpenAI-style base URL/model can be swapped in.
    AI_API_KEY = _load_ai_api_key()
    AI_BASE_URL = os.environ.get("RXSPARK_AI_BASE_URL", "https://api.groq.com/openai/v1")
    AI_MODEL = os.environ.get("RXSPARK_AI_MODEL", "openai/gpt-oss-120b")

    # Application labels
    APP_NAME = "RxSpark"
    APP_TAGLINE = "Smart Digital Prescription for Doctors"
