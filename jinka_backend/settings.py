import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file if it exists
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# ── Security ────────────────────────────────────────────────────────────────
# We pull the ALLOWED_HOSTS from the environment. 
# If not found, we use a safe default that includes your Render domain.
_allowed_hosts_env = os.environ.get(
    "ALLOWED_HOSTS", 
    "jinki-backend.onrender.com,localhost,127.0.0.1"
)
ALLOWED_HOSTS = [h.strip() for h in _allowed_hosts_env.split(",") if h.strip()]

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY", "insecure-dev-key-replace-in-production"
)

# Debug should be False in production (Render), True locally
DEBUG = os.environ.get("DEBUG", "True") == "True"

# ── Apps ────────────────────────────────────────────────────────────────────
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "corsheaders",
    "channels",
    "sync.apps.SyncConfig",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
]

# ── CORS / CSRF ──────────────────────────────────────────────────────────────
# Important for allowing your GitHub Pages frontend to talk to this backend
_cors_env = os.environ.get(
    "CORS_ALLOWED_ORIGINS",
    "https://muntasir-uwu.github.io,http://localhost:8000,http://127.0.0.1:8000",
)
CORS_ALLOWED_ORIGINS = [o.strip() for o in _cors_env.split(",") if o.strip()]
CSRF_TRUSTED_ORIGINS = CORS_ALLOWED_ORIGINS[:]
CORS_ALLOW_CREDENTIALS = True

# ── URLs / ASGI ──────────────────────────────────────────────────────────────
ROOT_URLCONF = "jinka_backend.urls"
ASGI_APPLICATION = "jinka_backend.asgi.application"

# ── Redis / Channels ─────────────────────────────────────────────────────────
# This connects your WebSocket logic to the Render Redis instance
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [REDIS_URL],
        },
    }
}

# ── Database ─────────────────────────────────────────────────────────────────
# SQLite is fine for small sync projects without persistent users
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# ── Misc ─────────────────────────────────────────────────────────────────────
STATIC_URL = "/static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Optional: Self-ping setting to keep the service awake
SELF_PING_URL = os.environ.get("SELF_PING_URL", "")
