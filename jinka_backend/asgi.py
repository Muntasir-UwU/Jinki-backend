"""
ASGI config for jinka_backend.

WebSocket endpoint:  ws://<host>/ws/jinka/?user=<name>
HTTP endpoint:       http://<host>/health/
"""
import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from django.urls import path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "jinka_backend.settings")

# Must call get_asgi_application() before importing anything that touches Django models.
django_asgi_app = get_asgi_application()

# Import consumer here (after Django setup) to avoid AppRegistryNotReady errors.
from sync.consumers import JinkaConsumer  # noqa: E402

websocket_urlpatterns = [
    path("ws/jinka/", JinkaConsumer.as_asgi()),
]

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        # No AllowedHostsOriginValidator here — GitHub Pages is a different
        # origin from the backend, so we skip origin-based blocking.
        # Add your own origin check in consumers.py if you need stricter security.
        "websocket": URLRouter(websocket_urlpatterns),
    }
)
