"""
jinki_backend/asgi.py
ASGI config — routes HTTP to Django and WebSocket to Channels.
"""
import os
import django
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'jinki_backend.settings')
django.setup()

# Import routing AFTER django.setup() so apps are ready
from sync.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter({
    # Standard HTTP (health-check endpoint, etc.)
    'http': get_asgi_application(),

    # WebSocket: validate Origin header then route
    'websocket': AllowedHostsOriginValidator(
        URLRouter(websocket_urlpatterns)
    ),
})
