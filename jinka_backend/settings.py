"""
jinki_backend/settings.py
Django + Channels settings for the Jinka Couple Sync backend.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# ── Security ──────────────────────────────────────────────────────────────────
SECRET_KEY = os.environ.get(
    'DJANGO_SECRET_KEY',
    'changeme-use-a-real-secret-in-production-please'
)
DEBUG = os.environ.get('DEBUG', 'false').lower() == 'true'

ALLOWED_HOSTS = os.environ.get(
    'ALLOWED_HOSTS',
    'localhost 127.0.0.1 jinki-backend.onrender.com'
).split()

# ── Apps ──────────────────────────────────────────────────────────────────────
INSTALLED_APPS = [
    'daphne',               # must be first so it owns the runserver command
    'django.contrib.staticfiles',
    'channels',
    'sync',                 # our WebSocket app
]

# ── Middleware ────────────────────────────────────────────────────────────────
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.middleware.common.CommonMiddleware',
]

ROOT_URLCONF = 'jinka_backend.urls'

# ── Static files ──────────────────────────────────────────────────────────────
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# ── ASGI / Channels ──────────────────────────────────────────────────────────
ASGI_APPLICATION = 'jinka_backend.asgi.application'

# Redis channel layer — falls back to in-memory if REDIS_URL is not set.
# In-memory layer works fine for a single-dyno Render deploy.
_REDIS_URL = os.environ.get('REDIS_URL', '')

if _REDIS_URL:
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels_redis.core.RedisChannelLayer',
            'CONFIG': {
                'hosts': [_REDIS_URL],
                # Keep messages small — each sync event is < 512 bytes
                'capacity': 100,
                'expiry': 5,
            },
        }
    }
else:
    # Zero-dependency fallback: works on Render free tier without Redis add-on
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels.layers.InMemoryChannelLayer',
        }
    }

# ── Logging ──────────────────────────────────────────────────────────────────
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {'console': {'class': 'logging.StreamHandler'}},
    'root': {'handlers': ['console'], 'level': 'INFO'},
}

# ── Internationalisation (minimal) ────────────────────────────────────────────
USE_TZ = True
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
