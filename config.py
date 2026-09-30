import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"].strip()
SUPABASE_URL = os.environ["SUPABASE_URL"].strip()
SUPABASE_KEY = os.environ["SUPABASE_KEY"].strip()
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
PORT = int(os.getenv("PORT", "10000"))
FILES_PER_PAGE = int(os.getenv("FILES_PER_PAGE", "6"))

PUBLIC_BASE_URL = (os.getenv("PUBLIC_BASE_URL") or WEBHOOK_URL).rstrip("/")
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

