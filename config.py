import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
PORT = int(os.getenv("PORT", "10000"))
FILES_PER_PAGE = 6
WEBAPP_URL = os.getenv("WEBAPP_URL") or (f"{WEBHOOK_URL.rstrip('/')}/webapp" if WEBHOOK_URL else "https://telegram-drive-bot-0upd.onrender.com/webapp")

