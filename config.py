import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"].strip()
SUPABASE_URL = os.environ["SUPABASE_URL"].strip()
SUPABASE_KEY = os.environ["SUPABASE_KEY"].strip()
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
PORT = int(os.getenv("PORT", "10000"))
FILES_PER_PAGE = int(os.getenv("FILES_PER_PAGE", "6"))

_render_url = os.getenv("RENDER_EXTERNAL_URL", "").strip().rstrip("/")
if not _render_url and os.getenv("RENDER_EXTERNAL_HOSTNAME"):
    _render_url = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME').strip().rstrip('/')}"

PUBLIC_BASE_URL = (os.getenv("PUBLIC_BASE_URL") or WEBHOOK_URL or _render_url).rstrip("/")
WEBAPP_URL = os.getenv("WEBAPP_URL") or (f"{PUBLIC_BASE_URL}/webapp" if PUBLIC_BASE_URL else "")

# Security & Dev Auth
DEV_AUTH_ENABLED = os.getenv("DEV_AUTH_ENABLED", "false").lower() in ("true", "1", "yes")
_dev_user_raw = os.getenv("DEV_USER_ID", "")
DEV_USER_ID = int(_dev_user_raw) if _dev_user_raw and _dev_user_raw.isdigit() else None
INIT_DATA_MAX_AGE_SECONDS = int(os.getenv("INIT_DATA_MAX_AGE_SECONDS", "86400"))

# Upload security limits
MAX_UPLOAD_FILE_SIZE_MB = int(os.getenv("MAX_UPLOAD_FILE_SIZE_MB", "50"))
MAX_UPLOAD_BATCH_FILES = int(os.getenv("MAX_UPLOAD_BATCH_FILES", "20"))
MAX_UPLOAD_BATCH_MB = int(os.getenv("MAX_UPLOAD_BATCH_MB", "100"))

# Allowed Origins for CORS
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]

# Task 3A Local OCR Configuration
OCR_ENABLED = os.getenv("OCR_ENABLED", "false").lower() in ("true", "1", "yes")
MAX_OCR_IMAGE_SIZE_MB = int(os.getenv("MAX_OCR_IMAGE_SIZE_MB", "20"))
MAX_OCR_IMAGE_DIMENSION = int(os.getenv("MAX_OCR_IMAGE_DIMENSION", "10000"))
OCR_TIMEOUT_SECONDS = int(os.getenv("OCR_TIMEOUT_SECONDS", "15"))
OCR_DEFAULT_LANGUAGE = os.getenv("OCR_DEFAULT_LANGUAGE", "eng")

# Task 6A Telegram Standalone Browser Authentication (OIDC)
TELEGRAM_OIDC_CLIENT_ID = os.getenv("TELEGRAM_OIDC_CLIENT_ID", "").strip()
TELEGRAM_OIDC_CLIENT_SECRET = os.getenv("TELEGRAM_OIDC_CLIENT_SECRET", "").strip()
TELEGRAM_OIDC_REDIRECT_URI = os.getenv("TELEGRAM_OIDC_REDIRECT_URI", "").strip()
if not TELEGRAM_OIDC_REDIRECT_URI and PUBLIC_BASE_URL:
    TELEGRAM_OIDC_REDIRECT_URI = f"{PUBLIC_BASE_URL}/auth/telegram/callback"
TELEGRAM_OIDC_ISSUER = os.getenv("TELEGRAM_OIDC_ISSUER", "https://oauth.telegram.org").strip().rstrip("/")
TELEGRAM_OIDC_SCOPES = os.getenv("TELEGRAM_OIDC_SCOPES", "openid profile").strip()
TELEGRAM_OIDC_AUTH_URL = os.getenv("TELEGRAM_OIDC_AUTH_URL", f"{TELEGRAM_OIDC_ISSUER}/auth").strip()
TELEGRAM_OIDC_TOKEN_URL = os.getenv("TELEGRAM_OIDC_TOKEN_URL", f"{TELEGRAM_OIDC_ISSUER}/token").strip()
TELEGRAM_OIDC_JWKS_URL = os.getenv("TELEGRAM_OIDC_JWKS_URL", f"{TELEGRAM_OIDC_ISSUER}/.well-known/jwks.json").strip()


